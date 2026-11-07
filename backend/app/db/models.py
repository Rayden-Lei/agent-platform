from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.config import settings
from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="caller")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 令牌版本（M0，docs/15 OP-04）：JWT 里带 ver，重置密码 / 停用 / 改密 / 退出其他设备时 +1，旧令牌即失效
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 为真时除 /auth/me 与改密外全部 403「请先修改初始密码」（服务端强制）
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    display_name: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    password_changed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class ModelConfig(Base, TimestampMixin):
    __tablename__ = "models"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    api_base: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    default_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_output: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("models.id", ondelete="RESTRICT"), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    kb_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 技能绑定（docs/17 §4.3）：与 kb_ids / tool_ids 同风格，JSONB 数组无外键，技能删除后残留 ID 装配时忽略。
    # 不塞进 tool_ids：技能不是"动作"，混进去会让工具列表与执行器都要多判一次类型
    skill_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    workflow_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=True)
    # draft 从未发布 / published 线上可用 / offline 有线上版本但已下线（docs/15 3.2，FR-039）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 最近一次生成的版本号
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    # Prompt 模板绑定（FR-028）：保存时用模板 + 变量渲染进 system_prompt 并记下模板版本；运行时仍只读 system_prompt
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)
    prompt_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 发布语义（FR-039）：本行是草稿，对外入口只读 published_version 指向的不可变快照；从未发布为空
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class AgentVersion(Base):
    """发布版本：不可变快照，字段只由 runtime.agent_config.snapshot_of 定义；回滚上线也生成新版本，历史不改写。"""

    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 发布说明


