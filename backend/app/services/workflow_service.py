import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from langgraph.types import Command, GraphOutput
from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.session import SessionLocal, rows_to_dict
from app.db.models import ApiKey, Run, ScheduledJob, User, Workflow, WorkflowVersion
from app.runtime.workflow_config import SNAPSHOT_FIELDS, load_version_config, normalize_snapshot, resolve_live_config, snapshot_of
from app.services import api_key_service, run_service
from app.workflow import cancel as workflow_cancel
from app.workflow import runner as workflow_runner
from app.workflow.checkpointer import delete_thread_safely
from app.workflow.engine import WorkflowState, build_workflow
from app.workflow.io_contract import build_initial_state, end_outputs, start_variables
from app.workflow.validation import validate_graph

logger = logging.getLogger(__name__)


def check_graph(graph: dict) -> None:
    """图校验（FR-029）：保存与运行前显式调用。不能只靠 build_workflow 内部抛错 ——
    test_run_workflow / execute_workflow 会把执行期异常吞成 failed，400 到不了调用方，还会白建一条 failed 运行记录。
    公开导出：工作流对话（workflow_chat）在建设话之前也要用它，与运行同一套拒绝口径。"""
    errors = validate_graph(graph or {})
    if errors:
        raise BizError(400, "图校验失败：" + "；".join(errors))


SORTABLE = {"id": Workflow.id, "name": Workflow.name, "status": Workflow.status, "version": Workflow.version, "updated_at": Workflow.updated_at}


def _node_summary(graph: dict | None) -> tuple[int, dict]:
    """图里的节点数与按类型计数（在 Python 里数，graph 是 JSON）。"""
    nodes = (graph or {}).get("nodes") or []
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n.get("type", "unknown")] = by_type.get(n.get("type", "unknown"), 0) + 1
    return len(nodes), by_type


def _live_snapshots(db: Session, rows: list) -> dict[int, dict]:
    """一页工作流的线上快照：判断"有未发布修改"要拿草稿与它比，一次 IN 查询（不在循环里查库）。"""
    pairs = {(w.id, w.published_version) for w in rows if w.published_version is not None}
    if not pairs:
        return {}
    versions = db.query(WorkflowVersion).filter(
        tuple_(WorkflowVersion.workflow_id, WorkflowVersion.version).in_(pairs)
    ).all()
    return {v.workflow_id: normalize_snapshot(v.snapshot) for v in versions}


def _serialize(db: Session, rows: list, with_graph: bool = False) -> list[dict]:
    """一页工作流的关联装配：创建人、最近 7 天运行数与最近运行时间、定时任务数、线上快照，各一次查询。"""
    ids = {w.id for w in rows}
    creator_ids = {w.created_by for w in rows if w.created_by}
    creators = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    live = _live_snapshots(db, rows)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    # 近 7 天运行不计调试（docs/15 D-05；工作流调试台在第 2 批，口径先对齐）
    runs = {wid: (count, last) for wid, count, last in db.query(Run.workflow_id, func.count(Run.id), func.max(Run.started_at)).filter(
        Run.workflow_id.in_(ids), Run.started_at >= since, run_service.operational_only()).group_by(Run.workflow_id).all()} if ids else {}
    schedules = rows_to_dict(db.query(ScheduledJob.workflow_id, func.count(ScheduledJob.id)).filter(ScheduledJob.workflow_id.in_(ids)).group_by(ScheduledJob.workflow_id).all()) if ids else {}
    items = []
    for w in rows:
        node_count, node_types = _node_summary(w.graph)
        runs_7d, last_run = runs.get(w.id, (0, None))
        item = {
            "id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version,
            "node_count": node_count, "node_types": node_types, "schedules_count": int(schedules.get(w.id, 0)),
            "created_by": w.created_by, "created_by_username": creators.get(w.created_by),
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "updated_at": w.updated_at.isoformat() if w.updated_at else None,
            "runs_7d": int(runs_7d), "last_run_at": last_run.isoformat() if last_run else None,
            # 发布语义（FR-075）：线上版本号与时间；草稿与线上快照是否不同（计算值，不入库）
            "published_version": w.published_version,
            "published_at": w.published_at.isoformat() if w.published_at else None,
            "has_unpublished_changes": w.published_version is not None and snapshot_of(w) != live.get(w.id),
        }
        if with_graph:
            item["graph"] = w.graph
        items.append(item)
    return items


