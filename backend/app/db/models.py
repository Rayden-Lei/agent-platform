from sqlalchemy import BigInteger, Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from pgvector.sqlalchemy import Vector

from app.config import settings
from app.db.base import Base


class TimestampMixin:
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="caller")
    is_active = Column(Boolean, nullable=False, default=True)


class ModelConfig(Base, TimestampMixin):
    __tablename__ = "models"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False, index=True)
    api_base = Column(String(255), nullable=False)
    api_key_enc = Column(Text, nullable=False)
    model_name = Column(String(128), nullable=False)
    default_params = Column(JSONB, nullable=False, default=dict)
    is_enabled = Column(Boolean, nullable=False, default=True)
    price_input = Column(Float, nullable=True)
    price_output = Column(Float, nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=False)
    model_id = Column(BigInteger, ForeignKey("models.id", ondelete="RESTRICT"), nullable=False)
    params = Column(JSONB, nullable=False, default=dict)
    kb_ids = Column(JSONB, nullable=False, default=list)
    tool_ids = Column(JSONB, nullable=False, default=list)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=True)
    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    # Prompt 模板绑定（FR-028）：保存时用模板 + 变量渲染进 system_prompt 并记下模板版本；运行时仍只读 system_prompt
    prompt_template_id = Column(BigInteger, ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)
    prompt_template_version = Column(Integer, nullable=True)
    prompt_variables = Column(JSONB, nullable=False, default=dict)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False, default=dict)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class PromptTemplate(Base, TimestampMixin):
    """Prompt 模板（FR-028）：内容里用 {{name}} 引用 variables 声明的变量；content / variables 变化时 version + 1 并写快照。"""

    __tablename__ = "prompt_templates"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    variables = Column(JSONB, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class PromptTemplateVersion(Base):
    """模板版本快照：与智能体的 agent_versions 同一套语义，回滚也产生新版本，历史不可篡改。"""

    __tablename__ = "prompt_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_template_versions_template_version"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_id = Column(BigInteger, ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    variables = Column(JSONB, nullable=False, default=list)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class Tool(Base):
    __tablename__ = "tools"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False)
    type = Column(String(16), nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    timeout = Column(Integer, nullable=False, default=30)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    embedding_model = Column(String(128), nullable=False)
    chunk_size = Column(Integer, nullable=False, default=500)
    chunk_overlap = Column(Integer, nullable=False, default=50)
    # 权限：is_public=True 所有角色可见；False 仅 visible_roles 内角色可见
    is_public = Column(Boolean, nullable=False, default=True, index=True)
    visible_roles = Column(JSONB, nullable=False, default=list)
    policy_version = Column(Integer, nullable=False, default=1)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="uploading", index=True)
    chunk_count = Column(Integer, nullable=False, default=0)  # 已入库切片数，处理中逐批递增
    chunk_total = Column(Integer, nullable=True)  # 分片后确定的计划切片总数；处理中据此算进度
    error = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at = Column(TIMESTAMP(timezone=True), nullable=True)  # 开始向量化入库的时间，据此算速度与剩余
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)  # ready / failed 的时间


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.EMBEDDING_DIM), nullable=False)
    meta = Column(JSONB, nullable=False, default=dict)
    token_count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    graph = Column(JSONB, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="draft")
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(64), nullable=False)
    node_type = Column(String(16), nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    pos_x = Column(Float, nullable=False, default=0)
    pos_y = Column(Float, nullable=False, default=0)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    # 对话摘要持久化（FR-031）：summary 覆盖 id ≤ summary_upto_message_id 的更早消息，按批增量折叠，不再每轮重算
    summary = Column(Text, nullable=True)
    summary_upto_message_id = Column(BigInteger, nullable=True)
    summary_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSONB, nullable=False, default=list)
    citations = Column(JSONB, nullable=False, default=list)
    token_usage = Column(JSONB, nullable=False, default=dict)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)


class Run(Base):
    __tablename__ = "runs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_type = Column(String(16), nullable=False, index=True)
    agent_id = Column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="running", index=True)
    input = Column(JSONB, nullable=False, default=dict)
    output = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    token_usage = Column(JSONB, nullable=False, default=dict)
    latency_ms = Column(Integer, nullable=False, default=0)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True, index=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    # 运营统计快照（页面深度优化）：model_id 记发起时智能体绑定的模型（智能体换模型后旧运行仍归旧模型）；
    # cost 在收尾时按当时单价折算落库，改单价不追溯，趋势图不会被重写；conversation_id 让运行记录能跳回会话
    model_id = Column(BigInteger, ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    cost = Column(Float, nullable=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    cron = Column(String(64), nullable=False)
    input = Column(JSONB, nullable=False, default=dict)
    is_enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False, index=True)  # 鉴权按哈希查找
    is_enabled = Column(Boolean, nullable=False, default=True)
    quota = Column(Integer, nullable=False, default=1000)
    used = Column(Integer, nullable=False, default=0)
    # 入口治理（FR-025 / FR-026）：来源 IP 白名单（IP 或 CIDR 列表，空 = 不限制）；每分钟限速（0 = 用全局默认）
    allowed_ips = Column(JSONB, nullable=False, default=list)
    rate_limit_per_minute = Column(Integer, nullable=False, default=0)
    last_used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)
    resource = Column(String(64), nullable=False)
    resource_id = Column(BigInteger, nullable=True)
    detail = Column(JSONB, nullable=False, default=dict)
    ip = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)


class RunNode(Base):
    __tablename__ = "run_nodes"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(64), nullable=False)
    node_type = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    input = Column(JSONB, nullable=False, default=dict)
    output = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
