"""通用熔断器（DESIGN §10.5 / 约束 #11）。

所有第三方调用（支付网关、短信、地图）必须经 `breaker.call()` 包裹：
- 默认 3s 超时快速失败；
- 滚动窗口内 失败率 >= failure_rate 且样本数 >= min_calls -> OPEN（熔断）；
- OPEN 持续 cooldown 后进入 HALF_OPEN 放探测请求：探测全部成功 -> CLOSED，任一失败 -> 重新 OPEN；
- OPEN 期间调用走 fallback（降级）或抛 CircuitOpenError。
"""
import asyncio
import logging
import time
from collections import deque

from app.core.errors import BizError

logger = logging.getLogger("sanshi.breaker")

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"


class CircuitOpenError(BizError):
    def __init__(self, name: str):
        super().__init__(f"服务暂时不可用（{name} 熔断保护中），请稍后再试")


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        timeout: float = 3.0,
        min_calls: int = 20,
        failure_rate: float = 0.5,
        window: float = 60.0,
        cooldown: float = 30.0,
        probes: int = 3,
    ):
        self.name = name
        self.timeout = timeout
        self.min_calls = min_calls
        self.failure_rate = failure_rate
        self.window = window
        self.cooldown = cooldown
        self.probes = probes
        self._events: deque[tuple[float, bool]] = deque()
        self._state = CLOSED
        self._opened_at = 0.0
        self._probe_ok = 0

    @property
    def state(self) -> str:
        if self._state == OPEN and time.monotonic() - self._opened_at >= self.cooldown:
            return HALF_OPEN
        return self._state

    def _trip_open(self, now: float) -> None:
        self._state = OPEN
        self._opened_at = now
        logger.warning("circuit %s -> OPEN", self.name)

    def _record(self, ok: bool, now: float) -> None:
        if self.state == HALF_OPEN:
            if ok:
                self._probe_ok += 1
                if self._probe_ok >= self.probes:
                    self._state = CLOSED
                    self._events.clear()
                    logger.info("circuit %s -> CLOSED (recovered)", self.name)
            else:
                self._trip_open(now)
            return
        self._events.append((now, ok))
        while self._events and now - self._events[0][0] > self.window:
            self._events.popleft()
        if len(self._events) >= self.min_calls:
            fails = sum(1 for _, o in self._events if not o)
            if fails / len(self._events) >= self.failure_rate:
                self._trip_open(now)

    async def call(self, fn, *args, fallback=None, **kwargs):
        state = self.state
        if state == OPEN:
            if fallback is not None:
                return fallback
            raise CircuitOpenError(self.name)
        if state == HALF_OPEN and self._state != HALF_OPEN:
            self._state = HALF_OPEN
            self._probe_ok = 0
        now = time.monotonic()
        try:
            result = await asyncio.wait_for(fn(*args, **kwargs), self.timeout)
        except Exception:
            self._record(False, now)
            raise
        self._record(True, now)
        return result

    def stats(self) -> dict:
        now = time.monotonic()
        fails = sum(1 for ts, ok in self._events if not ok)
        return {
            "name": self.name,
            "state": self.state,
            "window_calls": len(self._events),
            "window_failures": fails,
            "timeout": self.timeout,
        }


_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, **kwargs)
    return _breakers[name]


def all_breaker_stats() -> list[dict]:
    return [b.stats() for b in _breakers.values()]
