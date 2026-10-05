from datetime import datetime
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """分页响应信封，与 core.pagination.paginate 的返回结构一致。"""

    items: list[T]
    total: int
    page: int
    page_size: int


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool = False  # 为真时除 /auth/me 与改密外全部 403，前端据此弹改密框（docs/15 OP-04）
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MeOut(UserOut):
    """GET /auth/me：当前用户 + 对外地址 public_base_url（docs/15 PB-07：分享链接、API 调用示例用；空串表示前端用当前访问的地址）。"""
    public_base_url: str = ""


class TokenOut(BaseModel):
    token: str
    user: UserOut


UserRole = Literal["admin", "developer", "caller"]
PASSWORD_MIN, PASSWORD_MAX = 6, 128


class UserCreate(BaseModel):
    """新建用户（2026-10-05 起校验，422；此前空密码、role=superadmin 都能落库，超长用户名走 500）。
    用户名去掉首尾空白后 2～64 个字符且不含空白；密码 6～128。"""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    role: UserRole = "caller"

    @field_validator("username", mode="before")
    @classmethod
    def _clean_username(cls, value):
        value = value.strip() if isinstance(value, str) else value
        if isinstance(value, str) and any(ch.isspace() for ch in value):
            raise ValueError("用户名不能包含空白字符")
        return value


class UserUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class ChangePasswordIn(BaseModel):
    """本人改密：旧密码错 400、新旧相同 400、新密码不满足长度 422。"""

    old_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class ModelParams(BaseModel):
    """模型调用参数，模型的 default_params 与智能体的 params 共用这一个结构（FR-042）。

    只认这四个键，未知键 422 —— 2026-09-25 前两处都是裸 dict，智能体参数还从没生效过，写错键名也不会有任何提示。
    值为空表示不设置、继承上一层：运行时按"模型 default_params ← 智能体 params"合并（gateway.build_llm）。
    """

    model_config = ConfigDict(extra="forbid")
    temperature: Optional[float] = Field(None, ge=0, le=2)
    top_p: Optional[float] = Field(None, ge=0, le=1)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    thinking: Optional[str] = None  # disabled / enabled，以 extra_body 透传给 DeepSeek 类混合推理模型

    @field_validator("thinking")
    @classmethod
    def _check_thinking(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ("disabled", "enabled"):
            raise ValueError("thinking 只能是 disabled 或 enabled")
        return value

    def to_dict(self) -> dict:
        """落库用：只存设置了的键，库里看得出哪些是显式配置、哪些在继承。"""
        return self.model_dump(exclude_none=True)


class ModelIn(BaseModel):
    name: str
    provider: str
    api_base: str
    api_key: str = ""  # 更新时留空表示沿用已有密钥；创建时非空（由 service 校验）
    model_name: str
    default_params: ModelParams = Field(default_factory=ModelParams)
    price_input: Optional[float] = Field(None, ge=0)
    price_output: Optional[float] = Field(None, ge=0)


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    provider: str
    api_base: str
    model_name: str
    default_params: dict
    is_enabled: bool
    price_input: Optional[float] = None
    price_output: Optional[float] = None
    # 列表附带的关联信息（页面深度优化）：引用该模型的智能体数、创建人、时间
    agents_count: int = 0
    created_by: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentIn(BaseModel):
    """创建 / 更新智能体。system_prompt 与 prompt_template_id 二选一（FR-028）：
    绑定模板时 system_prompt 必须省略或为空，服务端用模板 + prompt_variables 渲染写入。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    system_prompt: str = Field("", max_length=20000)
    model_id: int
    params: ModelParams = Field(default_factory=ModelParams)  # 覆盖模型的 default_params，留空的键继承
    # 每个知识库对话时都要并行检索一次，不能无界；ID 必须是整数，重复的去掉
    kb_ids: list[int] = Field(default_factory=list, max_length=20)
    tool_ids: list[int] = Field(default_factory=list, max_length=20)
    workflow_id: Optional[int] = None
    prompt_template_id: Optional[int] = None
    prompt_variables: dict = Field(default_factory=dict)

    @field_validator("kb_ids", "tool_ids")
    @classmethod
    def _dedupe_ids(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class AgentUpdateIn(AgentIn):
    """更新草稿：整体覆盖。expected_updated_at 是读到的 updated_at（乐观锁），与库中不一致 409，防止两个人同时改互相覆盖（docs/15 D-11）。"""

    expected_updated_at: datetime

    @field_validator("expected_updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("expected_updated_at 必须带时区，原样回传读取时拿到的 updated_at")
        return value


class PublishIn(BaseModel):
    note: Optional[str] = Field(None, max_length=200)  # 发布说明，进版本历史与审计


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    system_prompt: str
    model_id: int
    params: dict
    kb_ids: list
    tool_ids: list
    workflow_id: Optional[int]
    status: str
    version: int
    prompt_template_id: Optional[int] = None
    prompt_template_version: Optional[int] = None
    prompt_variables: dict = Field(default_factory=dict)
    # 模板当前版本高于绑定时版本；模板改版不自动传播，由开发者重新保存
    prompt_template_outdated: bool = False
    # 列表附带的关联信息（页面深度优化）：模型名、模板名、创建人、时间、最近 7 天运行数与最近运行时间
    model_name: Optional[str] = None
    prompt_template_name: Optional[str] = None
    created_by: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    runs_7d: int = 0
    last_run_at: Optional[str] = None
    # 发布语义（FR-039）：本对象的配置字段是草稿；线上版本号与发布时间；草稿与线上快照是否不同（计算值，不入库）
    published_version: Optional[int] = None
    published_at: Optional[str] = None
    has_unpublished_changes: bool = False


class AgentPublishOut(AgentOut):
    """发布 / 回滚上线的结果：published 生成了新线上版本或重新上线；unchanged 与线上一致，什么都没做（幂等）。"""

    publish_result: str


class AgentDetailOut(AgentOut):
    """详情：在列表字段之上附关联对象（供详情页展示与跳转）与悬空引用清单。"""

    model: Optional[dict] = None
    tools: list = Field(default_factory=list)
    missing_tool_ids: list = Field(default_factory=list)
    knowledge_bases: list = Field(default_factory=list)
    missing_kb_ids: list = Field(default_factory=list)
    workflow: Optional[dict] = None
    prompt_template: Optional[dict] = None
    # 草稿与线上两份同形快照（字段由 runtime.agent_config.snapshot_of 定义）；从未发布时 live_snapshot 为空
    draft_snapshot: dict = Field(default_factory=dict)
    live_snapshot: Optional[dict] = None


class AgentBriefOut(BaseModel):
    """可对话智能体的对外资料（GET /agents/available）。caller 与 API Key 都拿得到，
    字段白名单靠这个模型保证：提示词、模型、工具、知识库、模板变量一律不出。
    名称与描述取线上快照；时间是发布时间 —— 不能用 updated_at，那是草稿的编辑时间（2026-09-25 一次切换）。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    published_at: Optional[datetime] = None
