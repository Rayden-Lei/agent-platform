"""v1 路由聚合：把各业务模块的 router 统一挂载到 api_router 下。

每个模块内部自带 prefix 与 tags，这里只负责组合，不声明路径。
"""

from fastapi import APIRouter

from app.api.v1 import agents, api_keys, audit, auth, chat, conversations, kb, models, prompt_templates, runs, schedules, stats, system, tools, users, workflows

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(models.router)
api_router.include_router(agents.router)
api_router.include_router(prompt_templates.router)
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(workflows.router)
api_router.include_router(kb.router)
api_router.include_router(tools.router)
api_router.include_router(runs.router)
api_router.include_router(audit.router)
api_router.include_router(api_keys.router)
api_router.include_router(schedules.router)
api_router.include_router(system.router)
api_router.include_router(stats.router)
