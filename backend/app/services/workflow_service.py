import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from langgraph.types import Command
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, Run, ScheduledJob, User, Workflow
from app.services import run_service
from app.workflow.engine import build_workflow
from app.workflow.validation import validate_graph

logger = logging.getLogger(__name__)


def _check_graph(graph: dict) -> None:
    """图校验（FR-029）：保存与运行前显式调用。不能只靠 build_workflow 内部抛错 ——
    test_run_workflow / execute_workflow 会把执行期异常吞成 failed，400 到不了调用方，还会白建一条 failed 运行记录。"""
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


def _serialize(db: Session, rows: list, with_graph: bool = False) -> list[dict]:
    """一页工作流的关联装配：创建人、最近 7 天运行数与最近运行时间、定时任务数，各一次查询。"""
    ids = {w.id for w in rows}
    creator_ids = {w.created_by for w in rows if w.created_by}
    creators = dict(db.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()) if creator_ids else {}
    since = datetime.now(timezone.utc) - timedelta(days=7)
    runs = {wid: (count, last) for wid, count, last in db.query(Run.workflow_id, func.count(Run.id), func.max(Run.started_at)).filter(Run.workflow_id.in_(ids), Run.started_at >= since).group_by(Run.workflow_id).all()} if ids else {}
    schedules = dict(db.query(ScheduledJob.workflow_id, func.count(ScheduledJob.id)).filter(ScheduledJob.workflow_id.in_(ids)).group_by(ScheduledJob.workflow_id).all()) if ids else {}
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
        }
        if with_graph:
            item["graph"] = w.graph
        items.append(item)
    return items


def list_workflows(db: Session, params: PageParams, q: str = None, status: str = None, sort: SortParams = None) -> dict:
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
    """新建工作流（graph 为图定义 JSON），记录创建人。图结构不合法 400。"""
    _check_graph(data.graph)
    w = Workflow(name=data.name, description=data.description, graph=data.graph, created_by=user.id)
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "description": w.description, "status": w.status, "version": w.version}


def get_workflow(db: Session, workflow_id: int) -> Workflow:
    """按 ID 取工作流，不存在抛 BizError(404)。"""
    w = db.get(Workflow, workflow_id)
    if w is None:
        raise BizError(404, "工作流不存在")
    return w


