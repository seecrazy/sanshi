"""计票纯函数测试：权重归一化 / quorum / 少数保护抬阈值 / 弃权分母 / 陪审裁决。"""
from app.services.tally_service import Vote, jury_verdict, tally

WEIGHTS = {"rider": 0.5, "consumer": 0.3, "merchant": 0.2}
QUORUM = {"rider": 2, "consumer": 2, "merchant": 1}


def test_all_for_approves():
    votes = [
        Vote("rider", "FOR"), Vote("rider", "FOR"),
        Vote("consumer", "FOR"), Vote("consumer", "FOR"),
        Vote("merchant", "FOR"),
    ]
    r = tally(votes, WEIGHTS, QUORUM)
    assert r.approved and r.weighted_support == 1.0 and r.quorum_met_all


def test_abstain_excluded_from_denominator():
    votes = [Vote("rider", "FOR"), Vote("rider", "ABSTAIN")] + \
            [Vote("consumer", "FOR"), Vote("consumer", "FOR"), Vote("merchant", "FOR")]
    r = tally(votes, WEIGHTS, QUORUM)
    # 骑手 1FOR/0AGAINST -> 支持率 1.0，弃权不影响
    assert r.roles["rider"]["support"] == 1.0
    assert r.approved


def test_quorum_failure_blocks():
    votes = [Vote("rider", "FOR"), Vote("rider", "FOR"), Vote("consumer", "FOR"), Vote("merchant", "FOR")]
    r = tally(votes, WEIGHTS, QUORUM)  # consumer 只有 1 票 < quorum 2
    assert not r.approved and not r.quorum_met_all


def test_minority_protection_elevates_threshold():
    # 商家全反对（支持率 0 < 0.3）-> 阈值抬到 0.6
    votes = [Vote("rider", "FOR"), Vote("rider", "FOR"),
             Vote("consumer", "FOR"), Vote("consumer", "FOR"),
             Vote("merchant", "AGAINST")]
    r = tally(votes, WEIGHTS, QUORUM)
    assert r.minority_flag and r.threshold_used == 0.6
    # 加权支持度 = 0.5 + 0.3 = 0.8 >= 0.6 仍通过
    assert r.approved

    # 若加权支持度介于 0.5~0.6 之间则被抬升的阈值拦下：
    votes2 = [Vote("rider", "FOR"), Vote("rider", "AGAINST"),  # rider 支持率 0.5 -> 贡献 0.25
              Vote("consumer", "FOR"), Vote("consumer", "AGAINST"),  # consumer 0.5 -> 0.15
              Vote("merchant", "AGAINST")]  # merchant 0 -> 少数保护
    r2 = tally(votes2, WEIGHTS, QUORUM)
    assert r2.minority_flag
    assert abs(r2.weighted_support - 0.4) < 1e-9
    assert not r2.approved


def test_weight_normalization():
    # 权重和不必为 1（5/3/2 -> 0.5/0.3/0.2）
    w = {"rider": 5, "consumer": 3, "merchant": 2}
    votes = [Vote("rider", "AGAINST"), Vote("rider", "AGAINST"),
             Vote("consumer", "FOR"), Vote("consumer", "FOR"),
             Vote("merchant", "FOR")]
    r = tally(votes, w, QUORUM)
    # 支持度 = 0.5*0 + 0.3*1 + 0.2*1 = 0.5；骑手支持率 0 触发少数保护抬阈值 0.6 -> 不通过
    assert not r.approved and abs(r.weighted_support - 0.5) < 1e-9
    assert r.minority_flag and r.threshold_used == 0.6


def test_jury_verdict_majority_tie_and_empty():
    assert jury_verdict(["REFUND", "REFUND", "REJECT"])[0] == "REFUND"
    assert jury_verdict(["REFUND", "REJECT"])[0] == "REFUND"  # 平票倾斜消费者
    assert jury_verdict([])[0] == "REJECT"  # 零票驳回
    assert jury_verdict(["REJECT", "REJECT"])[0] == "REJECT"
