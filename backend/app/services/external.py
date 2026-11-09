"""外部服务接入层（模拟）：支付网关 / 短信。真实接入时仅替换本文件的实现。

约束 #11：所有外部调用必须经熔断器包裹（默认 3s 超时），熔断打开时走降级。
- 支付：熔断打开 -> 直接报"支付通道繁忙"（资金操作不可静默降级）；
- 短信：熔断打开/失败 -> 跳过并记日志（通知类可降级）。
"""
import asyncio
import logging
import random

from app.config import Settings
from app.core.circuit_breaker import CircuitOpenError, get_breaker
from app.core.errors import BizError

logger = logging.getLogger("sanshi.external")


class GatewayError(Exception):
    pass


async def _gateway_charge(total_cents: int, order_no: str) -> dict:
    """模拟支付网关远程调用。故障注入见 charge()。"""
    await asyncio.sleep(0.02)
    return {"channel": "mock", "paid_cents": total_cents, "order_no": order_no}


async def charge(settings: Settings, total_cents: int, order_no: str) -> dict:
    """支付网关调用（熔断包裹）。网关故障/超时 -> BizError(400)；熔断打开 -> CircuitOpenError(400)。"""
    breaker = get_breaker("payment", min_calls=settings.breaker_min_calls)

    async def _call():
        if random.random() < settings.mock_pay_fail_rate:
            raise GatewayError("支付网关超时（模拟故障）")
        return await _gateway_charge(total_cents, order_no)

    import asyncio

    try:
        return await breaker.call(_call)
    except (GatewayError, asyncio.TimeoutError) as e:
        raise BizError(f"支付通道繁忙，请稍后重试（{e}）") from e


async def _sms_send(phone: str, text: str) -> None:
    await asyncio.sleep(0.01)  # 模拟运营商耗时


async def sms_notify(phone: str, text: str) -> bool:
    breaker = get_breaker("sms")
    try:
        await breaker.call(_sms_send, phone, text, fallback=None)
        return True
    except CircuitOpenError:
        logger.warning("sms circuit open, skip notify to %s", phone)
        return False
    except Exception:
        logger.warning("sms send failed to %s", phone, exc_info=True)
        return False