def list_workflows(db: Session, params: PageParams, q: str | None = None, status: str | None = None, sort: SortParams | None = None) -> dict:
    """分页列出工作流：q 名称模糊、状态精确，白名单排序；附节点数、创建人、最近 7 天运行数、定时任务数。"""
    query = db.query(Workflow)
    if q:
        query = query.filter(Workflow.name.ilike(f"%{q}%"))
    if status:
        query = query.filter(Workflow.status == status)
    page = paginate(apply_sort(query, sort, SORTABLE, [Workflow.id.asc()]), params)
    page["items"] = _serialize(db, page["items"])
    return page


def create_workflow(db: Session, data, user) -> dict:
    """新建工作流（graph 为图定义 JSON），记录创建人。图结构不合法 400。写审计 create。"""
    check_graph(data.graph)
    w = Workflow(name=data.name, description=data.description, graph=data.graph, created_by=user.id)
    db.add(w)
    db.commit()
    db.refresh(w)
    # 与列表/详情同一套字段（含 published_version / has_unpublished_changes）：前端新建后直接拿这个结果，
    # 少一套形状就得多一次详情请求；新建的必是草稿（从未发布），这里如实给出。
    record_audit(db, user, "create", "workflow", w.id, detail={"name": w.name})
    return _serialize(db, [w])[0]


def get_workflow(db: Session, workflow_id: int) -> Workflow:
    """按 ID 取工作流，不存在抛 BizError(404)。"""
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise BizError(404, "工作流不存在")
    return w


def get_workflow_detail(db: Session, workflow_id: int) -> dict:
    """取工作流详情：graph 定义、节点统计、绑定的定时任务，供编辑器与详情页加载。

    曾经还带一份"引用它的智能体"清单，取自 agents.workflow_id —— 那一列在对话链路里从未被读过，
    2026-11-18 按 docs/15 D-12 决策 A 删掉了，清单随之取消（工作流不再有"被智能体绑定"这种关系）。
    """
    w = get_workflow(db, workflow_id)
    schedules = [{"id": s.id, "name": s.name, "cron": s.cron, "is_enabled": s.is_enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
                 for s in db.query(ScheduledJob).filter(ScheduledJob.workflow_id == workflow_id).order_by(ScheduledJob.id).all()]
    return {**_serialize(db, [w], with_graph=True)[0], "schedules": schedules}


def workflow_parameters(db: Session, workflow_id: int, api_key: ApiKey | None = None) -> dict:
    """开始 / 结束节点的声明（docs/15 WF-04）：运行弹窗、定时任务表单与 API 访问页签按它生成表单项。

    返回变量列表（含是否必填：没有默认值即必填）与输出声明；声明本身不合法时 400，
    与运行时的报错口径一致，不让前端拿到一半能用的表单。

    api_key：API Key 调用时校验作用域。这个接口开放给了 Key（外部系统据此知道该传什么参数），
    就必须和 run / resume 同一口径 —— 否则只有 A 作用域的 Key 能枚举出全部工作流的接口契约，
    既是横向越权也是信息泄露（2026-11-14 审计的 IDOR）。
    """
    api_key_service.check_workflow_scope(api_key, workflow_id)
    # 读线上版本的声明（FR-075）：这个接口的契约是给外部调用方生成请求参数的，
    # 必须与实际会执行的图一致；读草稿会让外部系统按"还没上线"的声明填参，运行时却按线上版本校验。
    live = resolve_live_config(db, workflow_id)
    variables = [
        {"name": v.name, "type": v.type, "description": v.description, "default": v.default, "required": v.default is None}
        for v in start_variables(live.graph)
    ]
    outputs = [{"name": o.name, "ref": o.ref} for o in end_outputs(live.graph)]
    return {"workflow_id": live.workflow_id, "version": live.version, "variables": variables, "outputs": outputs}


def duplicate_workflow(db: Session, workflow_id: int, user) -> dict:
    """复制一份工作流（**草稿态、未发布**、修订号 1、名称加"副本"），供在既有编排上改出新流程。

    复制的是当前草稿还是线上版本？这里取草稿：复制动作发生在编辑场景，用户要的是"我现在看到的这张图"。
    复制品不继承发布状态 —— 它还没被任何人审过，直接对外可见是危险的。"""
    w = get_workflow(db, workflow_id)
    copy = Workflow(name=f"{w.name} 副本", description=w.description, graph=w.graph, created_by=user.id)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _serialize(db, [copy])[0]


def apply_batch_action(db: Session, workflow_id: int, action: str, user: User | None = None) -> None:
    """批量操作的单条执行（delete）；被智能体引用的 409 进失败清单。"""
    delete_workflow(db, workflow_id, user)


def update_workflow(db: Session, workflow_id: int, data, user: User | None = None) -> dict:
    """覆盖式更新工作流**草稿**，草稿修订号 +1，不生成版本快照、不影响线上（FR-075）。

    保存 ≠ 发布：改完图要点"发布"才对外生效。2026-11-15 前这里保存即上线，
    改一次图会立刻影响已绑定的定时任务与已发出的 API 调用方，出事无法回滚。
    写审计 update：发布语义下它只改草稿，但"谁在什么时候改了哪版草稿"仍是回滚时判断的依据。
    """
    check_graph(data.graph)
    w = get_workflow(db, workflow_id)
    w.name = data.name
    w.description = data.description
    w.graph = data.graph
    w.version = (w.version or 0) + 1
    db.commit()
    db.refresh(w)
    result = {**_serialize(db, [w])[0]}
    if user is not None:
        record_audit(db, user, "update", "workflow", w.id, detail={"name": w.name, "version": w.version})
    return result


def _lock_workflow(db: Session, workflow_id: int) -> Workflow:
    """SELECT … FOR UPDATE 锁住工作流行：发布与回滚上线要"读线上 → 比较 → 生成版本号"一气呵成，
    并发的第二个请求等锁，拿到锁后看到的已是新的线上版本（与 agent_service._lock_agent 同理，
    此前先读后写，并发发布会写出重复版本号）。"""
    w = db.query(Workflow).filter(Workflow.id == workflow_id).with_for_update().populate_existing().one_or_none()
    if w is None:
        raise BizError(404, "工作流不存在")
    return w


def _live_snapshot(db: Session, w: Workflow) -> dict | None:
    if w.published_version is None:
        return None
    wv = db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == w.id, WorkflowVersion.version == w.published_version).one_or_none()
    return normalize_snapshot(wv.snapshot) if wv else None


