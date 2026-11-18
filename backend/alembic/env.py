"""Alembic 环境（2026-11-18 接入，docs/09 第三梯队「Alembic 待做」）。

职责
----
- 连接串只有 app.config.settings.DATABASE_URL 一个来源（见 alembic.ini 顶部的说明）；
- target_metadata 取 app/db/models.py 声明的 Base.metadata，autogenerate 据此比对库结构；
- 迁移脚本一律是"未来增量"，接入前的存量结构由 baseline revision 标记（versions/20261118_000000_baseline.py）。

为什么不用 config.set_main_option("sqlalchemy.url", ...)
------------------------------------------------------
ConfigParser 会对值做 % 插值：口令里一旦出现 %，set_main_option / get_main_option 要么抛
InterpolationSyntaxError，要么把 %xx 当占位符吃掉。直接把 URL 交给 create_engine、不经过 ini，
省掉这一类只在特定口令下才炸、而且报错信息完全看不出原因的坑。
"""
from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, pool

import app.db.models  # noqa: F401  导入即把所有表注册到 Base.metadata
from app.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False：不关掉 app.* 的 logger。迁移里若调用了服务层代码（数据修复），
    # 它的日志要能看见，而不是被 alembic 的 ini 静默关掉。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# 不属于本仓库模型的表：LangGraph 的 checkpointer 自己建（app/workflow/checkpointer.py，
# 表名 checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations）。
# 不排除的话 autogenerate 会把它们当成"模型里删掉的表"，生成 drop_table —— 那是把工作流的
# 全部检查点连表一起删掉。用前缀而不是逐个列名，langgraph 以后加表也不会漏。
_EXTERNAL_TABLE_PREFIXES = ("checkpoint",)


def _include_object(obj, name, type_, reflected, compare_to):
    """autogenerate 的对象过滤器：只排除外部组件自己管理的表，其余全部参与比对。"""
    if type_ == "table" and name is not None and name.startswith(_EXTERNAL_TABLE_PREFIXES):
        return False
    return True


def _render_item(type_, obj, autogen_context):
    """autogenerate 的类型渲染钩子：给 pgvector 的向量类型补上 import。

    不接管的话，生成的文件里写的是 pgvector.sqlalchemy.vector.VECTOR(dim=768)，
    却不会补 import —— 那份 revision 一执行就 NameError，而 autogenerate 本身不报错，
    属于"生成成功、执行才炸"的静默缺陷。返回 False 表示其余类型走 Alembic 默认渲染。
    """
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.VECTOR(dim={obj.dim})"
    return False


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=_include_object,
        render_item=_render_item,
        # 类型变化（varchar(64) → varchar(128) 之类）要能被 autogenerate 发现
        compare_type=True,
        # 不比对 server_default：模型里 server_default 的写法与存量库的默认值表达式不完全一致，
        # 打开只会让每次 autogenerate 都夹带一堆噪音 DDL，把真实变更淹没。
        compare_server_default=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """离线模式（--sql）：只生成 SQL，不连库。URL 直接传，不经过 ini 的插值。"""
    _configure(url=settings.DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：一次性短命连接。

    NullPool：迁移跑完就断开，不进池。共享库的 max_connections 很紧（docs/03），
    迁移进程没有理由留一条空闲连接。
    """
    connectable = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool, future=True)
    try:
        with connectable.connect() as connection:
            _configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
