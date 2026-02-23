"""Seed reviews from Lagarias annotated bibliographies.

Downloads the Lagarias survey PDFs from arXiv, finds the page for each paper,
and creates Review entries linking to the PDF with page anchors.

Idempotent — skips papers that already have a review with the same URL.

Usage:
    python -m backend.services.seed_reviews
"""

import asyncio
import json
import re
import subprocess
import tempfile
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session_maker, engine
from backend.models import Base, Paper, Review, User

ROOT = Path(__file__).resolve().parent.parent.parent

SURVEYS = [
    {
        "curation": ROOT / "curations" / "Lagarias_I.json",
        "pdf_url": "https://arxiv.org/pdf/math/0309224",
        "citation": (
            'J. C. Lagarias, "The 3x+1 problem: An annotated bibliography'
            ' (1963\u20131999)", arXiv:math/0309224'
        ),
    },
    {
        "curation": ROOT / "curations" / "Lagarias_II.json",
        "pdf_url": "https://arxiv.org/pdf/math/0608208",
        "citation": (
            'J. C. Lagarias, "The 3x+1 problem: An annotated bibliography,'
            ' II (2000\u20132009)", arXiv:math/0608208'
        ),
    },
]

BOT_USERNAME = "lagarias-bot"
BOT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _normalize(text: str) -> str:
    """Replace ligatures and strip diacritics for fuzzy matching."""
    text = text.replace("\ufb00", "ff").replace("\ufb03", "ffi")
    text = text.replace("\ufb02", "fl").replace("\ufb01", "fi")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _extract_key_parts(key: str) -> tuple[str, str]:
    """Extract (first_author_last_name, year) from a bibtex key."""
    match = re.match(r"^(.+?)(\d{4})[a-z]?$", key)
    if not match:
        return key, ""
    names_part, year = match.group(1), match.group(2)
    names = re.findall(r"[A-Z][a-z]+", names_part)
    return (names[0] if names else names_part), year


def _find_bib_start(pages: list[str], first_author: str) -> int:
    """Find the 0-based page index where the bibliography entries begin.

    Searches for the first numbered entry (``1. <first_author>``).
    Falls back to page 0 if detection fails.
    """
    norm_author = _normalize(first_author)
    for i, page in enumerate(pages):
        norm_page = _normalize(page)
        if re.search(rf"^\s*1\.\s+.*{re.escape(norm_author)}", norm_page, re.MULTILINE):
            return i
    return 0


def _find_entry(
    last_name: str, year: str, pages: list[str], start: int = 0,
) -> tuple[int, int] | None:
    """Find the PDF page and entry number for a bibliography entry.

    Returns ``(page_number, entry_number)`` or *None*.

    Looks for the pattern ``N. ...LastName... (Year`` on a single line
    (the actual entry header), which avoids false matches from
    cross-references within other entries' annotation text.
    """
    norm_name = _normalize(last_name)
    # Primary: numbered entry "N. ...Name... (Year" on one line
    pat = rf"^\s*(\d+)\.\s+[^\n]*{re.escape(norm_name)}[^\n]*\({year}"
    for i in range(start, len(pages)):
        norm_page = _normalize(pages[i])
        m = re.search(pat, norm_page, re.MULTILINE)
        if m:
            return i + 1, int(m.group(1))
    # Fallback: numbered entry where year wraps to the next line
    for i in range(start, len(pages)):
        norm_page = _normalize(pages[i])
        for m in re.finditer(r"^\s*(\d+)\.\s+", norm_page, re.MULTILINE):
            snippet = norm_page[m.start() : m.start() + 300]
            if norm_name in snippet and year in snippet:
                return i + 1, int(m.group(1))
    return None


def _download_and_extract(pdf_url: str, tmpdir: str) -> list[str]:
    """Download a PDF and extract text split by page."""
    pdf_path = Path(tmpdir) / "survey.pdf"
    txt_path = Path(tmpdir) / "survey.txt"

    subprocess.run(
        ["curl", "-sL", "-o", str(pdf_path), pdf_url],
        check=True,
    )
    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
        check=True,
    )
    return txt_path.read_text().split("\f")