def _go_live(db: Session, w: Workflow, snapshot: dict, user: User, note: str | None) -> str:
    """让 snapshot 成为线上版本并返回 publish_result。与线上一致时不生成版本：已上线的返回 unchanged（幂等），
    否则生成新版本。

    版本号只按**快照序列**递增（最大快照号 + 1），不像智能体那样取 max(快照号, 行上的 version)：
    工作流的 workflows.version 是**草稿修订号**（每保存一次 +1，与发布无关），拿它参与取号会让
    发布版本号跟着草稿一起跳（存三次草稿再发布，线上直接从 v3 起），版本历史里全是空号。
    智能体那边反过来 —— agents.version 记的就是最近一次生成的版本号，两者语义不同，不能照抄。"""
    if _live_snapshot(db, w) == snapshot:
        if w.status == "published":
            return "unchanged"
        w.status = "published"
        return "published"
    latest = db.query(func.max(WorkflowVersion.version)).filter(WorkflowVersion.workflow_id == w.id).scalar()
    version = (latest or 0) + 1
    db.add(WorkflowVersion(workflow_id=w.id, version=version, snapshot=snapshot, created_by=user.id, note=note))
    w.published_version = version
    w.published_at = datetime.now(timezone.utc)
    w.status = "published"
    return "published"


def publish_workflow(db: Session, workflow_id: int, user: User, note: str | None = None) -> dict:
    """发布草稿：草稿成为新的线上版本（docs/15 FR-075）。发布前跑完整图校验，不通过 400 且不生成版本。
    草稿与线上一致时返回 unchanged 不生成版本（双击不会连出两个版本，与智能体同一语义）。"""
    w = _lock_workflow(db, workflow_id)
    check_graph(w.graph)
    result = _go_live(db, w, snapshot_of(w), user, note)
    db.commit()
    db.refresh(w)
    if result == "published":
        record_audit(db, user, "publish", "workflow", w.id, detail={"name": w.name, "version": w.published_version, "note": note})
    return {**_serialize(db, [w])[0], "publish_result": result}


def _get_version(db: Session, workflow_id: int, version_id: int) -> WorkflowVersion:
    wv = db.get(WorkflowVersion, version_id)
    if wv is None or wv.workflow_id != workflow_id:
        # 版本必须存在且属于该工作流，防止拿别的工作流的版本覆盖
        raise BizError(404, "版本不存在")
    return wv


def restore_version(db: Session, workflow_id: int, version_id: int, user: User) -> dict:
    """恢复到草稿：草稿 = 该版本快照，线上不变（与智能体 restore_version 同一语义）。
    只做结构校验，不跑发布校验 —— 允许把有问题的旧版本拉回草稿上修，发布时再拦。"""
    w = get_workflow(db, workflow_id)
    wv = _get_version(db, workflow_id, version_id)
    snap = normalize_snapshot(wv.snapshot)
    check_graph(snap["graph"])
    for field in SNAPSHOT_FIELDS:
        setattr(w, field, snap[field])
    w.version = (w.version or 0) + 1  # 草稿被改过，修订号 +1（线上版本号不动）
    db.commit()
    db.refresh(w)
    record_audit(db, user, "restore", "workflow", w.id, detail={"name": w.name, "version": wv.version})
    return _serialize(db, [w])[0]