def get_workflow_detail(db: Session, workflow_id: int) -> dict:
    """取工作流详情：graph 定义、节点统计、引用它的智能体、绑定的定时任务，供编辑器与详情页加载。"""
    w = get_workflow(db, workflow_id)
    agents = [{"id": a.id, "name": a.name, "status": a.status} for a in db.query(Agent).filter(Agent.workflow_id == workflow_id).order_by(Agent.id).all()]
    schedules = [{"id": s.id, "name": s.name, "cron": s.cron, "is_enabled": s.is_enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
                 for s in db.query(ScheduledJob).filter(ScheduledJob.workflow_id == workflow_id).order_by(ScheduledJob.id).all()]
    return {**_serialize(db, [w], with_graph=True)[0], "agents": agents, "schedules": schedules}


def duplicate_workflow(db: Session, workflow_id: int, user) -> dict:
    """复制一份工作流（草稿态、版本 1、名称加"副本"），供在既有编排上改出新流程。"""
    w = get_workflow(db, workflow_id)
    copy = Workflow(name=f"{w.name} 副本", description=w.description, graph=w.graph, created_by=user.id)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _serialize(db, [copy])[0]


def apply_batch_action(db: Session, workflow_id: int, action: str) -> None:
    """批量操作的单条执行（delete）；被智能体引用的 409 进失败清单。"""
    delete_workflow(db, workflow_id)


def update_workflow(db: Session, workflow_id: int, data) -> dict:
    """覆盖式更新工作流图，版本号 +1（草稿迭代，不生成历史快照）。图结构不合法 400。"""
    _check_graph(data.graph)
    w = get_workflow(db, workflow_id)
    w.name = data.name
    w.description = data.description
    w.graph = data.graph
    w.version = (w.version or 0) + 1
    db.commit()
    db.refresh(w)
    return {"id": w.id, "name": w.name, "version": w.version}


def delete_workflow(db: Session, workflow_id: int) -> None:
    """删除工作流：先检查智能体引用（RESTRICT），其余关联数据由外键 CASCADE 级联删除。"""
    w = get_workflow(db, workflow_id)
    # agents.workflow_id 为 RESTRICT，删除前给出友好提示
    ref_count = db.query(Agent).filter(Agent.workflow_id == workflow_id).count()
    if ref_count:
        raise BizError(409, f"该工作流已被 {ref_count} 个智能体引用，无法删除")
    # runs / run_nodes / conversations / workflow_nodes / scheduled_jobs 由数据库外键 CASCADE 级联删除
    db.delete(w)
    db.commit()


def _interrupt_value(result: dict):
    """从 langgraph 结果中提取中断值：__interrupt__ 里第一个元素的 value（或元素本身）。"""
    iv = result.get("__interrupt__")
    if iv:
        first = iv[0]
        return getattr(first, "value", first)
    return None


async def test_run_workflow(graph: dict, input_text: str, role: str = None) -> dict:
    """编辑器内测试运行：用当前图直接执行，不落库。图结构不合法 400（在 try 之外，不能被吞成 failed）。"""
    _check_graph(graph)
    try:
        g = build_workflow(graph, role=role)
        thread_id = "test-" + uuid.uuid4().hex[:12]
        result = await asyncio.to_thread(g.invoke, {"input": input_text, "steps": []}, {"configurable": {"thread_id": thread_id}})
        iv = _interrupt_value(result)
        if iv is not None:
            return {"status": "awaiting_review", "interrupt": iv, "steps": result.get("steps", [])}
        return {"status": "success", "output": result.get("output"), "steps": result.get("steps", [])}
    except Exception as e:
        # 编辑器内测试不落库，失败只回给前端；日志是排查图配置错误的唯一线索
        logger.exception("工作流测试运行失败")
        return {"status": "failed", "error": str(e)}


def execute_workflow(db: Session, workflow: Workflow, run: Run, payload, role: str = None) -> dict:
    """同步执行（或续跑）一张工作流图，并收尾运行记录。接口触发（线程池）与定时任务（调度线程）共用。

    payload 为首跑的初始 state，或人工审核后的 Command(resume=...)。
    thread_id 固定用 run.id：图编译时绑了 checkpointer，不传会直接抛错；resume 也靠它找回被中断的图。
    永不抛出：任何异常都落到 run.error 并返回 failed，调用方按返回值判断。
    """
    try:
        graph = build_workflow(workflow.graph, run_id=run.id, role=role)
        result = graph.invoke(payload, {"configurable": {"thread_id": str(run.id)}})
    except Exception as e:
        logger.exception("工作流执行失败 run_id=%s workflow_id=%s", run.id, workflow.id)
        run_service.finalize_run(db, run, "failed", error=str(e))
        return {"run_id": run.id, "status": "failed", "error": str(e)}

    steps = result.get("steps", [])
    iv = _interrupt_value(result)
    if iv is not None:
        # 等待人工审核不是终态：不写 finished_at，resume 后再收尾
        run.status = "awaiting_review"
        run.output = {"interrupt": iv, "steps": steps}
        db.commit()
        return {"run_id": run.id, "status": "awaiting_review", "interrupt": iv, "steps": steps}
    run_service.finalize_run(db, run, "success", output={"output": result.get("output"), "steps": steps})
    return {"run_id": run.id, "status": "success", "output": result.get("output"), "steps": steps}


async def run_workflow(db: Session, workflow_id: int, input_text: str, user, source: str = "ui") -> dict:
    """接口触发工作流：建运行记录后在独立线程执行（不阻塞请求线程）。图结构不合法 400 且不建运行记录。
    source 记录触发来源（ui / api_key），与定时任务的 schedule 一起供运行记录页追溯。"""
    w = get_workflow(db, workflow_id)
    _check_graph(w.graph)
    run = run_service.create_run(db, "workflow", user.id, workflow_id=workflow_id, input_data={"input": input_text, "source": source})
    return await asyncio.to_thread(execute_workflow, db, w, run, {"input": input_text, "steps": []}, user.role)


async def resume_workflow(db: Session, workflow_id: int, run_id: int, decision: dict) -> dict:
    """人工审核通过/驳回后续跑：仅允许 awaiting_review 状态的运行记录被 resume。"""
    w = get_workflow(db, workflow_id)
    run = db.get(Run, run_id)
    if run is None or run.workflow_id != workflow_id:
        raise BizError(404, "运行记录不存在")
    if run.status != "awaiting_review":
        raise BizError(400, "该运行不在待审核状态")
    role = db.get(User, run.user_id).role if run.user_id else None
    return await asyncio.to_thread(execute_workflow, db, w, run, Command(resume=decision), role)


def list_workflow_runs(db: Session, workflow_id: int, params: PageParams, status: str = None,
                       started_from=None, started_to=None, sort: SortParams = None) -> dict:
    """分页列出某工作流的运行记录（委托给 run_service，字段、过滤与排序和全局运行记录页一致）。"""
    get_workflow(db, workflow_id)
    return run_service.list_runs(db, params, run_type="workflow", status=status, workflow_id=workflow_id,
                                 started_from=started_from, started_to=started_to, sort=sort)
