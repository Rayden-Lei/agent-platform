from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
    api_key: str
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
    name: str
    description: str = ""
    system_prompt: str
    model_id: int
    params: dict = Field(default_factory=dict)
    kb_ids: list = Field(default_factory=list)
    tool_ids: list = Field(default_factory=list)
    workflow_id: Optional[int] = None


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