def build_page_map(
    curation_keys: list[str], pages: list[str],
) -> dict[str, tuple[int, int]]:
    """Map bibtex keys to ``(page_number, entry_number)``."""
    # Detect where the bibliography section starts using the first key
    first_author, _ = _extract_key_parts(curation_keys[0])
    bib_start = _find_bib_start(pages, first_author)

    page_map: dict[str, tuple[int, int]] = {}
    for key in curation_keys:
        last_name, year = _extract_key_parts(key)
        result = _find_entry(last_name, year, pages, start=bib_start)
        if result:
            page_map[key] = result
    return page_map


async def _ensure_bot_user(session: AsyncSession) -> User:
    """Get or create the bot user for seeded reviews."""
    result = await session.execute(select(User).where(User.id == BOT_ID))
    user = result.unique().scalar_one_or_none()
    if user:
        return user

    user = User(
        id=BOT_ID,
        username=BOT_USERNAME,
        email="lagarias-bot@ccchallenge.local",
        hashed_password="!disabled",
        is_active=False,
        is_superuser=False,
        is_verified=False,
        is_maintainer=False,
    )
    session.add(user)
    await session.flush()
    return user


async def seed_reviews():
    """Seed Review entries from Lagarias annotated bibliographies."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        bot = await _ensure_bot_user(session)

        # Load all papers keyed by bibtex_key
        result = await session.execute(select(Paper))
        papers_by_key: dict[str, Paper] = {p.bibtex_key: p for p in result.scalars().all()}

        # Load existing review URLs to skip duplicates
        result = await session.execute(
            select(Review.paper_id, Review.external_url).where(Review.user_id == bot.id)
        )
        existing_reviews: set[tuple[int, str]] = set(result.all())

        total_inserted = 0
        total_skipped = 0
        total_missing = 0

        for survey in SURVEYS:
            curation_path = survey["curation"]
            pdf_url = survey["pdf_url"]
            citation = survey["citation"]

            with open(curation_path) as f:
                curation = json.load(f)
            keys = curation["curation"]
            survey_name = curation["name"]

            print(f"\nProcessing: {survey_name}")
            print(f"  Downloading {pdf_url} ...")

            with tempfile.TemporaryDirectory() as tmpdir:
                pages = _download_and_extract(pdf_url, tmpdir)

            page_map = build_page_map(keys, pages)
            print(f"  Matched {len(page_map)}/{len(keys)} papers to pages")

            inserted = 0
            skipped = 0
            missing_papers = []
            unmatched_pages = []

            for key in keys:
                if key not in papers_by_key:
                    missing_papers.append(key)
                    continue

                if key not in page_map:
                    unmatched_pages.append(key)
                    continue

                paper = papers_by_key[key]
                page_num, entry_num = page_map[key]
                review_url = f"{pdf_url}#page={page_num}"
                comment = f"Entry #{entry_num} in {citation}"

                if (paper.id, review_url) in existing_reviews:
                    skipped += 1
                    continue

                review = Review(
                    paper_id=paper.id,
                    user_id=bot.id,
                    external_url=review_url,
                    comment=comment,
                )
                session.add(review)
                existing_reviews.add((paper.id, review_url))
                inserted += 1

            if missing_papers:
                print(f"  Papers not in database ({len(missing_papers)}): {', '.join(missing_papers[:5])}{'...' if len(missing_papers) > 5 else ''}")
            if unmatched_pages:
                print(f"  Could not match to page ({len(unmatched_pages)}): {', '.join(unmatched_pages)}")
            print(f"  Inserted {inserted} reviews (skipped {skipped} existing)")

            total_inserted += inserted
            total_skipped += skipped
            total_missing += len(missing_papers)

        await session.commit()
        print(f"\nDone. Inserted {total_inserted} reviews total ({total_skipped} skipped, {total_missing} papers not in DB)")


if __name__ == "__main__":
    asyncio.run(seed_reviews())
