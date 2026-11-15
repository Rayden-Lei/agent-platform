from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.scheduler import add_schedule_job, is_valid_cron, next_run_times, remove_schedule_job, trigger_now
from app.db.session import rows_to_dict
from app.db.models import Run, ScheduledJob, User, Workflow
from app.runtime.workflow_config import resolve_live_config

SORTABLE = {"id": ScheduledJob.id, "name": ScheduledJob.name, "last_run_at": ScheduledJob.last_run_at, "created_at": ScheduledJob.created_at}


def _to_dict(s: ScheduledJob, workflow_name: str | None = None, username: str | None = None,
             next_run_at: datetime | None = None, last_run: dict | None = None) -> dict:
    return {
        "id": s.id, "name": s.name, "workflow_id": s.workflow_id, "workflow_name": workflow_name, "cron": s.cron,
        "cron_valid": is_valid_cron(s.cron), "input": s.input or {}, "is_enabled": s.is_enabled,
        "user_id": s.user_id, "username": username,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_run_id": last_run.get("id") if last_run else None,
        "last_run_status": last_run.get("status") if last_run else None,
        "next_run_at": next_run_at.isoformat() if next_run_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _last_runs(db: Session, schedule_ids: set[int]) -> dict[int, dict]:
    """每个定时任务最近一次运行的 id 与状态：按 runs.schedule_id 分组取最大 id，再一次取状态，共两次查询。

    2026-09-25 前从 input.schedule_id 里取、且只看最近 N×5 条，某个任务跑得勤就会把其他任务挤出结果。
    """
    if not schedule_ids:
        return {}
    latest = rows_to_dict(db.query(Run.schedule_id, func.max(Run.id)).filter(Run.schedule_id.in_(schedule_ids)).group_by(Run.schedule_id).all())
    statuses = rows_to_dict(db.query(Run.id, Run.status).filter(Run.id.in_(latest.values())).all()) if latest else {}
    return {sid: {"id": run_id, "status": statuses.get(run_id)} for sid, run_id in latest.items()}


def _serialize_page(db: Session, rows: list) -> list[dict]:
    """一页任务的关联装配：工作流名、创建人、下次触发时间、最近一次运行，各一次查询。"""
    workflow_ids = {s.workflow_id for s in rows}
    user_ids = {s.user_id for s in rows if s.user_id}
    workflows = rows_to_dict(db.query(Workflow.id, Workflow.name).filter(Workflow.id.in_(workflow_ids)).all()) if workflow_ids else {}
    users = rows_to_dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}
    next_runs = next_run_times([s.id for s in rows]) if rows else {}
    last_runs = _last_runs(db, {s.id for s in rows})
    return [_to_dict(s, workflows.get(s.workflow_id), users.get(s.user_id), next_runs.get(s.id), last_runs.get(s.id)) for s in rows]


def list_schedules(db: Session, params: PageParams, q: str | None = None, workflow_id: int | None = None, is_enabled: bool | None = None, sort: SortParams | None = None) -> dict:
    """分页列出定时任务：名称模糊、按工作流、启用状态过滤，白名单排序，默认 ID 倒序。"""
    query = db.query(ScheduledJob)
    if q:
        query = query.filter(ScheduledJob.name.ilike(f"%{q}%"))
    if workflow_id:
        query = query.filter(ScheduledJob.workflow_id == workflow_id)
    if is_enabled is not None:
        query = query.filter(ScheduledJob.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [ScheduledJob.id.desc()]), params)
    page["items"] = _serialize_page(db, page["items"])
    return page


def _check_workflow(db: Session, workflow_id: int) -> None:
    """定时任务只能绑已发布的工作流（FR-075）。

    为什么在保存时拦而不是等到点再失败：任务建出来之后是无人值守的，到点才发现"工作流没发布"
    意味着这段时间的调度全部空跑，而用户以为自己配好了。报错口径与运行时一致（403 工作流未发布）。
    改草稿不影响已建的任务 —— 任务跑的是线上版本。
    """
    if db.get(Workflow, workflow_id) is None:
        raise BizError(404, "工作流不存在")
    resolve_live_config(db, workflow_id)


