from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

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
