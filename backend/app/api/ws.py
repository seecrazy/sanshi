"""WS /ws：首消息鉴权（token 不进 URL）、60s 空闲超时、重连后 drain 离线队列。DESIGN §9。"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.services import notify_service

logger = logging.getLogger("sanshi.ws")
router = APIRouter()
AUTH_TIMEOUT = 10
IDLE_TIMEOUT = 60


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    user_id = None
    hub = ws.app.state.hub
    try:
        # 首条消息鉴权
        auth_raw = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT)
        if auth_raw.get("type") != "auth":
            await ws.close(code=4401)
            return
        user_id = decode_token(auth_raw.get("token", ""), ws.app.state.settings)
        if user_id is None:
            await ws.close(code=4401)
            return
        hub.register(user_id, ws)
        await ws.send_json({"type": "auth.ok"})
        await notify_service.drain_offline(ws.app.state.redis, hub, user_id)

        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                await ws.close(code=4408)
                return
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        logger.exception("ws error, user=%s", user_id)
    finally:
        if user_id is not None:
            hub.unregister(user_id, ws)
