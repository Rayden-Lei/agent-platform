from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import BigInteger, case, cast, func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.session import rows_to_dict
from app.db.models import Agent, ModelConfig, Run, RunNode, User, Workflow
from app.workflow.checkpointer import delete_thread_safely

# 运行记录的终态。awaiting_review 不是终态：它不写 finished_at，等待 resume 后再收尾。
FINAL_STATUSES = ("success", "failed", "cancelled")
RUN_STATUSES = ("running", "success", "failed", "cancelled", "awaiting_review")
# 触发来源（runs.source 列，2026-09-25 前只写在 input.source）：登录对话 / 界面运行工作流 / API Key（对话或工作流）/
# 定时任务 / 装配页调试。运营指标默认排除 debug（docs/15 D-05）
RUN_SOURCES = ("chat", "ui", "api_key", "schedule", "debug", "share")  # share：分享链接的访客对话（docs/15 3.6，带 share_id）

# 卡住运行被人工终止时写进 runs.error 的原因（docs/15 OP-10）。
# 写成固定文案而不是让调用方自由输入：运行记录页要能按它区分"真的执行失败"与"没人收尾被清理掉"。
STUCK_RUN_REASON = "运行超时未收尾，已人工终止"

# 列表排序白名单（字段名不能拼进 SQL）
SORTABLE = {"id": Run.id, "started_at": Run.started_at, "finished_at": Run.finished_at, "latency_ms": Run.latency_ms, "cost": Run.cost}
# 耗时分布的桶边界（毫秒），与前端"耗时分布"图一致
LATENCY_BUCKETS = [(0, 1000, "<1s"), (1000, 3000, "1-3s"), (3000, 10000, "3-10s"), (10000, 30000, "10-30s"), (30000, 60000, "30-60s"), (60000, None, ">60s")]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def operational_only():
    """运营指标的过滤条件：不计装配页调试（docs/15 D-05）。工作台、智能体 / 工作流统计、列表的近 7 天运行都用它；
    按模型的消耗照常计入（调试花的钱要能追溯），运行记录页不排除、可按来源筛出。"""
    return Run.source != "debug"


def create_run(db: Session, run_type: str, user_id: int, agent_id: int | None = None, workflow_id: int | None = None,
               input_data: dict | None = None, model_id: int | None = None, conversation_id: int | None = None, *,
               source: str, agent_version: int | None = None, workflow_version: int | None = None, api_key_id: int | None = None,
               schedule_id: int | None = None, share_id: int | None = None, commit: bool = True) -> Run:
    """创建运行记录并写入 started_at。所有产生 Run 的入口（对话/工作流/定时任务/调试）都必须走这里，
    否则 latency_ms 无法计算、监控页耗时永远是 0。model_id / conversation_id / agent_version / workflow_version 是统计与追溯用的快照。

    source 必须显式传（没有默认值）：漏传会被当成界面触发，调试流量就混进运营指标。input 只放本次的业务输入，
    来源等元数据走列（2026-09-25 前写在 input.source / input.scheduled）。
    commit=False 时只 flush（拿到 id），由调用方与同一事务里的其他写入一起提交：对话要让用户消息与运行记录原子落库（幂等回放靠这条关联）。
    """
    if source not in RUN_SOURCES:
        raise ValueError(f"运行来源只能是 {RUN_SOURCES}，收到: {source}")
    run = Run(
        run_type=run_type, agent_id=agent_id, workflow_id=workflow_id, user_id=user_id,
        model_id=model_id, conversation_id=conversation_id, source=source, agent_version=agent_version,
        workflow_version=workflow_version, api_key_id=api_key_id, schedule_id=schedule_id, share_id=share_id,
        status="running", input=input_data or {}, started_at=_now(),
    )
    db.add(run)
    if not commit:
        db.flush()
        return run
    db.commit()
    db.refresh(run)
    return run


