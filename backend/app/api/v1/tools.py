from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import tool_service

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
    return tool_service.list_tools(db)


@router.post("")
def create_tool(data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return tool_service.create_tool(db, data)


@router.put("/{tool_id}")
def update_tool(tool_id: int, data: ToolIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    return tool_service.update_tool(db, tool_id, data)


@router.delete("/{tool_id}")
def delete_tool(tool_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    tool_service.delete_tool(db, tool_id)
    return {"code": 0, "message": "ok"}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: int, data: ToolTestIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    result = await tool_service.test_tool(db, tool_id, data.args)
    return {"code": 0, "message": "ok", "data": {"result": result}}
