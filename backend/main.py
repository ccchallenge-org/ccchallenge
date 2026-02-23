from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth.router import router as auth_router
from backend.config import settings
from backend.auth.users import current_optional_user
from backend.database import engine, get_async_session
from backend.models import AuditReport, Base, Formalisation, FormalisationStatus, Paper, Review, User, Vote
from backend.routers import formalisations, papers, reviews, stats, votes

BACKEND_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="ccchallenge", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory=BACKEND_DIR / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=BACKEND_DIR / "templates")
templates.env.globals["oauth_github"] = bool(settings.github_client_id)
templates.env.globals["oauth_discord"] = bool(settings.discord_client_id)

@app.middleware("http")
async def oauth_callback_redirect(request: Request, call_next):
    response = await call_next(request)
    if (
        "/auth/" in request.url.path
        and request.url.path.endswith("/callback")
        and response.status_code == 204
    ):
        redirect = RedirectResponse(url="/", status_code=302)
        for key, value in response.headers.raw:
            if key == b"set-cookie":
                redirect.headers.append("set-cookie", value.decode())
        return redirect
    return response

# API routers
app.include_router(auth_router, prefix="/api")
app.include_router(papers.router, prefix="/api")
app.include_router(formalisations.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(votes.router, prefix="/api")


# ── Page routes ─────────────────────────────────────────────────────────────


def _vote_won_subquery():
    """Subquery returning paper_ids where yes votes >= no votes (with at least 1 vote)."""
    return (
        select(Vote.paper_id)
        .group_by(Vote.paper_id)
        .having(
            func.sum(case((Vote.vote == True, 1), else_=0))
            >= func.sum(case((Vote.vote == False, 1), else_=0))
        )
        .subquery()
    )


async def _compute_stats(session: AsyncSession) -> dict:
    total = (await session.execute(select(func.count(Paper.id)))).scalar() or 0

    # Compute max status priority per paper: audited(3) > auditing(2) > formalising(1)
    status_priority = case(
        (Formalisation.status == FormalisationStatus.audited, 3),
        (Formalisation.status == FormalisationStatus.auditing, 2),
        else_=1,
    )
    max_status_subq = (
        select(
            Formalisation.paper_id,
            func.max(status_priority).label("max_priority"),
        )
        .group_by(Formalisation.paper_id)
        .subquery()
    )

    # Count papers per computed status bucket
    rows = (await session.execute(
        select(max_status_subq.c.max_priority, func.count()).group_by(max_status_subq.c.max_priority)
    )).all()
    bucket = {row[0]: row[1] for row in rows}

    papers_with_formalisations = sum(bucket.values())
    reviews = (await session.execute(select(func.count(Review.id)))).scalar() or 0

    # Papers that won the "should be formalised" vote (yes >= no)
    won_subq = _vote_won_subquery()
    vote_won = (await session.execute(
        select(func.count()).select_from(
            select(Paper.id)
            .where(Paper.id.in_(select(won_subq.c.paper_id)))
            .subquery()
        )
    )).scalar() or 0

    return {
        "not_started": total - papers_with_formalisations,
        "formalising": bucket.get(1, 0),
        "auditing": bucket.get(2, 0),
        "audited": bucket.get(3, 0),
        "reviews": reviews,
        "vote_won": vote_won,
    }


PAGE_SIZE = 20


@app.get("/verify")
async def verify_page(request: Request, token: str = ""):
    return templates.TemplateResponse("verify.html", {"request": request, "token": token})


@app.get("/")
async def index(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    # Total count for stats header
    total = (await session.execute(select(func.count(Paper.id)))).scalar() or 0

    # First page of papers
    query = (
        select(Paper)
        .options(selectinload(Paper.formalisations))
        .order_by(Paper.bibtex_key)
        .limit(PAGE_SIZE)
    )
    result = await session.execute(query)
    paper_list = result.scalars().unique().all()

    # Stats
    stat_counts = await _compute_stats(session)

    # Formalisation / review counts for displayed papers
    paper_ids = [p.id for p in paper_list]
    fc_map = {}
    rc_map = {}
    vc_map = {}
    if paper_ids:
        fc_q = (
            select(Formalisation.paper_id, func.count().label("cnt"))
            .where(Formalisation.paper_id.in_(paper_ids))
            .group_by(Formalisation.paper_id)
        )
        fc_map = dict((await session.execute(fc_q)).all())
        rc_q = (
            select(Review.paper_id, func.count().label("cnt"))
            .where(Review.paper_id.in_(paper_ids))
            .group_by(Review.paper_id)
        )
        rc_map = dict((await session.execute(rc_q)).all())
        vc_q = (
            select(Vote.paper_id, func.count().label("cnt"))
            .where(Vote.paper_id.in_(paper_ids))
            .group_by(Vote.paper_id)
        )
        vc_map = dict((await session.execute(vc_q)).all())

    has_more = len(paper_list) == PAGE_SIZE

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "papers": paper_list,
            "total": total,
            "stats": stat_counts,
            "fc_map": fc_map,
            "rc_map": rc_map,
            "vc_map": vc_map,
            "page": 1,
            "has_more": has_more,
        },
    )


