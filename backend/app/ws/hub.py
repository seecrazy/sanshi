"""WebSocket 连接管理。按 user_id 键控（DESIGN §9.2）。业务代码禁止直接使用本模块（约束 #2）。"""
import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("sanshi.ws")


class Hub:
    def __init__(self) -> None:
        self._conns: dict[int, set[WebSocket]] = {}

    def register(self, user_id: int, ws: WebSocket) -> None:
        self._conns.setdefault(user_id, set()).add(ws)

    def unregister(self, user_id: int, ws: WebSocket) -> None:
        conns = self._conns.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._conns.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._conns

    async def send(self, user_ids: list[int], data: dict) -> set[int]:
        """返回成功送达的 user_id 集合。"""
        delivered: set[int] = set()
        for uid in user_ids:
            for ws in list(self._conns.get(uid, ())):
                try:
                    await ws.send_json(data)
                    delivered.add(uid)
                except Exception:
                    self.unregister(uid, ws)
        return delivered

    async def broadcast(self, data: dict) -> None:
        for uid in list(self._conns.keys()):
            await self.send([uid], data)
