"""系统管理路由：运行状态查询、运行时可调参数。本模块仅允许 admin / developer 角色访问，改参数仅 admin。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictFloat, StrictInt
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import User
from app.db.session import get_db
from app.services import settings_service, system_service

router = APIRouter(prefix="/system", tags=["system"])


class SystemSettingsIn(BaseModel):
    """`{values: {key: 数字 | null}}`，null 表示删掉覆盖值、回到 .env 默认。

    用严格数字类型：不接受 `"4"` 这类字符串，也不接受 true/false —— 参数被写成字符串却静默生效，
    比直接报错更难查（值会走 _coerce 被夹成默认值，表现是"我明明改了却没变"）。整数 / 小数由各参数的 kind 再校验。
    """

    values: dict[str, StrictInt | StrictFloat | None]


@router.get("/status")
def system_status(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """运行状态与降级项。含依赖可用性，属运维信息，不对 caller 与 API Key 开放。"""
    return system_service.get_system_status(db)


@router.get("/settings")
def list_system_settings(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "developer"))):
    """运行时可调参数清单：每项带规格（范围、默认值）、当前值与来源（default = .env，db = 页面改过）。"""
    return settings_service.list_settings(db)


@router.put("/settings")
def update_system_settings(data: SystemSettingsIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """批量修改参数（幂等：同样的值重复提交结果一致）。越界或未知键整批 400；成功返回修改后的完整清单。对下一篇开始处理的文档生效。"""
    return settings_service.update_settings(db, user, data.values)
