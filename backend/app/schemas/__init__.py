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


class ModelIn(BaseModel):
    name: str
    provider: str
    api_base: str
    api_key: str = ""  # 更新时留空表示沿用已有密钥；创建时非空（由 service 校验）
    model_name: str
    default_params: dict = Field(default_factory=dict)
    price_input: Optional[float] = None
    price_output: Optional[float] = None

    @field_validator("default_params")
    @classmethod
    def _check_default_params(cls, value: dict) -> dict:
        """thinking 只接受 disabled / enabled（或不设）；其余键由网关按需取用。"""
        thinking = value.get("thinking")
        if thinking is not None and thinking not in ("disabled", "enabled"):
            raise ValueError("default_params.thinking 只能是 disabled 或 enabled")
        return value


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
    params: dict = Field(default_factory=dict)
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
