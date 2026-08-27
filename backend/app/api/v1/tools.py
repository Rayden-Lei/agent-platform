from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import Tool, User
from app.db.session import get_db
from app.tools.executor import execute_tool

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolIn(BaseModel):
    name: str
    description: str
    type: str = "builtin"
    config: dict = {}
    timeout: int = 30


class ToolTestIn(BaseModel):
    args: dict = {}


@router.get("")
def list_tools(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    rows = db.query(Tool).order_by(Tool.id).all()
    return [{"id": t.id, "name": t.name, "description": t.description, "type": t.type, "config": t.config, "timeout": t.timeout, "is_enabled": t.is_enabled} for t in rows]


@router.post("")
def create_tool(data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    t = Tool(name=data.name, description=data.description, type=data.type, config=data.config, timeout=data.timeout)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "type": t.type, "description": t.description, "config": t.config, "timeout": t.timeout}


@router.put("/{tool_id}")
def update_tool(tool_id: int, data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    t = db.get(Tool, tool_id)
    if t is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    t.name = data.name
    t.description = data.description
    t.type = data.type
    t.config = data.config
    t.timeout = data.timeout
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "type": t.type, "description": t.description, "config": t.config, "timeout": t.timeout}


@router.delete("/{tool_id}")
def delete_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    t = db.get(Tool, tool_id)
    if t is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    db.delete(t)
    db.commit()
    return {"code": 0, "message": "ok"}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: int, data: ToolTestIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    t = db.get(Tool, tool_id)
    if t is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    result = await execute_tool(t, data.args)
    return {"code": 0, "message": "ok", "data": {"result": result}}