class PromptTemplate(Base, TimestampMixin):
    """Prompt 模板（FR-028）：内容里用 {{name}} 引用 variables 声明的变量；content / variables 变化时 version + 1 并写快照。"""

    __tablename__ = "prompt_templates"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class PromptTemplateVersion(Base):
    """模板版本快照：与智能体的 agent_versions 同一套语义，回滚也产生新版本，历史不可篡改。"""

    __tablename__ = "prompt_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_template_versions_template_version"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class Skill(Base, TimestampMixin):
    """技能（docs/17 §4）：一套"怎么做事"的知识 + 可选附带资源，运行时按需加载。

    与提示词模板的分工：模板是"人设"（保存时渲染进 system_prompt，一变就升版本），
    技能是"操作手册"（只把 name + description 放进提示词，模型需要时调内置工具 load_skill 取正文）。
    always_on 为真的技能正文常驻注入系统提示，适合短小且每轮都要的规则。
    正文可能含内部地址与操作规则，与提示词模板同口径：接口不回传给分享访客、改动写审计。
    """

    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 模型看到的名字，英文小写短横线（如 expense-form）：load_skill(name) 按它查找，重名会让模型取错手册
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 给模型看的一句话，决定它会不会调用这个技能；非空是硬要求，空的描述等于技能永远不被加载
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 附带资源清单 [{name, type, content}]，首版只存文本，不做文件上传
    resources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    always_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")  # content / description 变化 +1
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class McpServer(Base, TimestampMixin):
    """外部 MCP 服务器（docs/17 §5，P5）。

    首版只接 HTTP / SSE 传输：stdio 等于在服务器上执行配置里写的任意命令
    （同类问题见 MaxKB CVE-2026-39417），且要在镜像里装运行时。

    凭据走 secret_enc，与 tools 同一套加密（core/security.encrypt_secret），
    任何接口都不回传明文，只回 has_secret。
    """

    __tablename__ = "mcp_servers"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # http = Streamable HTTP（POST 一个端点，可返回 JSON 或 SSE 流）；sse = 旧版 HTTP+SSE（先 GET 拿端点）
    transport: Mapped[str] = mapped_column(String(16), nullable=False, default="http", server_default="http")
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    # 非敏感请求头；含凭据的键在接口层 422 拒绝（与 tools.config.headers 同一判定）
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    secret_enc: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    # 出站白名单：只写主机名，执行时按域名后缀匹配（与 tools 的 allowed_hosts 同一套判定）。
    # 这里为空是拒绝 —— MCP 的地址由管理员配，没配白名单就无从判断目标是否可信。
    allowed_hosts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 鉴权（M0，docs/15 RS-06）：auth 只放方式与位置 {type, location, name}，凭据加密后放 secret_enc，任何接口不回传
    auth: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    secret_enc: Mapped[str | None] = mapped_column(Text)
    # MCP 来源（docs/17 §5.2）：type='mcp' 时指向 mcp_servers，remote_name 是远端工具原名。
    # 不设外键到 mcp_servers：同步出来的行与服务器生命周期解耦，服务器删了这些行要留着
    # （否则会破坏已有智能体的 tool_ids 引用），由服务层在删除时统一停用。
    mcp_server_id: Mapped[int | None] = mapped_column(BigInteger)
    remote_name: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EmbeddingModel(Base, TimestampMixin):
    """向量模型配置：知识库建库时绑一个，入库与检索都按它走（一个库一个模型，与 LLM 的 models 表并列）。

    为什么单独一张表而不是复用 models：models 是对话（chat/completions）配置，字段语义（价格、思考模式、
    默认参数）对 embedding 端点全都不适用；混在一起会让"模型"页面同时出现两种调用协议，选错就报 400。

    dim 必须与 document_chunks.embedding 的列宽一致：pgvector 是定长列，维度和列宽不一致时插入直接报错，
    所以在保存时就校验，不留到入库时才炸（见 embedding_model_service.create/update）。

    api_key_enc 与 models.api_key_enc 同一口径：AES 加密落库，任何接口只回 has_key，明文不出服务端。
    """

    __tablename__ = "embedding_models"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    api_base: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 该模型实际产出的向量维度：保存时与 document_chunks.embedding 的列宽比对，不一致拒绝
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # 单次请求最多带几条文本（阿里云百炼 20，本地 oMLX 可更大）；入库流水线按它分批
    request_size: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 绑定的向量模型：建库时定，之后不可改（改了已有切片的向量就和库对不上）。
    # 2026-11-08 前是一个自由字符串 embedding_model，只记录不生效，默认值还写成了本平台不存在的
    # text-embedding-3-small；现在改成外键，入库与检索真的按它取模型。
    embedding_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("embedding_models.id", ondelete="RESTRICT"), nullable=False, index=True)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    # 权限：is_public=True 所有角色可见；False 仅 visible_roles 内角色可见
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    visible_roles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploading", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 已入库切片数，处理中逐批递增
    chunk_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 分片后确定的计划切片总数；处理中据此算进度
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)  # 开始向量化入库的时间，据此算速度与剩余
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)  # ready / failed 的时间
    processing_node: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 负责处理的节点（主机名）：共享库上多个后端只续本机的文档
    heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)  # 每批提交时刷新；长时间不动即中断，可续处理
    resume_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 本次处理从第几片接着做（续处理时非 0）


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(settings.EMBEDDING_DIM), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    # 两个通道各自的会话列表（docs/15 3.7.1，M2a）：界面按 (本人, ui)，API Key 按 (Key, 终端用户)
    # kind 决定这个会话属于哪类对话，三种类型的归属列互斥（docs/17 §3.3）：唯一性交给 DB 约束，
    # 应用层漏判时会在写入处直接失败，而不是留下一行"既绑智能体又绑模型"的脏数据。
    __table_args__ = (
        Index("ix_conversations_user_channel_updated", "user_id", "channel", "updated_at"),
        Index("ix_conversations_api_key_end_user_updated", "api_key_id", "end_user", "updated_at"),
        Index("ix_conversations_share_end_user_updated", "share_id", "end_user", "updated_at"),
        Index("ix_conversations_user_kind_updated", "user_id", "kind", "updated_at"),
        CheckConstraint(
            "(kind = 'agent' AND agent_id IS NOT NULL AND workflow_id IS NULL AND model_id IS NULL)"
            " OR (kind = 'workflow' AND workflow_id IS NOT NULL AND agent_id IS NULL AND model_id IS NULL)"
            " OR (kind = 'model' AND model_id IS NOT NULL AND agent_id IS NULL AND workflow_id IS NULL)",
            name="ck_conversations_kind",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 对话类型（docs/17 §3.1）：model 模型对话、agent 智能体对话、workflow 工作流对话。存量会话都是 agent
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="agent", server_default="agent")
    agent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True)
    # 模型对话直接指向模型行（不经过智能体）；与 agent_id / workflow_id 一样 CASCADE：删模型连带删会话，语义一致
    model_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("models.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # 会话通道：ui = 登录界面里的会话；api = API Key 发起的会话，只对该 Key（与同一个 end_user）可见，界面里看不到；
    # share = 分享链接的访客会话（docs/15 3.6）。归属判定见 conversation_service.owns
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="ui", server_default="ui")
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    end_user: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Key 背后的终端用户标识（调用方传），或分享公开模式的访客 id；不传为空
    share_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agent_shares.id", ondelete="CASCADE"), nullable=True)  # channel=share 时的分享链接
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 对话摘要持久化（FR-031）：summary 覆盖 id ≤ summary_upto_message_id 的更早消息，按批增量折叠，不再每轮重算
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_upto_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    summary_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    # 调用方的幂等键在会话内唯一（只约束非空的）：超时重试同一条消息不会重复落库、重复调模型（docs/15 3.7.1，M2a）
    __table_args__ = (
        Index("uq_messages_conversation_client_message", "conversation_id", "client_message_id", unique=True,
              postgresql_where=text("client_message_id IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 这一轮对话的运行记录（用户消息与回答都记）：带 client_message_id 重试时据此回放首次的结果（docs/15 3.7.1）
    run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 模型思维链（reasoning_content 全文，可空）：回答下方的"思考过程"折叠行，刷新后要能回看
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)


class Run(Base):
    __tablename__ = "runs"
    # 运营指标按来源排除调试流量、Key 用量按 api_key_id 聚合，都带发起时间区间
    __table_args__ = (
        Index("ix_runs_source_started_at", "source", "started_at"),
        Index("ix_runs_api_key_started_at", "api_key_id", "started_at"),
        Index("ix_runs_share_started_at", "share_id", "started_at"),  # 分享链接的每日总量按它计数（docs/15 3.6）
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # 运营统计快照（页面深度优化）：model_id 记发起时智能体绑定的模型（智能体换模型后旧运行仍归旧模型）；
    # cost 在收尾时按当时单价折算落库，改单价不追溯，趋势图不会被重写；conversation_id 让运行记录能跳回会话
    model_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 触发来源（2026-09-25 从 input.source 提成列，docs/15 OP-09a）：chat / ui / api_key / schedule / debug。
    # 运营指标按它排除调试流量；server_default 让部署窗口里旧代码的写入不失败，迁移回填可重复执行纠正
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ui")
    agent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 本次回答用的线上版本号；调试运行为空
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    schedule_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    share_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agent_shares.id", ondelete="SET NULL"), nullable=True)  # source=share 时的分享链接


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    cron: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class AgentShare(Base):
    """智能体的分享体验链接（docs/15 3.6，PB-01）：一个智能体一条；访客打开 /s/{code} 免登录（public）或用平台账号（login）对话。
    限额一律显式范围，不用"0 表示不限"（避免 API Key 配额 0 的歧义）。"""

    __tablename__ = "agent_shares"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)  # secrets.token_urlsafe 生成；重置链接时换新
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="public")  # public 免登录 / login 须平台账号（D-06）
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 访问密码（bcrypt），可空
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 改密码、改访问方式、重置链接时 +1，旧访客令牌失效
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=20)  # 整条链接每分钟（1～600）
    daily_message_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)  # 整条链接每天（1～100000），成本的硬上限
    visitor_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)  # 每位访客每天（1～1000）
    allow_http_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 访客对话是否装配 HTTP 工具
    show_citations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # 访客是否看得到引用（只给文档名与内容）
    # 公开访客的会话与运行记在创建者名下：创建者不能在分享还在时被删掉（RESTRICT）
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # 鉴权按哈希查找
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quota: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 入口治理（FR-025 / FR-026）：来源 IP 白名单（IP 或 CIDR 列表，空 = 不限制）；每分钟限速（0 = 用全局默认）
    allowed_ips: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 资源作用域（docs/15 3.7.1，D-09）：只能调这些智能体与工作流；检索时除公开库外只放行 kb_ids 内、且归属人可见的库。
    # 三者至少一个非空；没有"空 = 全部放行"的兜底
    agent_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    workflow_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    kb_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)


