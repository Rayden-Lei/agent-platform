from sqlalchemy import BigInteger, Boolean, Column, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from pgvector.sqlalchemy import Vector

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
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=False)
    model_id = Column(BigInteger, ForeignKey("models.id"), nullable=False)
    params = Column(JSONB, nullable=False, default=dict)
    kb_ids = Column(JSONB, nullable=False, default=list)
    tool_ids = Column(JSONB, nullable=False, default=list)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id"), nullable=True)
    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(BigInteger, ForeignKey("agents.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False, default=dict)
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
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="uploading", index=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(BigInteger, ForeignKey("documents.id"), nullable=False, index=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(2048), nullable=False)
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
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id"), nullable=False, index=True)
    node_id = Column(String(64), nullable=False)
    node_type = Column(String(16), nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    pos_x = Column(Float, nullable=False, default=0)
    pos_y = Column(Float, nullable=False, default=0)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(BigInteger, ForeignKey("agents.id"), nullable=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id"), nullable=False, index=True)
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
    agent_id = Column(BigInteger, ForeignKey("agents.id"), nullable=True)
    workflow_id = Column(BigInteger, ForeignKey("workflows.id"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="running", index=True)
    input = Column(JSONB, nullable=False, default=dict)
    output = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    token_usage = Column(JSONB, nullable=False, default=dict)
    latency_ms = Column(Integer, nullable=False, default=0)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)


class RunNode(Base):
    __tablename__ = "run_nodes"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("runs.id"), nullable=False, index=True)
    node_id = Column(String(64), nullable=False)
    node_type = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    input = Column(JSONB, nullable=False, default=dict)
    output = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
