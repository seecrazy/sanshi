"""治理域：席位 / 议题 / 表决 / 决议 / 陪审。"""
import uuid
from datetime import datetime

from sqlalchemy import (
    func,
    func,
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class GovSeat(Base, TimestampMixin):
    __tablename__ = "gov_seats"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_seat_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # CONSUMER / RIDER / MERCHANT
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # 资格快照
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Issue(Base, TimestampMixin):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(String(200), default="")  # 一句话结论
    content: Mapped[str] = mapped_column(Text)
    # REVIEWING / OPEN / CLOSED / VETOED / REJECTED
    status: Mapped[str] = mapped_column(String(20), default="REVIEWING", index=True)
    weights: Mapped[dict] = mapped_column(JSON)   # {"rider":0.5,"consumer":0.3,"merchant":0.2}
    quorum: Mapped[dict] = mapped_column(JSON)    # {"rider":5,"consumer":5,"merchant":3}
    proposer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    voting_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    veto_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class IssueVote(Base):
    __tablename__ = "issue_votes"
    __table_args__ = (UniqueConstraint("issue_id", "user_id", name="uq_issue_vote"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))
    choice: Mapped[str] = mapped_column(String(10))  # FOR / AGAINST / ABSTAIN
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Decision(Base):
    """决议/否决公示。"""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(20), index=True)  # ISSUE / JURY / VETO
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("issues.id"), nullable=True)
    jury_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class JuryCase(Base, TimestampMixin):
    __tablename__ = "jury_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    consumer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    merchant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 商家所属 user_id
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)  # OPEN / RESOLVED / CANCELLED
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)       # REFUND / REJECT
    pre_dispute_status: Mapped[str] = mapped_column(String(20))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JuryAssignment(Base):
    __tablename__ = "jury_assignments"
    __table_args__ = (UniqueConstraint("case_id", "juror_id", name="uq_jury_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("jury_cases.id"), index=True)
    juror_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING / VOTED / RECUSED / EXPIRED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JuryVote(Base):
    __tablename__ = "jury_votes"
    __table_args__ = (UniqueConstraint("case_id", "juror_id", name="uq_jury_vote"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("jury_cases.id"), index=True)
    juror_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    choice: Mapped[str] = mapped_column(String(10))  # REFUND / REJECT
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