def rollback_workflow(db: Session, workflow_id: int, version_id: int, user: User) -> dict:
    """回滚上线：用该版本快照生成一个新版本并置为线上，**草稿不动**（与智能体 rollback_agent 同一语义）。
    线上出事时一键止血，又不丢掉正在改的草稿。与线上一致时 unchanged（双击不会连出两个版本）。"""
    w = _lock_workflow(db, workflow_id)
    wv = _get_version(db, workflow_id, version_id)
    snap = normalize_snapshot(wv.snapshot)
    check_graph(snap["graph"])
    result = _go_live(db, w, snap, user, f"回滚到 v{wv.version}")
    db.commit()
    db.refresh(w)
    if result == "published":
        record_audit(db, user, "rollback", "workflow", w.id, detail={"name": w.name, "from_version": wv.version, "version": w.published_version})
    return {**_serialize(db, [w])[0], "publish_result": result}


def list_versions(db: Session, workflow_id: int, params: PageParams) -> dict:
    """分页列出发布版本（按版本号倒序）：附发布人、说明、是否线上、节点数与名称（一页各一次查询）。"""
    w = get_workflow(db, workflow_id)
    page = paginate(
        db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version.desc(), WorkflowVersion.id.desc()),
        params,
    )
    rows = page["items"]
    creator_ids = {v.created_by for v in rows if v.created_by}
    creators = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    page["items"] = [{
        "id": v.id, "version": v.version, "snapshot": normalize_snapshot(v.snapshot), "created_at": v.created_at.isoformat(),
        "created_by": v.created_by, "created_by_username": creators.get(v.created_by), "note": v.note,
        "is_live": w.status == "published" and v.version == w.published_version,
        "node_count": _node_summary((v.snapshot or {}).get("graph"))[0],
    } for v in rows]
    return page


def delete_workflow(db: Session, workflow_id: int, user: User | None = None) -> None:
    """删除工作流：关联数据全部由外键 CASCADE 级联删除。

    写审计 delete：这个操作会连带删掉该工作流的全部运行记录与会话（CASCADE），
    是最不该无声发生的一类删除。

    2026-11-18 起没有"被智能体引用则 409"这道检查了：agents.workflow_id 已按 docs/15 D-12
    决策 A 删掉，工作流与智能体之间只剩运行记录（runs.workflow_id）、会话
    （conversations.workflow_id）、定时任务（scheduled_jobs.workflow_id）三类级联关系，
    都是随删除一起带走的下游数据，不是拦住删除的引用。
    """
    w = get_workflow(db, workflow_id)
    name = w.name
    # runs / run_nodes / conversations / scheduled_jobs 由数据库外键 CASCADE 级联删除
    db.delete(w)
    db.commit()
    if user is not None:
        record_audit(db, user, "delete", "workflow", workflow_id, detail={"name": name})


def _interrupt_value(result: GraphOutput[WorkflowState]):
    """从 langgraph 结果中提取中断值：interrupts 里第一个中断的 value，没有中断返回 None。

    langgraph 1.2 起 invoke/ainvoke 的类型契约是 version="v2" 返回 GraphOutput（state 在 .value、
    中断在 .interrupts），v1 的 "__interrupt__" 键只是旧口径的兼容。两处运行路径统一按 v2 取值。
    """
    return result.interrupts[0].value if result.interrupts else None