# ── HTMX partial routes ────────────────────────────────────────────────────


@app.get("/htmx/paper-list")
async def htmx_paper_list(
    request: Request,
    status: str | None = None,
    has_reviews: bool | None = None,
    vote_won: bool | None = None,
    order: str = "authors",
    q: str | None = None,
    page: int = 1,
    anchor: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    query = select(Paper)
    if vote_won or status == "vote_won":
        won_subq = _vote_won_subquery()
        query = query.where(
            Paper.id.in_(select(won_subq.c.paper_id))
        )
        status = None  # consumed
    elif has_reviews:
        query = query.where(Paper.id.in_(select(Review.paper_id)))
    elif status:
        if status == FormalisationStatus.not_started.value:
            query = query.where(~Paper.id.in_(select(Formalisation.paper_id)))
        else:
            query = query.where(
                Paper.id.in_(
                    select(Formalisation.paper_id).where(Formalisation.status == status)
                )
            )
    if q:
        pattern = f"%{q}%"
        query = query.where(
            Paper.title.ilike(pattern) | Paper.authors.ilike(pattern) | Paper.bibtex_key.ilike(pattern)
        )

    # Count total before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    ordering = Paper.year.desc() if order == "year" else Paper.bibtex_key

    # If anchor is set, figure out which page it's on and load pages 1..N
    if anchor:
        pos_q = select(func.count()).select_from(
            query.where(Paper.bibtex_key < anchor).subquery()
        )
        position = (await session.execute(pos_q)).scalar() or 0
        page = (position // PAGE_SIZE) + 1

    offset = (page - 1) * PAGE_SIZE if not anchor else 0
    limit = PAGE_SIZE if not anchor else page * PAGE_SIZE
    query = (
        query.options(selectinload(Paper.formalisations))
        .order_by(ordering)
        .offset(offset)
        .limit(limit)
    )
    papers = (await session.execute(query)).scalars().unique().all()

    paper_ids = [p.id for p in papers]
    fc_map = {}
    rc_map = {}
    vc_map = {}
    if paper_ids:
        fc_q = (
            select(Formalisation.paper_id, func.count().label("cnt"))
            .where(Formalisation.paper_id.in_(paper_ids))
            .group_by(Formalisation.paper_id)
        )
        fc_map = dict((await session.execute(fc_q)).all())
        rc_q = (
            select(Review.paper_id, func.count().label("cnt"))
            .where(Review.paper_id.in_(paper_ids))
            .group_by(Review.paper_id)
        )
        rc_map = dict((await session.execute(rc_q)).all())
        vc_q = (
            select(Vote.paper_id, func.count().label("cnt"))
            .where(Vote.paper_id.in_(paper_ids))
            .group_by(Vote.paper_id)
        )
        vc_map = dict((await session.execute(vc_q)).all())

    end = (offset + len(papers)) if not anchor else len(papers)
    has_more = end < total

    # Build the current filter query string for the "Load more" button
    filter_params = []
    if status:
        filter_params.append(f"status={status}")
    if has_reviews:
        filter_params.append("has_reviews=true")
    if vote_won:
        filter_params.append("vote_won=true")
    if order and order != "authors":
        filter_params.append(f"order={order}")
    if q:
        filter_params.append(f"q={q}")
    filter_qs = "&".join(filter_params)

    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "user": user,
            "papers": papers,
            "total": total,
            "fc_map": fc_map,
            "rc_map": rc_map,
            "vc_map": vc_map,
            "page": page,
            "has_more": has_more,
            "filter_qs": filter_qs,
        },
    )


