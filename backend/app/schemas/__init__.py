from datetime import datetime
from typing import Generic, Optional, TypeVar

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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "caller"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


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

    name: str
    description: str = ""
    system_prompt: str = ""
    model_id: int
    params: ModelParams = Field(default_factory=ModelParams)  # 覆盖模型的 default_params，留空的键继承
    kb_ids: list = Field(default_factory=list)
    tool_ids: list = Field(default_factory=list)
    workflow_id: Optional[int] = None
    prompt_template_id: Optional[int] = None
    prompt_variables: dict = Field(default_factory=dict)


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


class AgentDetailOut(AgentOut):
    """详情：在列表字段之上附关联对象（供详情页展示与跳转）与悬空引用清单。"""

    model: Optional[dict] = None
    tools: list = Field(default_factory=list)
    missing_tool_ids: list = Field(default_factory=list)
    knowledge_bases: list = Field(default_factory=list)
    missing_kb_ids: list = Field(default_factory=list)
    workflow: Optional[dict] = None
    prompt_template: Optional[dict] = None


class AgentBriefOut(BaseModel):
    """可对话智能体的对外资料（GET /agents/available）。caller 与 API Key 都拿得到，
    字段白名单靠这个模型保证：提示词、模型、工具、知识库、模板变量一律不出。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None