async def test_run_workflow(graph: dict, inputs: dict | None, role: str | None = None) -> dict:
    """编辑器内测试运行：用**请求内联的 graph（草稿）**直接执行，不落库。图结构不合法 400、入参不合法 400
    （都在 try 之外，不能被吞成 failed）。

    **这是唯一读草稿的执行路径，刻意如此**：试跑的意义就是"改完图先预览效果再决定发不发布"，
    读线上版本会让预览所见非所得。其余四个入口（execute_workflow / 工作流对话 / 定时任务）一律读线上快照，
    不要为了"统一"把这里改成读快照。它也不建运行记录（不占配额、不进运营指标）。

    入参按开始节点声明校验（io_contract），与正式运行同一套规则——测试通过就意味着正式运行也能跑通。
    """
    check_graph(graph)
    initial = WorkflowState(**build_initial_state(graph, inputs))
    # 试运行没有外部可见的终态（不建运行记录），也不存在"过几天回来续跑"——所以**跑完就清**，
    # 放在 finally 里：中断、失败、成功三种结局都要清，否则编辑器点一次就永久留一份检查点。
    # 这是唯一允许在 awaiting_review 语义下清理的地方：它的 interrupt 只是回给前端的预览，没有 resume 入口。
    thread_id = "test-" + uuid.uuid4().hex[:12]
    try:
        g = build_workflow(graph, role=role)
        # 显式要 v2：结果按 GraphOutput 取值（state 在 .value、中断在 .interrupts），见 _interrupt_value
        result = await asyncio.to_thread(g.invoke, initial, {"configurable": {"thread_id": thread_id}}, version="v2")
        state = result.value
        iv = _interrupt_value(result)
        if iv is not None:
            return {"status": "awaiting_review", "interrupt": iv, "steps": state.get("steps", [])}
        return {"status": "success", "output": state.get("output"), "steps": state.get("steps", [])}
    except Exception as e:
        # 编辑器内测试不落库，失败只回给前端；日志是排查图配置错误的唯一线索
        logger.exception("工作流测试运行失败")
        return {"status": "failed", "error": str(e)}
    finally:
        # 清理失败只记日志（delete_thread_safely 内部处理）：不能因为回收不了检查点就让试运行报错
        delete_thread_safely(thread_id)


def _refresh_quietly(db: Session, run: Run) -> None:
    """把 run 对象与库里的最新行同步（取消等跨会话写入后必须先做）。

    刷新失败不该让执行线程崩掉：数据已经在库里，收尾失败只会让状态稍后被清理任务纠正，
    而在这里抛异常会把"运行已取消"变成"运行执行异常"，反而误导调用方。
    """
    try:
        db.refresh(run)
    except Exception:
        logger.warning("刷新运行记录失败 run_id=%s", run.id, exc_info=True)


def execute_workflow(db: Session, workflow_id: int, version: int, payload, run: Run, role: str | None = None) -> dict:
    """同步执行（或续跑）一张工作流图，并收尾运行记录。接口触发（线程池）、API Key、人工审核续跑与定时任务共用。

    **读的是线上发布的不可变快照，不是 workflows 行上的草稿**（FR-075）：按 (workflow_id, version) 取快照里的图。
    version 由调用方在建运行记录时从 published_version 定好并写进 runs.workflow_version，
    执行时用同一个版本 —— 中途有人发布也不会让"运行记录上的版本号"与"实际执行的图"对不上，
    人工审核中断后过几天再 resume，续跑的仍是当初那一版。

    payload 为首跑的初始 state，或人工审核后的 Command(resume=...)。
    thread_id 固定用 run.id：图编译时绑了 checkpointer，不传会直接抛错；resume 也靠它找回被中断的图。
    永不抛出：任何异常都落到 run.error 并返回 failed，调用方按返回值判断。

    **检查点清理只在两个终态分支做**（success / failed），awaiting_review 分支一行不动：
    那个分支的检查点是 resume 找回被 interrupt 的图的唯一依据，清掉之后审批一提交就找不到中断点、
    会从空 state 重跑（实测行为见 tests/test_checkpoint_postgres.py::test_awaiting_review_thread_must_survive_cleanup）。
    清理失败只记日志（delete_thread_safely），绝不影响已经定稿的运行结果。
    """
    run_id = run.id
    cancelled_at_end = False
    try:
        graph = build_workflow(load_version_config(db, workflow_id, version).graph, run_id=run_id, role=role)
        # 显式要 v2：结果按 GraphOutput 取值（state 在 .value、中断在 .interrupts），见 _interrupt_value
        result = graph.invoke(payload, {"configurable": {"thread_id": str(run_id)}}, version="v2")
    except workflow_cancel.RunCancelled:
        # 取消不是失败：调用方主动终止的，落 cancelled 而不是 failed（docs/15 WF-05）。
        # 先 refresh：取消接口在另一个会话里已经把行写成 cancelled，本会话的 run 对象还停在 running，
        # 不刷新就 finalize 会把 finished_at / latency_ms 覆盖成"执行线程发现取消的时刻"，与取消时间对不上。
        # finalize_run 本身幂等：刷新后若已是终态，它返回 False，一个字段都不改。
        logger.info("工作流运行已取消 run_id=%s workflow_id=%s", run_id, workflow_id)
        _refresh_quietly(db, run)
        run_service.finalize_run(db, run, "cancelled", error="运行已取消")
        delete_thread_safely(str(run_id))
        return {"run_id": run_id, "status": "cancelled"}
    except Exception as e:
        # 先判是不是"被取消"：RunCancelled 在节点里抛出后可能被框架包装成别的异常类型
        # （例如并行分支聚合时），只看异常类型会把它误判成执行失败、写一条假的 failed 日志。
        if workflow_cancel.is_cancelled(run_id):
            logger.info("工作流运行已取消 run_id=%s workflow_id=%s", run_id, workflow_id)
            _refresh_quietly(db, run)
            run_service.finalize_run(db, run, "cancelled", error="运行已取消")
            delete_thread_safely(str(run_id))
            return {"run_id": run_id, "status": "cancelled"}
        logger.exception("工作流执行失败 run_id=%s workflow_id=%s version=%s", run_id, workflow_id, version)
        run_service.finalize_run(db, run, "failed", error=str(e))
        # 终态：先收尾运行记录，再回收检查点。顺序反了的话"收尾失败"会连累检查点，留下一份没有主的快照
        delete_thread_safely(str(run_id))
        return {"run_id": run_id, "status": "failed", "error": str(e)}
    finally:
        # 取消标记用完即清（任何结局都要清）：留着就是内存泄漏，且会误伤同 id 的后续运行。
        # 清之前先读一次：取消可能恰好落在"图刚跑完、还没收尾"的缝里，下面的 success 分支要靠它让位。
        cancelled_at_end = workflow_cancel.is_cancelled(run_id)
        workflow_cancel.discard(run_id)

    if cancelled_at_end:
        # 图已经跑完，但取消在收尾前落地：尊重取消，不把结果写成 success（用户看到"取消了却成功"会困惑）。
        # 同样先 refresh：取消接口若已把行写成 cancelled，finalize_run 幂等返回 False，不覆盖它的终态时间。
        _refresh_quietly(db, run)
        run_service.finalize_run(db, run, "cancelled", error="运行已取消")
        delete_thread_safely(str(run_id))
        return {"run_id": run_id, "status": "cancelled"}

    state = result.value
    steps = state.get("steps", [])
    iv = _interrupt_value(result)
    if iv is not None:
        # 等待人工审核不是终态：不写 finished_at，resume 后再收尾。
        # 这里**绝不能**清理检查点 —— resume 要靠它找回被 interrupt 的图。
        run.status = "awaiting_review"
        run.output = {"interrupt": iv, "steps": steps}
        # 中断不是终态，但已经花掉的 token 要先落库：审批可能隔天才做，
        # 期间运营统计里这条运行不该显示成"0 token"。续跑结束后会用完整用量覆盖。
        run_service.apply_usage_by_model(db, run, state.get("usage_by_model") or {})
        db.commit()
        return {"run_id": run.id, "status": "awaiting_review", "interrupt": iv, "steps": steps}
    run_service.finalize_run(db, run, "success", output={"output": state.get("output"), "steps": steps},
                             usage_by_model=state.get("usage_by_model"))
    delete_thread_safely(str(run.id))
    return {"run_id": run.id, "status": "success", "output": state.get("output"), "steps": steps}