@app.get("/htmx/paper-card/{bibtex_key}")
async def htmx_paper_card(
    bibtex_key: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    result = await session.execute(
        select(Paper).where(Paper.bibtex_key == bibtex_key).options(selectinload(Paper.formalisations))
    )
    paper = result.scalar_one_or_none()
    if not paper:
        return templates.TemplateResponse("partials/paper_card.html", {"request": request, "paper": None})

    fc = (await session.execute(select(func.count()).where(Formalisation.paper_id == paper.id))).scalar() or 0
    rc = (await session.execute(select(func.count()).where(Review.paper_id == paper.id))).scalar() or 0
    vc = (await session.execute(select(func.count()).where(Vote.paper_id == paper.id))).scalar() or 0

    return templates.TemplateResponse(
        "partials/paper_card.html",
        {
            "request": request,
            "user": user,
            "paper": paper,
            "fc_map": {paper.id: fc},
            "rc_map": {paper.id: rc},
            "vc_map": {paper.id: vc},
        },
    )


@app.get("/htmx/paper-detail/{bibtex_key}")
async def htmx_paper_detail(
    bibtex_key: str,
    request: Request,
    tab: str = "reviews",
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    result = await session.execute(
        select(Paper).where(Paper.bibtex_key == bibtex_key).options(selectinload(Paper.formalisations))
    )
    paper = result.scalar_one_or_none()
    if not paper:
        return templates.TemplateResponse("partials/paper_detail.html", {"request": request, "paper": None})

    formalisations_result = await session.execute(
        select(Formalisation).where(Formalisation.paper_id == paper.id).order_by(Formalisation.created_at.desc())
    )
    formalisations_list = formalisations_result.scalars().all()

    # Fetch user display names and audit reports for formalisations
    for f in formalisations_list:
        name = (await session.execute(select(User.username).where(User.id == f.user_id))).scalar_one_or_none()
        f._user_display_name = name
        audit_reports_result = await session.execute(
            select(AuditReport).where(AuditReport.formalisation_id == f.id).order_by(AuditReport.created_at.desc())
        )
        f._audit_reports = audit_reports_result.scalars().all()
        for ar in f._audit_reports:
            ar_name = (await session.execute(select(User.username).where(User.id == ar.user_id))).scalar_one_or_none()
            ar._user_display_name = ar_name

    reviews_result = await session.execute(
        select(Review).where(Review.paper_id == paper.id).order_by(Review.created_at.desc())
    )
    reviews_list = reviews_result.scalars().all()
    for r in reviews_list:
        name = (await session.execute(select(User.username).where(User.id == r.user_id))).scalar_one_or_none()
        r._user_display_name = name

    return templates.TemplateResponse(
        "partials/paper_detail.html",
        {
            "request": request,
            "user": user,
            "paper": paper,
            "formalisations": formalisations_list,
            "reviews": reviews_list,
            "initial_tab": tab if tab in ("reviews", "formalisations", "audits") else "reviews",
        },
    )


@app.get("/htmx/paper-poll/{bibtex_key}")
async def htmx_paper_poll(
    bibtex_key: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    result = await session.execute(
        select(Paper).where(Paper.bibtex_key == bibtex_key)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        return templates.TemplateResponse("partials/paper_poll.html", {"request": request, "paper": None, "votes": [], "user": None})

    votes_result = await session.execute(
        select(Vote).where(Vote.paper_id == paper.id).order_by(Vote.created_at.desc())
    )
    votes_list = votes_result.scalars().all()
    for v in votes_list:
        name = (await session.execute(select(User.username).where(User.id == v.user_id))).scalar_one_or_none()
        v._user_display_name = name

    # Check if paper has formalisations (voting closed)
    has_formalisations = (await session.execute(
        select(func.count()).where(Formalisation.paper_id == paper.id)
    )).scalar() or 0

    return templates.TemplateResponse(
        "partials/paper_poll.html",
        {
            "request": request,
            "user": user,
            "paper": paper,
            "votes": votes_list,
            "voting_closed": has_formalisations > 0,
        },
    )


@app.get("/htmx/stats")
async def htmx_stats(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    total = (await session.execute(select(func.count(Paper.id)))).scalar() or 0
    counts = await _compute_stats(session)

    return templates.TemplateResponse(
        "partials/stats_bar.html",
        {"request": request, "total": total, "stats": counts},
    )
