"""批量操作的统一执行器（页面深度优化）：逐条独立执行、逐条独立返回结果。

语义：不是全成功或全失败，而是每条独立提交；业务失败（BizError）进 failed 清单并继续，
非预期异常记日志后以通用文案进 failed 清单。每条失败后 rollback，否则 IntegrityError 之后 session 不可用。
"""
import logging
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

BATCH_MAX_IDS = 100

# action 的类型由每个子类自己给（都是 Literal 字面量集合）。
ActionT = TypeVar("ActionT", bound=str)


class BatchIn(BaseModel, Generic[ActionT]):
    """批量请求体：ids 1～100 个且去重；action 由各路由用 Literal 收窄（非法值 422）。

    action 做成类型参数、而不是在基类留一个 str：
    子类需要把它收窄成各自允许的动作集合（Literal["enable", "disable", "delete"]）。
    如果基类直接写 action: str，子类收窄就成了不兼容的属性覆写——凡是按基类类型使用的地方
    都可能塞进任意字符串，收窄并不成立，检查器报 reportIncompatibleVariableOverride 是对的。
    改成泛型参数后，每个子类的 action 就是它自己那组字面量，约束在类型层面真实成立。
    """

    ids: list[int] = Field(min_length=1, max_length=BATCH_MAX_IDS)
    action: ActionT

    def unique_ids(self) -> list[int]:
        seen: set[int] = set()
        return [i for i in self.ids if not (i in seen or seen.add(i))]


def run_batch(db: Session, ids: list[int], fn: Callable[[int], None]) -> dict:
    """对每个 id 调 fn(id)；返回 {"succeeded": [...], "failed": [{"id", "detail"}]}。"""
    succeeded: list[int] = []
    failed: list[dict] = []
    for item_id in ids:
        try:
            fn(item_id)
            succeeded.append(item_id)
        except BizError as e:
            db.rollback()
            failed.append({"id": item_id, "detail": e.detail})
        except Exception:
            db.rollback()
            logger.exception("批量操作单条失败 id=%s", item_id)
            failed.append({"id": item_id, "detail": "服务器内部错误"})
    return {"succeeded": succeeded, "failed": failed}