@dataclass(frozen=True)
class AcceptedRun:
    """202 语义的运行受理结果（docs/15 WF-05）：blocking 超时与 async 模式都只回 run_id 与状态，让调用方轮询。

    为什么要单独一个类型而不是往返回字典里塞标记字段：响应体必须与文档一致（{run_id, status}），
    多一个内部标记就是对外契约的噪声；由路由层据此把状态码改成 202，业务字段保持不变。
    """

    payload: dict


def _execute_in_background(run_id: int, workflow_id: int, version: int, initial: dict, role: str | None) -> dict:
    """后台线程里的执行入口：**自带 Session**，不复用请求会话。

    为什么不能复用：async 模式请求返回后 FastAPI 会关掉请求会话（get_db 的 finally），
    之后 run 对象是 detached 的 —— finalize_run 里改 run.status 再 commit 会静默丢掉收尾，
    运行记录永远停在 running。自己开一个会话，执行期的一切写入都是它自己的事务。
    """
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if run is None:  # 建记录与执行之间被删除（清理任务）：没有可收尾的对象，记日志即可
            logger.warning("工作流运行记录不存在，跳过执行 run_id=%s", run_id)
            return {"run_id": run_id, "status": "failed"}
        return execute_workflow(db, workflow_id, version, initial, run, role)
    finally:
        db.close()


