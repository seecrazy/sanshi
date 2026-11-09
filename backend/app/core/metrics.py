"""轻量请求指标（进程内，M11 压测配套）。单进程口径；多实例部署时由采集端聚合。"""
import time
from collections import Counter, deque

from starlette.types import ASGIApp, Receive, Scope, Send


class Metrics:
    def __init__(self, max_samples: int = 10000):
        self.latencies: deque[float] = deque(maxlen=max_samples)
        self.path_counts: Counter = Counter()
        self.errors_5xx = 0
        self.errors_4xx = 0
        self.started_at = time.monotonic()

    def observe(self, path: str, status: int, ms: float) -> None:
        self.latencies.append(ms)
        self.path_counts[path] += 1
        if status >= 500:
            self.errors_5xx += 1
        elif status >= 400:
            self.errors_4xx += 1

    @staticmethod
    def _pct(sorted_vals: list, pct: float) -> float:
        if not sorted_vals:
            return 0.0
        idx = min(int(len(sorted_vals) * pct), len(sorted_vals) - 1)
        return round(sorted_vals[idx], 2)

    def snapshot(self) -> dict:
        vals = sorted(self.latencies)
        elapsed = max(time.monotonic() - self.started_at, 0.001)
        return {
            "requests": len(vals),
            "rps": round(len(vals) / elapsed, 2),
            "latency_ms": {
                "p50": self._pct(vals, 0.50),
                "p95": self._pct(vals, 0.95),
                "p99": self._pct(vals, 0.99),
                "max": self._pct(vals, 1.0),
            },
            "errors_4xx": self.errors_4xx,
            "errors_5xx": self.errors_5xx,
            "top_paths": self.path_counts.most_common(10),
        }


metrics = Metrics()


class MetricsMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500
        t0 = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.observe(scope.get("path", "?"), status, (time.perf_counter() - t0) * 1000)