def finalize_run(db: Session, run: Run, status: str, output: dict | None = None, error: str | None = None,
                 usage: dict | None = None, usage_by_model: dict | None = None) -> bool:
    """把运行记录置为终态，并写 finished_at / latency_ms / cost 快照。返回是否实际做了收尾。

    幂等：已处于终态的记录直接返回 False、不做任何改动，保证首次收尾结果不被覆盖
    （典型场景：流式对话已正常 done，随后客户端断开又触发一次取消收尾）。
    成本按收尾时的模型单价折算后落库，之后改单价不追溯，趋势图不会被重写。

    usage_by_model（工作流用）：{模型 id: {prompt_tokens, completion_tokens, total_tokens}}。
    一条工作流可以挂多个不同模型的智能体节点，单一 model_id 算不出正确成本，所以按模型分别折算后相加；
    run.model_id 记用量最大的那个模型，只作为列表展示与筛选的归属（不是成本口径）。
    """
    if status not in FINAL_STATUSES:
        raise ValueError(f"finalize_run 只接受终态 {FINAL_STATUSES}，收到: {status}")
    if run.status in FINAL_STATUSES:
        return False
    run.status = status
    if output is not None:
        run.output = output
    if usage is not None:
        run.token_usage = usage
    if error:
        run.error = str(error)[:2000]
    finished_at = _now()
    run.finished_at = finished_at
    # 取到局部变量再算：run.started_at 是 Mapped[datetime | None]，属性访问的收窄在不同检查器下
    # 不稳定（赋值另一个属性就会失效），局部变量的收窄是确定的。
    started_at = run.started_at
    if started_at is not None:
        run.latency_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    if usage_by_model:
        apply_usage_by_model(db, run, usage_by_model)
    elif run.token_usage and run.model_id:
        run.cost = _cost(run.token_usage, db.get(ModelConfig, run.model_id))
    db.commit()
    return True


def aggregate_usage(usage_by_model: dict | None) -> dict:
    """把按模型拆分的用量汇总成 runs.token_usage 的口径（三键合计）。无用量时返回空字典。"""
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for usage in (usage_by_model or {}).values():
        for k in total:
            total[k] += int((usage or {}).get(k) or 0)
    return total if any(total.values()) else {}


