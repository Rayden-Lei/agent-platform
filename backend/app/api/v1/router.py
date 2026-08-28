from fastapi import APIRouter

from app.api.v1 import agents, api_keys, audit, auth, chat, conversations, kb, models, runs, schedules, tools, users, workflows

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(models.router)
api_router.include_router(agents.router)
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(workflows.router)
api_router.include_router(kb.router)
api_router.include_router(tools.router)
api_router.include_router(runs.router)
api_router.include_router(audit.router)
api_router.include_router(api_keys.router)
api_router.include_router(schedules.router)
