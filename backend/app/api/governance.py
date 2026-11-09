"""治理中心 API：席位/议题/表决/决议/陪审。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis, get_settings
from app.models import Decision, GovSeat, Issue, IssueVote, User
from app.schemas import IssueIn, JuryVoteIn, VoteIn
from app.services import governance_service, jury_service
from app.services.tally_service import Vote, tally

router = APIRouter(prefix="/gov", tags=["governance"])


def issue_out(issue: Issue, my_vote: str | None = None) -> dict:
    return {
        "id": issue.id, "title": issue.title, "summary": issue.summary, "content": issue.content,
        "status": issue.status, "weights": issue.weights, "quorum": issue.quorum,
        "proposer_id": issue.proposer_id,
        "voting_opens_at": issue.voting_opens_at.isoformat() if issue.voting_opens_at else None,
        "voting_closes_at": issue.voting_closes_at.isoformat() if issue.voting_closes_at else None,
        "result": issue.result, "veto_reason": issue.veto_reason, "my_vote": my_vote,
    }


@router.get("/seats/me")
async def my_seats(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    seats = await governance_service.my_seats(db, user.id)
    rows = (await db.execute(select(GovSeat).where(GovSeat.user_id == user.id))).scalars().all() if seats else []
    return {
        "seats": [
            {"role": s.role, "metrics": s.metrics, "computed_at": s.computed_at.isoformat() if s.computed_at else None}
            for s in rows
        ]
    }


@router.post("/issues")
async def create_issue(
    body: IssueIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    issue = await governance_service.create_issue(db, settings, user, body.model_dump())
    return issue_out(issue)


@router.get("/issues")
async def list_issues(
    status: str = "",
    page: int = 1,
    size: int = 20,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(Issue)
    if status:
        stmt = stmt.where(Issue.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Issue.id.desc()).offset((page - 1) * size).limit(size)
    issues = (await db.execute(stmt)).scalars().all()
    my_votes = {}
    if user and issues:
        rows = (
            await db.execute(
                select(IssueVote.issue_id, IssueVote.choice).where(
                    IssueVote.user_id == user.id, IssueVote.issue_id.in_([i.id for i in issues])
                )
            )
        ).all()
        my_votes = dict(rows)
    return {"total": total, "items": [issue_out(i, my_votes.get(i.id)) for i in issues]}


@router.get("/issues/{issue_id}")
async def issue_detail(
    issue_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    issue = await db.get(Issue, issue_id)
    if issue is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("议题不存在")
    my_vote = (
        await db.execute(select(IssueVote.choice).where(IssueVote.issue_id == issue_id, IssueVote.user_id == user.id))
    ).scalar_one_or_none()
    votes = (
        await db.execute(select(IssueVote.role, IssueVote.choice).where(IssueVote.issue_id == issue_id))
    ).all()
    live = tally([Vote(r, c) for r, c in votes], issue.weights, issue.quorum).as_dict()
    return {**issue_out(issue, my_vote), "live_tally": live}


@router.post("/issues/{issue_id}/vote")
async def vote_issue(
    issue_id: int,
    body: VoteIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    vote = await governance_service.vote_issue(db, user, issue_id, body.choice)
    return {"issue_id": issue_id, "choice": vote.choice, "role": vote.role}


@router.get("/decisions")
async def decisions(
    page: int = 1,
    size: int = 20,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(Decision).order_by(Decision.id.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * size).limit(size))).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": d.id, "type": d.type, "title": d.title, "content": d.content,
                "result": d.result,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ],
    }


# ---- 陪审 ----


@router.get("/jury/tasks")
async def jury_tasks(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"items": await jury_service.my_jury_tasks(db, user)}


@router.post("/jury/{case_id}/vote")
async def jury_vote(
    case_id: int,
    body: JuryVoteIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await jury_service.jury_vote(db, user, case_id, body.choice, body.comment)


@router.post("/jury/{case_id}/recuse")
async def jury_recuse(
    case_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    settings=Depends(get_settings),
):
    return await jury_service.recuse(db, settings, redis, user, case_id)