def apply_usage_by_model(db: Session, run: Run, usage_by_model: dict) -> None:
    """工作流收尾：写总用量、按模型分别折算成本相加、model_id 归属到用量最大的模型。

    为什么要按模型分别算：单价挂在 models 行上，一张图里 A 节点用便宜模型、B 节点用贵模型，
    用其中一个的单价乘总量会得出一个既不是 A 也不是 B 的数字。

    人工审核中断时也会调它一次（不 commit），让"等待审核"的运行在界面上先看到已花掉的量；
    续跑结束后 finalize_run 会用完整用量覆盖，不会重复累加。
    """
    normalized: dict[int, dict] = {}
    for mid, usage in usage_by_model.items():
        try:
            key = int(mid)
        except (TypeError, ValueError):
            continue
        normalized[key] = {k: int((usage or {}).get(k) or 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    if not normalized:
        return
    run.token_usage = aggregate_usage({str(k): v for k, v in normalized.items()})
    models = {m.id: m for m in db.query(ModelConfig).filter(ModelConfig.id.in_(list(normalized))).all()}
    costs = [_cost(usage, models.get(mid)) for mid, usage in normalized.items()]
    known = [c for c in costs if c is not None]
    # 全部模型都没配单价时保持 None（与对话口径一致：没配单价就不编一个 0 出来）
    run.cost = round(sum(known), 6) if known else None
    run.model_id = max(normalized, key=lambda mid: normalized[mid]["total_tokens"])


def _cost(token_usage: dict, model: ModelConfig | None):
    """按模型单价（元 / 百万 token）折算成本；无用量、无模型或未配单价时为 None。"""
    if not token_usage or model is None or (model.price_input is None and model.price_output is None):
        return None
    prompt = token_usage.get("prompt_tokens") or 0
    completion = token_usage.get("completion_tokens") or 0
    return round(prompt / 1000000 * (model.price_input or 0) + completion / 1000000 * (model.price_output or 0), 6)


def stuck_cutoff(now: datetime | None = None) -> datetime:
    """卡住运行的判定线：早于这个时刻仍处于 running 的运行，视为进程被杀后没收尾的幽灵记录。

    阈值走配置 STUCK_RUN_MINUTES（docs/15 OP-10）。工作台 pending.stuck_running 与本模块的
    处置入口必须用同一个函数取判定线，否则会出现"工作台报有卡住的、点处置却说过期不够"的错位。
    """
    return (now or _now()) - timedelta(minutes=settings.STUCK_RUN_MINUTES)


def stuck_condition(cutoff: datetime):
    """卡住运行的 SQL 条件：仍是 running，且发起时间早于判定线。

    公开（不带下划线）：工作台 stats_service 的 pending.stuck_running 要用同一个条件，
    两处口径必须一致 —— 各写一份 SQL 迟早会漂移成"工作台说有卡住的、运行记录页筛不出来"。
    

    started_at 为空的也要算进来：这类行是 2026-09-25 之前直接 Run(...) 构造出来的（当时
    create_run 还不写 started_at），它们永远不会有 finished_at，不纳入就永久占着 running 计数、
    也永远没有处置入口。它们必然不是当前进程刚起的运行，按"已超期"处理是安全的。
    """
    return (Run.status == "running") & ((Run.started_at < cutoff) | Run.started_at.is_(None))


def fail_stuck_run(db: Session, run_id: int, user: User | None = None) -> dict:
    """把一条卡住的运行置为 failed，并回收它的工作流检查点（docs/15 OP-10）。返回处置结果。

    为什么需要：进程被 kill（部署、OOM、Ctrl-C）时正在执行的运行没有任何人收尾，
    记录会永久停在 running —— 工作台一直报"卡住 N 个"，运行记录页却没有任何终止入口，
    只能连库改数据。docs/15 里记录过共享库长期挂着一条超过 1 小时的 running。

    前置条件（都不满足即拒绝，不是"先查后改"）：
    - 记录存在，否则 404；
    - 当前必须是 running，已终态 409（不要用本接口改写成功/失败的运行）；
    - 已超过 STUCK_RUN_MINUTES 仍 running，否则 400 —— 阈值存在的意义就是防止把
      "还在正常执行的长工作流"当成卡住处置掉。本接口只改数据库状态，**不会中断仍在执行的线程**，
      所以宁可拒绝也不能提前放行。

    并发：用 SELECT ... FOR UPDATE 锁住这一行再判断，两个管理员同时点只会有一次生效，
    第二次拿到锁时看到的已是 failed（与 workflow_service._lock_workflow 同一手法）。
    不用裸 UPDATE 的原因：收尾必须经 finalize_run 写 finished_at / latency_ms / cost 快照
    （05 铁律 4：运行记录只能经 create_run / finalize_run 收尾），裸 UPDATE 会把这几列漏掉，
    于是"处置后"的运行耗时仍是 0、统计里既不在 running 也不在已结束。

    检查点：复用 checkpointer.delete_thread_safely（失败只记日志），顺序是先收尾再清理 ——
    反过来的话"收尾失败"会连累检查点，留下一份没有主的快照（与 execute_workflow 同一口径）。
    """
    run = db.query(Run).filter(Run.id == run_id).with_for_update().populate_existing().one_or_none()
    if run is None:
        raise BizError(404, "运行记录不存在")
    if run.status != "running":
        raise BizError(409, f"该运行当前状态为 {run.status}，只有运行中的运行才能标记为失败")
    cutoff = stuck_cutoff()
    started_at = run.started_at
    if started_at is not None and started_at >= cutoff:
        raise BizError(400, f"该运行发起不足 {settings.STUCK_RUN_MINUTES} 分钟，仍在正常执行窗口内，不能处置")

    finalize_run(db, run, "failed", error=STUCK_RUN_REASON)
    delete_thread_safely(str(run.id))
    if user is not None:
        record_audit(db, user, "mark_failed", "run", run.id, detail={
            "run_type": run.run_type, "workflow_id": run.workflow_id, "agent_id": run.agent_id,
            "previous_status": "running", "started_at": _iso(started_at),
            "stuck_minutes": settings.STUCK_RUN_MINUTES, "reason": STUCK_RUN_REASON,
        })
    return {"id": run.id, "status": run.status, "error": run.error, "finished_at": _iso(run.finished_at)}


def apply_batch_action(db: Session, run_id: int, action: str, user: User) -> None:
    """批量操作的单条执行（mark_failed）；被 core.batch.run_batch 逐条调用，失败进失败清单。"""
    if action == "mark_failed":
        fail_stuck_run(db, run_id, user)
        return
    # 路由用 Literal 收窄过 action，走到这里说明调用方绕过了路由（脚本/内部调用）：显式报错，不静默成功
    raise BizError(400, f"不支持的批量操作：{action}")


class _Related:
    """一页运行记录的关联名称（智能体、模型、工作流、用户）：各批量查一次，内存装配；不逐行查库。"""

    def __init__(self, db: Session, runs: list):
        agent_ids = {r.agent_id for r in runs if r.agent_id}
        model_ids = {r.model_id for r in runs if r.model_id}
        workflow_ids = {r.workflow_id for r in runs if r.workflow_id}
        user_ids = {r.user_id for r in runs if r.user_id}
        self.agents = rows_to_dict(db.query(Agent.id, Agent.name).filter(Agent.id.in_(agent_ids)).all()) if agent_ids else {}
        self.models = rows_to_dict(db.query(ModelConfig.id, ModelConfig.name).filter(ModelConfig.id.in_(model_ids)).all()) if model_ids else {}
        self.workflows = rows_to_dict(db.query(Workflow.id, Workflow.name).filter(Workflow.id.in_(workflow_ids)).all()) if workflow_ids else {}
        self.users = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}

    def to_dict(self, run: Run) -> dict:
        return {
            **_run_dict(run),
            "agent_name": self.agents.get(run.agent_id) if run.agent_id else None,
            "model_name": self.models.get(run.model_id) if run.model_id else None,
            "workflow_name": self.workflows.get(run.workflow_id) if run.workflow_id else None,
            "username": self.users.get(run.user_id) if run.user_id else None,
        }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _run_dict(r: Run) -> dict:
    """运行记录 → 对外字典。来源、定时任务、API Key、智能体版本都是列，方便追溯触发来源与回答用的配置。"""
    return {
        "id": r.id, "run_type": r.run_type, "agent_id": r.agent_id, "workflow_id": r.workflow_id, "user_id": r.user_id,
        "model_id": r.model_id, "conversation_id": r.conversation_id,
        "source": r.source, "schedule_id": r.schedule_id, "api_key_id": r.api_key_id, "share_id": r.share_id,
        "agent_version": r.agent_version, "workflow_version": r.workflow_version,
        "status": r.status, "error": r.error, "output": r.output, "latency_ms": r.latency_ms,
        "token_usage": r.token_usage, "cost": r.cost,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
    }


def _filtered(db: Session, run_type: str | None = None, status: str | None = None, agent_id: int | None = None, workflow_id: int | None = None,
              user_id: int | None = None, model_id: int | None = None, source: str | None = None,
              started_from: datetime | None = None, started_to: datetime | None = None,
              stuck: bool | None = None):
    """列表与汇总共用的过滤条件：精确过滤 + 发起时间左闭右开区间 + 卡住运行筛选。"""
    query = db.query(Run)
    if stuck:
        # 只筛"超过阈值仍 running"的（docs/15 OP-10）：运行记录页的"卡住的运行"页签靠它列出待处置项。
        # stuck=False 不做事：它表达的是"不筛"，不是"筛出没卡住的"—— 后者与 status 筛选语义重叠。
        query = query.filter(stuck_condition(stuck_cutoff()))
    if run_type:
        query = query.filter(Run.run_type == run_type)
    if status:
        query = query.filter(Run.status == status)
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if workflow_id:
        query = query.filter(Run.workflow_id == workflow_id)
    if user_id:
        query = query.filter(Run.user_id == user_id)
    if model_id:
        query = query.filter(Run.model_id == model_id)
    if source:
        query = query.filter(Run.source == source)
    if started_from is not None:
        query = query.filter(Run.started_at >= started_from)
    if started_to is not None:
        query = query.filter(Run.started_at < started_to)
    return query


def list_runs(db: Session, params: PageParams, run_type: str | None = None, status: str | None = None,
              agent_id: int | None = None, workflow_id: int | None = None, user_id: int | None = None, model_id: int | None = None, source: str | None = None,
              started_from: datetime | None = None, started_to: datetime | None = None, sort: SortParams | None = None,
              stuck: bool | None = None) -> dict:
    """分页查询运行记录：精确过滤 + 时间区间 + 白名单排序（默认 id 倒序）；
    返回前为一页数据批量装配关联名称（智能体、模型、工作流、用户各查一次，不在循环内查库）。
    stuck=True 只返回超过 STUCK_RUN_MINUTES 仍 running 的运行（待人工处置的）。"""
    query = _filtered(db, run_type, status, agent_id, workflow_id, user_id, model_id, source, started_from, started_to, stuck)
    page = paginate(apply_sort(query, sort, SORTABLE, [Run.id.desc()]), params)
    related = _Related(db, page["items"])
    page["items"] = [related.to_dict(r) for r in page["items"]]
    return page


def recent_runs(db: Session, limit: int = 10) -> list[dict]:
    """最近的 N 条运行（工作台用），带关联名称；不含调试运行（反复调试会把真实运行挤出去）。"""
    runs = db.query(Run).filter(operational_only()).order_by(Run.id.desc()).limit(limit).all()
    related = _Related(db, runs)
    return [related.to_dict(r) for r in runs]


def summarize_runs(db: Session, run_type: str | None = None, agent_id: int | None = None, workflow_id: int | None = None,
                   user_id: int | None = None, model_id: int | None = None, source: str | None = None,
                   started_from: datetime | None = None, started_to: datetime | None = None) -> dict:
    """运行记录页顶部统计：各状态数量、总 token、总成本、平均 / P50 / P95 耗时、成功率、耗时分布，
    全部在数据库聚合，随列表筛选联动。成本读收尾时的快照列，不再实时折算。"""
    base = _filtered(db, run_type, None, agent_id, workflow_id, user_id, model_id, source, started_from, started_to)
    by_status = rows_to_dict(base.with_entities(Run.status, func.count(Run.id)).group_by(Run.status).all())
    tokens_row = base.with_entities(
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["prompt_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["completion_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(func.coalesce(cast(Run.token_usage["total_tokens"].astext, BigInteger), 0)), 0),
        func.coalesce(func.sum(Run.cost), 0.0),
    ).one()
    finished = base.filter(Run.finished_at.isnot(None))
    latency_row = finished.with_entities(
        func.avg(Run.latency_ms),
        func.percentile_cont(0.5).within_group(Run.latency_ms),
        func.percentile_cont(0.95).within_group(Run.latency_ms),
    ).one()
    bucket_rows = finished.with_entities(
        *[func.count(case((_bucket_condition(low, high), 1), else_=None)) for low, high, _ in LATENCY_BUCKETS]
    ).one()
    # 标注 dict[str, Any]：这个统计字典同时装 int（各状态数、token）、float（成本、成功率）和
    # None（无样本时的耗时），不标的话会被推成 dict[Literal[...], int]，后面赋值全报错。
    summary: dict[str, Any] = {s: int(by_status.get(s, 0)) for s in RUN_STATUSES}
    summary["total"] = sum(summary.values())
    summary["prompt_tokens"] = int(tokens_row[0] or 0)
    summary["completion_tokens"] = int(tokens_row[1] or 0)
    summary["total_tokens"] = int(tokens_row[2] or 0)
    summary["total_cost"] = round(float(tokens_row[3] or 0.0), 6)
    summary["avg_latency_ms"] = int(round(float(latency_row[0]))) if latency_row[0] is not None else None
    summary["p50_latency_ms"] = int(round(float(latency_row[1]))) if latency_row[1] is not None else None
    summary["p95_latency_ms"] = int(round(float(latency_row[2]))) if latency_row[2] is not None else None
    done = summary["success"] + summary["failed"]
    summary["success_rate"] = round(summary["success"] / done, 4) if done else None
    summary["latency_buckets"] = [
        {"label": label, "from_ms": low, "to_ms": high, "count": int(count or 0)}
        for (low, high, label), count in zip(LATENCY_BUCKETS, bucket_rows)
    ]
    return summary


def _bucket_condition(low: int, high: int | None):
    return (Run.latency_ms >= low) if high is None else ((Run.latency_ms >= low) & (Run.latency_ms < high))


def _node_dict(n: RunNode) -> dict:
    """节点日志：输入输出是引擎截断到 500 字符的文本快照（{"data": "..."}），耗时由起止时间算。"""
    duration = int((n.finished_at - n.started_at).total_seconds() * 1000) if n.started_at and n.finished_at else None
    return {
        "id": n.id, "node_id": n.node_id, "node_type": n.node_type, "status": n.status, "error": n.error,
        "input": (n.input or {}).get("data"), "output": (n.output or {}).get("data"),
        "started_at": _iso(n.started_at), "finished_at": _iso(n.finished_at), "duration_ms": duration,
    }


def get_run(db: Session, run_id: int) -> dict:
    """取单条运行详情：含输入、关联名称与各节点执行结果（输入输出快照、起止时间、耗时），不存在抛 BizError(404)。"""
    r = db.get(Run, run_id)
    if r is None:
        raise BizError(404, "运行记录不存在")
    related = _Related(db, [r])
    nodes = db.query(RunNode).filter(RunNode.run_id == run_id).order_by(RunNode.id).all()
    return {**related.to_dict(r), "input": r.input, "nodes": [_node_dict(n) for n in nodes]}
