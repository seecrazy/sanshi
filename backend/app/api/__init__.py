from fastapi import APIRouter

from app.api import admin, auth, governance, merchants, orders, riders, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth.addr_router)
api_router.include_router(merchants.router)
api_router.include_router(merchants.self_router)
api_router.include_router(orders.router)
api_router.include_router(riders.router)
api_router.include_router(riders.self_router)
api_router.include_router(governance.router)
api_router.include_router(admin.router)
api_router.include_router(ws.router)
