from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth.router import router as auth_router
from backend.config import settings
from backend.auth.users import current_optional_user, current_superuser
from backend.database import engine, get_async_session
from backend.models import AuditReport, Base, Formalisation, FormalisationStatus, Paper, Review, User
from backend.routers import formalisations, papers, reviews, stats

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

def latex_quotes(s: str) -> str:
    """Convert LaTeX-style quotes to plain double quotes."""
    return s.replace("``", '"').replace("''", '"')

templates.env.filters["latex_quotes"] = latex_quotes

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


# ── Page routes ─────────────────────────────────────────────────────────────


async def _compute_stats(session: AsyncSession) -> dict:
    # Only count papers that are not excluded from the goal
    included_filter = Paper.exclusion_reason.is_(None)
    total = (await session.execute(select(func.count(Paper.id)).where(included_filter))).scalar() or 0

    # Compute max status priority per paper: audited(3) > auditing(2) > formalising(1)
    # Only for papers not excluded from the goal
    included_paper_ids = select(Paper.id).where(included_filter)
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
        .where(Formalisation.paper_id.in_(included_paper_ids))
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

    return {
        "not_started": total - papers_with_formalisations,
        "formalising": bucket.get(1, 0),
        "auditing": bucket.get(2, 0),
        "audited": bucket.get(3, 0),
        "reviews": reviews,
    }


@app.get("/verify")
async def verify_page(request: Request, token: str = ""):
    return templates.TemplateResponse("verify.html", {"request": request, "token": token})


@app.get("/")
async def index(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    # Total counts
    total = (await session.execute(select(func.count(Paper.id)))).scalar() or 0
    goal_total = (await session.execute(select(func.count(Paper.id)).where(Paper.exclusion_reason.is_(None)))).scalar() or 0

    # All papers
    query = (
        select(Paper)
        .options(selectinload(Paper.formalisations))
        .order_by(Paper.bibtex_key)
    )
    result = await session.execute(query)
    paper_list = result.scalars().unique().all()

    # Stats
    stat_counts = await _compute_stats(session)

    # Formalisation / review counts for displayed papers
    paper_ids = [p.id for p in paper_list]
    fc_map = {}
    rc_map = {}
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

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "papers": paper_list,
            "total": total,
            "goal_total": goal_total,
            "stats": stat_counts,
            "fc_map": fc_map,
            "rc_map": rc_map,
        },
    )


# ── HTMX partial routes ────────────────────────────────────────────────────


@app.get("/htmx/paper-list")
async def htmx_paper_list(
    request: Request,
    status: str | None = None,
    has_reviews: bool | None = None,
    order: str = "authors",
    q: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    query = select(Paper)
    if has_reviews:
        query = query.where(Paper.id.in_(select(Review.paper_id)))
    elif status:
        if status == "excluded":
            query = query.where(Paper.exclusion_reason.isnot(None))
        elif status == FormalisationStatus.not_started.value:
            query = query.where(~Paper.id.in_(select(Formalisation.paper_id)), Paper.exclusion_reason.is_(None))
        elif status == "ai_assisted":
            query = query.where(
                Paper.id.in_(
                    select(Formalisation.paper_id).where(Formalisation.ai_assisted == True)
                )
            )
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

    ordering = Paper.year.desc() if order == "year" else Paper.bibtex_key
    query = (
        query.options(selectinload(Paper.formalisations))
        .order_by(ordering)
    )
    papers = (await session.execute(query)).scalars().unique().all()

    paper_ids = [p.id for p in papers]
    fc_map = {}
    rc_map = {}
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

    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "user": user,
            "papers": papers,
            "fc_map": fc_map,
            "rc_map": rc_map,
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

    return templates.TemplateResponse(
        "partials/paper_card.html",
        {
            "request": request,
            "user": user,
            "paper": paper,
            "fc_map": {paper.id: fc},
            "rc_map": {paper.id: rc},
        },
    )


@app.get("/htmx/paper-edit/{bibtex_key}")
async def htmx_paper_edit(
    bibtex_key: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(current_optional_user),
):
    if not user:
        return Response(status_code=403)
    result = await session.execute(select(Paper).where(Paper.bibtex_key == bibtex_key))
    paper = result.scalar_one_or_none()
    if not paper:
        return Response(status_code=404)
    return templates.TemplateResponse(
        "partials/paper_edit.html",
        {"request": request, "user": user, "paper": paper},
    )


@app.get("/htmx/paper-detail/{bibtex_key}")
async def htmx_paper_detail(
    bibtex_key: str,
    request: Request,
    tab: str = "reviews",
    add: bool = False,
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
            "auto_add": add,
        },
    )


@app.get("/htmx/stats")
async def htmx_stats(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    total = (await session.execute(select(func.count(Paper.id)).where(Paper.exclusion_reason.is_(None)))).scalar() or 0
    counts = await _compute_stats(session)

    return templates.TemplateResponse(
        "partials/stats_bar.html",
        {"request": request, "total": total, "stats": counts},
    )


# ── Admin routes ───────────────────────────────────────────────────────────


@app.get("/admin")
async def admin_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    result = await session.execute(select(User).order_by(User.username))
    users = result.unique().scalars().all()
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "user": user, "users": users},
    )


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    target = (await session.execute(select(User).where(User.id == user_id))).unique().scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await session.delete(target)
    await session.commit()
    return Response(status_code=204)