async def run_workflow(db: Session, workflow_id: int, inputs: dict | None, user, api_key: ApiKey | None = None,
                       response_mode: str = "blocking") -> dict | AcceptedRun:
    """接口触发工作流：建运行记录后交给工作流专用线程池执行（不阻塞请求线程）。图结构或入参不合法 400 且不建运行记录。

    **读线上发布版本，不读草稿**（FR-075）：未发布 403「工作流未发布」且不建运行记录；
    入参按线上版本的开始节点声明校验 —— 草稿里改了变量声明不会让已发出的 API 调用方立刻失效，
    发布之后才切换。这样才能做到"改草稿不影响线上，出事能回滚"。

    api_key 不为空表示 Key 调用：工作流须在 Key 的作用域内（否则 403 且不建运行记录，docs/15 3.7.1——2026-10-05 前
    Key 能调归属人能调的任意工作流），运行记录 source=api_key 并记 api_key_id，与定时任务的 schedule 一起供运行记录页追溯。

    response_mode（WF-05）：
    - blocking（默认，存量调用方不受影响）：等执行结果，最多等 WORKFLOW_BLOCKING_TIMEOUT_S 秒；
      超时**只放弃等待、不取消执行**，返回 AcceptedRun 让调用方按 run_id 轮询。
      刻意不用 asyncio.wait_for 包 to_thread：wait_for 超时会 cancel 任务，图被中断在半路，
      运行记录永远停在 running（结果丢了，取消也取消不掉）。
    - async：建完运行记录立刻返回 AcceptedRun，后台继续跑。
    """
    api_key_service.check_workflow_scope(api_key, workflow_id)
    live = resolve_live_config(db, workflow_id)
    check_graph(live.graph)
    # 入参校验放在建运行记录之前：不合法不该留下一条 failed 运行
    initial = build_initial_state(live.graph, inputs)
    # 判满也在建运行记录之前：满了就 429，不能留一条永远没人执行的 running（调用方会以为在跑）
    slot = workflow_runner.acquire()
    try:
        # 记声明层面的入参字典（initial["vars"]），不是"主输入"——运行记录要能回答"这次填了什么"
        run = run_service.create_run(db, "workflow", user.id, workflow_id=workflow_id, input_data={"inputs": initial["vars"]},
                                     source="api_key" if api_key else "ui", api_key_id=api_key.id if api_key else None,
                                     workflow_version=live.version)
    except BaseException:
        workflow_runner.release(slot)  # 槽已占但任务没提交，必须在这里还回去
        raise
    run_id = run.id
    future = workflow_runner.submit(slot, _execute_in_background, run_id, workflow_id, live.version, initial, user.role)
    if response_mode == "async":
        return AcceptedRun({"run_id": run_id, "status": "running"})
    # 与 chat.py 的心跳同一写法：起成独立 Task，超时只放弃等待、不取消它。
    task = asyncio.wrap_future(future)
    done, _ = await asyncio.wait({task}, timeout=settings.WORKFLOW_BLOCKING_TIMEOUT_S)
    if not done:
        # 放弃等待后这个 Task 没人再取结果：加一个回调把异常取出来，否则 asyncio 会在 GC 时报
        # "Task exception was never retrieved"（噪音日志，且掩盖真正的失败原因）。
        # 取出来只记日志 —— 失败详情已经由 execute_workflow 写进 runs.error，调用方轮询能看到。
        task.add_done_callback(_log_abandoned_result)
        logger.info("工作流 blocking 等待超时，转后台继续执行 run_id=%s", run_id)
        return AcceptedRun({"run_id": run_id, "status": "running"})
    return task.result()


