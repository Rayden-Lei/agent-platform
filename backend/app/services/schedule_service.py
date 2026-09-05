from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.core.scheduler import add_schedule_job, is_valid_cron, next_run_times, remove_schedule_job, trigger_now
from app.db.models import Run, ScheduledJob, User, Workflow

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
    """每个定时任务最近一次运行的 id 与状态：运行记录的 input.schedule_id 指回任务，取每个任务 id 最大的一条。"""
    if not schedule_ids:
        return {}
    rows = (
        db.query(Run.id, Run.status, Run.input["schedule_id"].astext)
        .filter(Run.input["schedule_id"].astext.in_([str(i) for i in schedule_ids]))
        .order_by(Run.id.desc())
        .limit(len(schedule_ids) * 5)
        .all()
    )
    result: dict[int, dict] = {}
    for run_id, status, schedule_id in rows:
        sid = int(schedule_id)
        if sid not in result:
            result[sid] = {"id": run_id, "status": status}
    return result


def _serialize_page(db: Session, rows: list) -> list[dict]:
    """一页任务的关联装配：工作流名、创建人、下次触发时间、最近一次运行，各一次查询。"""
    workflow_ids = {s.workflow_id for s in rows}
    user_ids = {s.user_id for s in rows if s.user_id}
    workflows = dict(db.query(Workflow.id, Workflow.name).filter(Workflow.id.in_(workflow_ids)).all()) if workflow_ids else {}
    users = dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()) if user_ids else {}
    next_runs = next_run_times([s.id for s in rows]) if rows else {}
    last_runs = _last_runs(db, {s.id for s in rows})
    return [_to_dict(s, workflows.get(s.workflow_id), users.get(s.user_id), next_runs.get(s.id), last_runs.get(s.id)) for s in rows]


def list_schedules(db: Session, params: PageParams, q: str = None, workflow_id: int = None, is_enabled: bool = None, sort: SortParams = None) -> dict:
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
    if db.get(Workflow, workflow_id) is None:
        raise BizError(404, "工作流不存在")


def create_schedule(db: Session, data, user: User) -> dict:
    """新建定时任务：工作流必须存在（404）；落库后立即注册到调度器。cron 合法性在 schema 层已校验（422）。"""
    _check_workflow(db, data.workflow_id)
    sj = ScheduledJob(name=data.name, workflow_id=data.workflow_id, user_id=user.id, cron=data.cron, input=data.input)
    db.add(sj)
    db.commit()
    db.refresh(sj)
    add_schedule_job(sj)
    return _serialize_page(db, [sj])[0]


def get_schedule(db: Session, schedule_id: int) -> ScheduledJob:
    s = db.get(ScheduledJob, schedule_id)
    if s is None:
        raise BizError(404, "定时任务不存在")
    return s


def get_schedule_detail(db: Session, schedule_id: int) -> dict:
    return _serialize_page(db, [get_schedule(db, schedule_id)])[0]


def update_schedule(db: Session, schedule_id: int, data) -> dict:
    """整体覆盖名称 / 工作流 / cron / 输入；启用中的任务按新配置重新注册。"""
    s = get_schedule(db, schedule_id)
    _check_workflow(db, data.workflow_id)
    s.name, s.workflow_id, s.cron, s.input = data.name, data.workflow_id, data.cron, data.input
    db.commit()
    db.refresh(s)
    remove_schedule_job(s.id)
    if s.is_enabled:
        add_schedule_job(s)
    return _serialize_page(db, [s])[0]


def set_schedule_enabled(db: Session, schedule_id: int, enabled: bool) -> dict:
    """设置启用状态并同步调度器注册 / 注销，保证库中状态与调度器一致；幂等。"""
    s = get_schedule(db, schedule_id)
    s.is_enabled = enabled
    db.commit()
    if s.is_enabled:
        add_schedule_job(s)
    else:
        remove_schedule_job(s.id)
    return {"id": s.id, "is_enabled": s.is_enabled}


def toggle_schedule(db: Session, schedule_id: int) -> dict:
    """启用/停用定时任务（开关切换）。"""
    s = get_schedule(db, schedule_id)
    return set_schedule_enabled(db, schedule_id, not s.is_enabled)


def run_now(db: Session, schedule_id: int) -> dict:
    """立即触发一次（在调度器线程里跑，与定时触发走同一条路径）；停用的任务也允许手动跑一次，便于验证配置。"""
    s = get_schedule(db, schedule_id)
    if not is_valid_cron(s.cron):
        raise BizError(400, "cron 表达式非法，请先修正")
    trigger_now(s.id, force=True)
    return {"id": s.id, "triggered_at": datetime.now(timezone.utc).isoformat()}


def delete_schedule(db: Session, schedule_id: int) -> None:
    """删除定时任务：先从调度器移除，再删库记录。"""
    s = get_schedule(db, schedule_id)
    remove_schedule_job(s.id)
    db.delete(s)
    db.commit()


def apply_batch_action(db: Session, schedule_id: int, action: str) -> None:
    """批量操作的单条执行（enable / disable / delete）。"""
    if action == "delete":
        delete_schedule(db, schedule_id)
    else:
        set_schedule_enabled(db, schedule_id, action == "enable")
