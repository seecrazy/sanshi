"""状态机迁移表驱动测试：全组合断言（DESIGN §16）。"""
from app.services.order_service import TERMINAL, TRANSITIONS

EXPECTED = {
    "PENDING_PAYMENT": {"PAID", "CANCELLED"},
    "PAID": {"PENDING_ACCEPT"},
    "PENDING_ACCEPT": {"ACCEPTED", "REFUNDED"},
    "ACCEPTED": {"ASSIGNED", "DISPUTED"},
    "ASSIGNED": {"PICKED", "DISPUTED"},
    "PICKED": {"DELIVERED", "DISPUTED"},
    "DELIVERED": {"COMPLETED", "DISPUTED"},
    "DISPUTED": {"REFUNDED", "ACCEPTED", "ASSIGNED", "PICKED", "DELIVERED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
    "REFUNDED": set(),
}


def test_transitions_table_matches_design():
    assert TRANSITIONS == EXPECTED


def test_terminal_states_closed():
    assert TERMINAL == {"COMPLETED", "CANCELLED", "REFUNDED"}


def test_happy_path_chain_allowed():
    chain = ["PENDING_PAYMENT", "PAID", "PENDING_ACCEPT", "ACCEPTED", "ASSIGNED", "PICKED", "DELIVERED", "COMPLETED"]
    for frm, to in zip(chain, chain[1:]):
        assert to in TRANSITIONS[frm], f"{frm} -> {to} 应允许"


def test_dispute_reachable_from_all_delivery_states():
    for state in ("ACCEPTED", "ASSIGNED", "PICKED", "DELIVERED"):
        assert "DISPUTED" in TRANSITIONS[state]


def test_dispute_can_restore_every_origin():
    for origin in ("ACCEPTED", "ASSIGNED", "PICKED", "DELIVERED"):
        assert origin in TRANSITIONS["DISPUTED"]


def test_paid_cannot_skip_to_accept():
    assert "ACCEPTED" not in TRANSITIONS["PAID"]
    assert "ASSIGNED" not in TRANSITIONS["PAID"]
    assert "ASSIGNED" not in TRANSITIONS["PENDING_ACCEPT"]  # 抢单池只含 ACCEPTED（约束 #10）