def _log_abandoned_result(task: "asyncio.Future") -> None:
    """blocking 超时后丢弃的 Task 的收尾：取出结果/异常，避免"未取回的异常"告警。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("blocking 超时后后台执行失败", exc_info=exc)


async def resume_workflow(db: Session, workflow_id: int, run_id: int, decision: dict, api_key: ApiKey | None = None) -> dict:
    """人工审核通过/驳回后续跑：仅允许 awaiting_review 状态的运行记录被 resume。
    Key 调用时工作流须在作用域内（403），且只能续跑这个 Key 自己发起的运行——别的 Key 或界面发起的一律 404「运行记录不存在」，
    不暴露存在性（docs/15 3.7.1；此前只校验运行属于该工作流，拿到 run_id 的任何 Key 都能替人审批）。JWT 请求的口径不变。

    **续跑用这次运行发起时的版本（runs.workflow_version），不是当前线上版本**：审批可能隔天才做，
    期间有人发不了新版，续跑必须接着当初那张图跑完，否则检查点里的节点与当前图对不上、执行语义也变了。
    只有本特性之前的运行（workflow_version 为空）才回落到当前线上版本。"""
    api_key_service.check_workflow_scope(api_key, workflow_id)
    run = db.get(Run, run_id)
    if run is None or run.workflow_id != workflow_id or (api_key is not None and run.api_key_id != api_key.id):
        raise BizError(404, "运行记录不存在")
    if run.status != "awaiting_review":
        raise BizError(400, "该运行不在待审核状态")
    version = run.workflow_version if run.workflow_version is not None else resolve_live_config(db, workflow_id).version
    # 取发起这一轮的用户角色（知识库检索要按它判可见性）；用户可能已被删除，那就按无角色处理
    executor = db.get(User, run.user_id) if run.user_id else None
    role = executor.role if executor is not None else None
    return await asyncio.to_thread(execute_workflow, db, workflow_id, version, Command(resume=decision), run, role)


def get_workflow_run(db: Session, workflow_id: int, run_id: int, api_key: ApiKey | None = None) -> dict:
    """查单条工作流运行（docs/15 WF-05）：允许 Key 调用，且只能查本 Key 发起的运行。

    行级校验与 resume_workflow 同一套口径：不属于该工作流、或不属于这个 Key，一律 404「运行记录不存在」，
    不暴露存在性（拿到 run_id 的任意 Key 不该能枚举别人的运行）。
    返回字段复用 run_service.get_run（含 input / output / nodes），与运行记录页一致。
    """
    _load_owned_run(db, workflow_id, run_id, api_key)
    return run_service.get_run(db, run_id)


def _load_owned_run(db: Session, workflow_id: int, run_id: int, api_key: ApiKey | None) -> Run:
    """取运行记录并做行级校验（工作流归属 + Key 归属）；不满足一律 404，不区分"不存在"与"无权"。

    resume_workflow 与 cancel/get 共用，避免三处各写一遍、日后只改一处导致口径漂移。
    """
    run = db.get(Run, run_id)
    if run is None or run.workflow_id != workflow_id or (api_key is not None and run.api_key_id != api_key.id):
        raise BizError(404, "运行记录不存在")
    return run


def cancel_workflow_run(db: Session, workflow_id: int, run_id: int, api_key: ApiKey | None = None) -> dict:
    """取消一条运行中的工作流（docs/15 WF-05）。

    用**带前置条件的 UPDATE**（id + workflow_id + status='running'）并按影响行数判断，而不是
    "先读后写"：两个并发取消请求只有一个能把 running 改成 cancelled，另一个按 rowcount=0 走下面的区分分支，
    不会互相覆盖，也不会把已经 success 的运行改成 cancelled（那个竞态会凭空造出一条"取消成功"的假记录）。

    rowcount=0 时再查一次区分三种情况（按 docs/15 的裁决）：
    - 已 cancelled：200，状态不变（重复取消是幂等的，客户端重试不该报错）；
    - 其它终态（success / failed / awaiting_review）：409，运行已经结束，取消没有意义；
    - 不存在 / 不属于该工作流 / 不属于本 Key：404，不暴露存在性。
    """
    run = _load_owned_run(db, workflow_id, run_id, api_key)
    now = datetime.now(timezone.utc)
    started_at = run.started_at
    # 耗时在这里一起算：带前置条件的 UPDATE 绕过了 finalize_run，不补的话被取消的运行 latency_ms 恒为 0，
    # 监控页会把它算成"0 耗时"而不是"跑了 N 秒后被取消"。
    values = {Run.status: "cancelled", Run.finished_at: now, Run.error: "运行已取消"}
    if started_at is not None:
        values[Run.latency_ms] = max(0, int((now - started_at).total_seconds() * 1000))
    cancelled = (
        db.query(Run)
        .filter(Run.id == run_id, Run.workflow_id == workflow_id, Run.status == "running")
        .update(values, synchronize_session=False)
    )
    db.commit()
    if cancelled:
        # 双写：库里是唯一可靠的终态（重启/多 worker 也认），进程内标记让正在跑的图在下一个节点边界就停
        workflow_cancel.mark(run_id)
        logger.info("工作流运行已取消 run_id=%s workflow_id=%s", run_id, workflow_id)
    # UPDATE 用了 synchronize_session=False，会话里可能还留着旧的 Run 对象，重新读一次拿准确状态
    db.expire_all()
    run = _load_owned_run(db, workflow_id, run_id, api_key)
    if cancelled or run.status == "cancelled":
        return {"run_id": run.id, "status": "cancelled"}
    raise BizError(409, f"运行已结束（{run.status}），无法取消")


def list_workflow_runs(db: Session, workflow_id: int, params: PageParams, status: str | None = None,
                       started_from=None, started_to=None, sort: SortParams | None = None) -> dict:
    """分页列出某工作流的运行记录（委托给 run_service，字段、过滤与排序和全局运行记录页一致）。"""
    get_workflow(db, workflow_id)
    return run_service.list_runs(db, params, run_type="workflow", status=status, workflow_id=workflow_id,
                                 started_from=started_from, started_to=started_to, sort=sort)