class RunNode(Base):
    __tablename__ = "run_nodes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class SystemSetting(Base):
    """运行时可调参数（页面"导入设置"可改）：键值对，规格 / 范围 / 默认值在 services/settings_service.SPECS。

    只收调优型参数（导入并发、批大小），密钥与地址这类环境相关的仍走 .env。没存过的键用 .env 默认值。
    """
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 操作人用户名快照，审计明细另有完整记录


class LlmCall(Base):
    """一次模型调用的完整记录（2026-11-08）：请求报文、响应报文、地址、工具定义、耗时。

    **为什么要这张表**：原来的调用链（run_nodes 的 trace step）只记 content_chars 与
    工具名。排查"模型为什么这么回答""为什么没调工具""上游返回了什么"时全都看不到 ——
    而这些问题恰恰只能靠原始报文回答，猜是猜不出来的。

    **打码口径**：只有凭据打码（api_key 换成 ***），其余全部原样保存 ——
    地址、请求体、响应体、工具定义、思考过程、错误原文都要能看见。
    凭据不进日志是本项目的硬约束，其余内容对使用者完全透明。

    体积控制：单条请求 / 响应各截断到 config 里配置的上限（默认 256KB），
    超出部分注明原文长度。截断是"看得见的不完整"，不是"悄悄丢掉"。

    不设外键到 runs / models：运行记录会被清理，而调用日志是排查依据，要能独立留存；
    run_id / model_id 只作为可查询的普通列。
    """

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_run_id_id", "run_id", "id"),
        Index("ix_llm_calls_started_at", "started_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 归属：run_id 为空表示不是对话发起的调用（如连通测试、摘要、检索改写）
    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    model_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 调用方：chat / workflow / debug / summary / rewrite / probe / embedding
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="chat", index=True)
    # 实际请求地址（完整 URL，含 base_url 与路径）——
    # 排查"配错 base_url""打到了哪个上游"全靠它
    url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    # 请求报文（tool 定义、messages、参数全在里面）与响应报文（含 SSE 原文）
    request_body: Mapped[dict | None] = mapped_column(JSONB)
    response_body: Mapped[str | None] = mapped_column(Text)
    # 响应里解析出的正文与思考过程，便于不点开原文就能看
    response_text: Mapped[str | None] = mapped_column(Text)
    reasoning_text: Mapped[str | None] = mapped_column(Text)
    # 本次调用发出去的工具定义（名字 + 描述 + 参数声明），与使用的工具名分开：
    # 前者是"给了模型什么"，后者是"模型用了什么"
    tools_offered: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # 用量与耗时
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)
    # 报文是否被截断（超出上限）。true 时 request_body / response_body 里注明了原文长度
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

