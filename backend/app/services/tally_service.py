"""计票纯函数（约束 #6）：不触 DB、不触 Redis。

规则（DESIGN §12.3）：
- 每角色支持率 s_r = for / (for + against)，弃权不计入分母；
- 加权支持度 S = Σ w_r * s_r（权重归一化）；
- 通过 = 所有配置角色达法定人数 且 S >= 阈值；
- 少数角色保护：任一达法定人数角色的 s_r < 30% -> 阈值从 50% 抬升至 60%。
"""
from dataclasses import dataclass, field

FOR, AGAINST, ABSTAIN = "FOR", "AGAINST", "ABSTAIN"
ROLE_ORDER = ("rider", "consumer", "merchant")  # 多席位用户的投票角色优先级


@dataclass(frozen=True)
class Vote:
    role: str
    choice: str


@dataclass
class RoleStat:
    votes_for: int = 0
    against: int = 0
    abstain: int = 0
    support: float | None = None  # None = 无有效票
    quorum_met: bool = False

    @property
    def total(self) -> int:
        return self.votes_for + self.against + self.abstain


@dataclass
class TallyResult:
    approved: bool
    weighted_support: float
    threshold_used: float
    quorum_met_all: bool
    minority_flag: bool
    roles: dict[str, dict] = field(default_factory=dict)
    total_votes: int = 0

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "weighted_support": round(self.weighted_support, 4),
            "threshold_used": self.threshold_used,
            "quorum_met_all": self.quorum_met_all,
            "minority_flag": self.minority_flag,
            "roles": self.roles,
            "total_votes": self.total_votes,
        }


def tally(
    votes: list[Vote],
    weights: dict[str, float],
    quorum: dict[str, int],
    *,
    threshold: float = 0.5,
    minority_threshold: float = 0.3,
    elevated_threshold: float = 0.6,
) -> TallyResult:
    w_sum = sum(float(v) for v in weights.values()) or 1.0
    norm = {r: float(w) / w_sum for r, w in weights.items()}

    stats: dict[str, RoleStat] = {r: RoleStat() for r in norm}
    total = 0
    for v in votes:
        total += 1
        st = stats.get(v.role)
        if st is None:
            continue
        if v.choice == FOR:
            st.votes_for += 1
        elif v.choice == AGAINST:
            st.against += 1
        elif v.choice == ABSTAIN:
            st.abstain += 1

    minority_flag = False
    weighted_support = 0.0
    quorum_met_all = True
    role_detail: dict[str, dict] = {}
    for role, st in stats.items():
        decided = st.votes_for + st.against
        st.support = (st.votes_for / decided) if decided else None
        st.quorum_met = st.total >= int(quorum.get(role, 0))
        if not st.quorum_met:
            quorum_met_all = False
        if st.support is not None:
            weighted_support += norm[role] * st.support
        if st.quorum_met and st.support is not None and st.support < minority_threshold:
            minority_flag = True
        role_detail[role] = {
            "for": st.votes_for,
            "against": st.against,
            "abstain": st.abstain,
            "support": round(st.support, 4) if st.support is not None else None,
            "quorum": int(quorum.get(role, 0)),
            "quorum_met": st.quorum_met,
            "weight": round(norm[role], 4),
        }

    threshold_used = elevated_threshold if minority_flag else threshold
    approved = quorum_met_all and weighted_support >= threshold_used
    return TallyResult(
        approved=approved,
        weighted_support=weighted_support,
        threshold_used=threshold_used,
        quorum_met_all=quorum_met_all,
        minority_flag=minority_flag,
        roles=role_detail,
        total_votes=total,
    )


def jury_verdict(choices: list[str]) -> tuple[str, str]:
    """陪审裁决纯函数：多数决，平票支持退款（消费者倾斜），零票驳回。choices 元素: REFUND/REJECT。"""
    refunds = sum(1 for c in choices if c == "REFUND")
    rejects = len(choices) - refunds
    if not choices:
        return "REJECT", "无人表决，按驳回处理"
    if refunds >= rejects:
        return "REFUND", f"{refunds}:{rejects}，支持退款" + ("（平票倾斜消费者）" if refunds == rejects else "")
    return "REJECT", f"{refunds}:{rejects}，驳回争议"
