from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, SortParams, apply_sort, paginate
from app.db.models import Agent, Tool
from app.tools.executor import execute_tool
from app.tools.schema import check_tool_args

SORTABLE = {"id": Tool.id, "name": Tool.name, "type": Tool.type, "timeout": Tool.timeout}


def _to_dict(t: Tool, agents_count: int = 0) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description, "type": t.type,
        "config": t.config, "timeout": t.timeout, "is_enabled": t.is_enabled, "agents_count": agents_count,
    }


def _agents_count_by_tool(db: Session, tool_ids: set[int]) -> dict[int, int]:
    """引用各工具的智能体数。tool_ids 是 JSONB 数组没有外键，一次拉回全部智能体的 (id, tool_ids) 在内存里数；
    智能体表小，避免对每个工具发一条 contains 查询。"""
    if not tool_ids:
        return {}
    counts = {tid: 0 for tid in tool_ids}
    for (ids,) in db.query(Agent.tool_ids).all():
        for tid in ids or []:
            if tid in counts:
                counts[tid] += 1
    return counts


def list_tools(db: Session, params: PageParams, q: str = None, tool_type: str = None, is_enabled: bool = None, sort: SortParams = None) -> dict:
    """分页列出工具：q 名称模糊，可按类型、启用状态过滤，白名单排序；附引用它的智能体数。"""
    query = db.query(Tool)
    if q:
        query = query.filter(Tool.name.ilike(f"%{q}%"))
    if tool_type:
        query = query.filter(Tool.type == tool_type)
    if is_enabled is not None:
        query = query.filter(Tool.is_enabled.is_(is_enabled))
    page = paginate(apply_sort(query, sort, SORTABLE, [Tool.id.asc()]), params)
    counts = _agents_count_by_tool(db, {t.id for t in page["items"]})
    page["items"] = [_to_dict(t, counts.get(t.id, 0)) for t in page["items"]]
    return page


def create_tool(db: Session, data) -> dict:
    """新建工具（type 决定执行方式，config 为各类型工具的参数配置）。"""
    t = Tool(name=data.name, description=data.description, type=data.type, config=data.config, timeout=data.timeout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_dict(t)


def get_tool(db: Session, tool_id: int) -> Tool:
    """按 ID 取工具，不存在抛 BizError(404)。"""
    t = db.get(Tool, tool_id)
    if t is None:
        raise BizError(404, "工具不存在")
    return t


def get_tool_detail(db: Session, tool_id: int) -> dict:
    """工具详情：附引用它的智能体清单（id / name / status）。"""
    t = get_tool(db, tool_id)
    agents = [{"id": a.id, "name": a.name, "status": a.status} for a in db.query(Agent).filter(Agent.tool_ids.contains([tool_id])).order_by(Agent.id).all()]
    return {**_to_dict(t, len(agents)), "agents": agents}


def update_tool(db: Session, tool_id: int, data) -> dict:
    """覆盖式更新工具配置。"""
    t = get_tool(db, tool_id)
    t.name = data.name
    t.description = data.description
    t.type = data.type
    t.config = data.config
    t.timeout = data.timeout
    db.commit()
    db.refresh(t)
    return _to_dict(t)


def set_tool_enabled(db: Session, tool_id: int, enabled: bool) -> dict:
    """启用 / 停用工具（幂等）。停用的工具仍保留在智能体的 tool_ids 里，只是不再暴露给模型（见 langchain_tools.build_tools）。"""
    t = get_tool(db, tool_id)
    t.is_enabled = enabled
    db.commit()
    return {"id": t.id, "is_enabled": t.is_enabled}


def delete_tool(db: Session, tool_id: int) -> None:
    """删除工具。

    tools 与智能体的关联是 agents.tool_ids（JSONB 列表）而非外键，删除后不会级联清理，
    这里主动把该 tool_id 从所有智能体的 tool_ids 里移除，避免留下悬空引用
    （否则对话/工作流运行时会按已不存在的工具做无谓查询或报"工具不存在"）。
    """
    t = get_tool(db, tool_id)
    agents = db.query(Agent).filter(Agent.tool_ids.contains([tool_id])).all()
    for a in agents:
        if tool_id in a.tool_ids:
            a.tool_ids = [x for x in a.tool_ids if x != tool_id]
    db.delete(t)
    db.commit()


def apply_batch_action(db: Session, tool_id: int, action: str) -> None:
    """批量操作的单条执行（enable / disable / delete）。"""
    if action == "delete":
        delete_tool(db, tool_id)
    else:
        set_tool_enabled(db, tool_id, action == "enable")


async def test_tool(db: Session, tool_id: int, args: dict) -> dict:
    """用给定参数实际执行一次工具，供前端测试配置是否可用。HTTP 工具先按参数声明校验，不合法 400 且不发起调用。"""
    t = get_tool(db, tool_id)
    try:
        args = check_tool_args(t, args)
    except ValueError as e:
        raise BizError(400, str(e)) from e
    return await execute_tool(t, args)
