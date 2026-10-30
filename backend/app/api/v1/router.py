from fastapi import APIRouter

from app.api.v1.endpoints import auth, events, recommendations, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
