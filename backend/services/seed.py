"""Seed the database from Collatz_conjecture.bib. Idempotent — skips existing keys."""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session_maker, engine
from backend.models import Base, Paper
from backend.services.bibtex_parser import parse_bibliography


async def seed(bib_path: Path | None = None):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    papers = parse_bibliography(bib_path)
    print(f"Parsed {len(papers)} papers from BibTeX")

    async with async_session_maker() as session:  # type: AsyncSession
        existing_keys = set(
            (await session.execute(select(Paper.bibtex_key))).scalars().all()
        )
        inserted = 0
        for p in papers:
            if p["bibtex_key"] in existing_keys:
                continue
            paper = Paper(
                bibtex_key=p["bibtex_key"],
                entry_type=p["entry_type"],
                title=p["title"],
                authors=p["authors"],
                year=p.get("year"),
                journal=p.get("journal"),
                booktitle=p.get("booktitle"),
                publisher=p.get("publisher"),
                volume=p.get("volume"),
                number=p.get("number"),
                pages=p.get("pages"),
                doi=p.get("doi"),
                url=p.get("url"),
                abstract=p.get("abstract"),
                note=p.get("note"),
                extra_fields=p.get("extra_fields"),
            )
            session.add(paper)
            inserted += 1

        await session.commit()
        print(f"Inserted {inserted} new papers (skipped {len(papers) - inserted} existing)")


if __name__ == "__main__":
    asyncio.run(seed())