def create_schedule(db: Session, data, user: User) -> dict:
    """新建定时任务：工作流必须存在（404）且已发布（403）；落库后立即注册到调度器。cron 合法性在 schema 层已校验（422）。

    写审计：定时任务会按 cron 反复触发工作流、消耗模型额度，属于"能造成资金损失"的操作，
    必须留痕（2026-11-15 补，此前 schedule_service 全模块 0 处审计）。
    """
    _check_workflow(db, data.workflow_id)
    sj = ScheduledJob(name=data.name, workflow_id=data.workflow_id, user_id=user.id, cron=data.cron, input=data.input)
    db.add(sj)
    db.commit()
    db.refresh(sj)
    add_schedule_job(sj)
    result = _serialize_page(db, [sj])[0]
    record_audit(db, user, "create", "schedule", sj.id,
                 detail={"name": sj.name, "workflow_id": sj.workflow_id, "cron": sj.cron})
    return result


def get_schedule(db: Session, schedule_id: int) -> ScheduledJob:
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise BizError(404, "定时任务不存在")
    return s


def get_schedule_detail(db: Session, schedule_id: int) -> dict:
    return _serialize_page(db, [get_schedule(db, schedule_id)])[0]


def update_schedule(db: Session, schedule_id: int, data, user: User) -> dict:
    """整体覆盖名称 / 工作流 / cron / 输入；启用中的任务按新配置重新注册。

    写审计并记录改前改后：把 cron 从「每天一次」改成「每分钟一次」不会报错，
    但账单会立刻变化；只有审计里能看出是谁在什么时候改的。
    """
    s = get_schedule(db, schedule_id)
    _check_workflow(db, data.workflow_id)
    before = {"name": s.name, "workflow_id": s.workflow_id, "cron": s.cron}
    s.name, s.workflow_id, s.cron, s.input = data.name, data.workflow_id, data.cron, data.input
    db.commit()
    db.refresh(s)
    remove_schedule_job(s.id)
    if s.is_enabled:
        add_schedule_job(s)
    result = _serialize_page(db, [s])[0]
    after = {"name": s.name, "workflow_id": s.workflow_id, "cron": s.cron}
    if before != after:
        record_audit(db, user, "update", "schedule", s.id, detail={"before": before, "after": after})
    return result


def set_schedule_enabled(db: Session, schedule_id: int, enabled: bool, user: User | None = None) -> dict:
    """设置启用状态并同步调度器注册 / 注销，保证库中状态与调度器一致；幂等。

    user 为空表示调度器内部调用（无操作者），此时不写审计；接口调用一定传。
    状态没变化时不写审计，避免开关点两次留两条一样的记录。
    """
    s = get_schedule(db, schedule_id)
    changed = s.is_enabled != enabled
    s.is_enabled = enabled
    db.commit()
    if s.is_enabled:
        add_schedule_job(s)
    else:
        remove_schedule_job(s.id)
    if user is not None and changed:
        record_audit(db, user, "enable" if enabled else "disable", "schedule", s.id, detail={"name": s.name})
    return {"id": s.id, "is_enabled": s.is_enabled}


def toggle_schedule(db: Session, schedule_id: int, user: User) -> dict:
    """启用/停用定时任务（开关切换）。"""
    s = get_schedule(db, schedule_id)
    return set_schedule_enabled(db, schedule_id, not s.is_enabled, user)


def run_now(db: Session, schedule_id: int) -> dict:
    """立即触发一次（在调度器线程里跑，与定时触发走同一条路径）；停用的任务也允许手动跑一次，便于验证配置。"""
    s = get_schedule(db, schedule_id)
    if not is_valid_cron(s.cron):
        raise BizError(400, "cron 表达式非法，请先修正")
    trigger_now(s.id, force=True)
    return {"id": s.id, "triggered_at": datetime.now(timezone.utc).isoformat()}


def delete_schedule(db: Session, schedule_id: int, user: User | None = None) -> None:
    """删除定时任务：先从调度器移除，再删库记录。写审计（user 为空时跳过，见 set_schedule_enabled）。"""
    s = get_schedule(db, schedule_id)
    name = s.name
    remove_schedule_job(s.id)
    db.delete(s)
    db.commit()
    if user is not None:
        record_audit(db, user, "delete", "schedule", schedule_id, detail={"name": name})


def apply_batch_action(db: Session, schedule_id: int, action: str, user: User | None = None) -> None:
    """批量操作的单条执行（enable / disable / delete）。"""
    if action == "delete":
        delete_schedule(db, schedule_id, user)
    else:
        set_schedule_enabled(db, schedule_id, action == "enable", user)
