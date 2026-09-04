from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.core.pagination import PageParams, paginate
from app.db.models import Tool
from app.tools.executor import execute_tool


def list_tools(db: Session, params: PageParams, q: str = None) -> dict:
    query = db.query(Tool)
    if q:
        query = query.filter(Tool.name.ilike(f"%{q}%"))
    return paginate(query.order_by(Tool.id), params, lambda t: {
        "id": t.id, "name": t.name, "description": t.description, "type": t.type,
        "config": t.config, "timeout": t.timeout, "is_enabled": t.is_enabled,
    })


def create_tool(db: Session, data) -> dict:
    t = Tool(name=data.name, description=data.description, type=data.type, config=data.config, timeout=data.timeout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "type": t.type, "description": t.description, "config": t.config, "timeout": t.timeout}


def get_tool(db: Session, tool_id: int) -> Tool:
    t = db.get(Tool, tool_id)
    if t is None:
        raise BizError(404, "工具不存在")
    return t


def update_tool(db: Session, tool_id: int, data) -> dict:
    t = get_tool(db, tool_id)
    t.name = data.name
    t.description = data.description
    t.type = data.type
    t.config = data.config
    t.timeout = data.timeout
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "type": t.type, "description": t.description, "config": t.config, "timeout": t.timeout}


def delete_tool(db: Session, tool_id: int) -> None:
    t = get_tool(db, tool_id)
    db.delete(t)
    db.commit()


async def test_tool(db: Session, tool_id: int, args: dict) -> dict:
    t = get_tool(db, tool_id)
    return await execute_tool(t, args)
