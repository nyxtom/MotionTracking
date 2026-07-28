from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dive_atlas.magazine_schemas import MagazineArticleIn, MagazineIssueIn, MagazineIn
from dive_atlas.models.magazine import Magazine, MagazineArticle, MagazineIssue


def upsert_magazine(session: Session, payload: MagazineIn) -> Magazine:
    row = session.scalar(select(Magazine).where(Magazine.slug == payload.slug))
    if row is None:
        row = Magazine(slug=payload.slug, languages=[], countries=[], regions=[], focus=[], properties={})
        session.add(row)
    row.name = payload.name
    row.name_local = payload.name_local
    row.language = payload.language
    row.languages = payload.languages or [payload.language]
    row.countries = payload.countries
    row.regions = payload.regions
    row.base_url = payload.base_url
    row.archive_url = payload.archive_url
    row.focus = payload.focus
    row.status = payload.status
    row.priority = payload.priority
    row.notes = payload.notes
    row.properties = {**(row.properties or {}), **payload.properties}
    session.flush()
    return row


def upsert_issue(session: Session, magazine: Magazine, payload: MagazineIssueIn) -> MagazineIssue:
    row = session.scalar(
        select(MagazineIssue).where(
            MagazineIssue.magazine_id == magazine.id,
            MagazineIssue.external_id == payload.external_id,
        )
    )
    if row is None:
        row = MagazineIssue(
            magazine_id=magazine.id,
            external_id=payload.external_id,
            raw={},
        )
        session.add(row)
    row.title = payload.title
    row.issue_number = payload.issue_number
    row.published_on = payload.published_on
    row.year = payload.year
    row.month = payload.month
    row.url = payload.url
    row.pdf_url = payload.pdf_url
    row.language = payload.language
    row.raw = payload.raw or {}
    session.flush()
    return row


def upsert_article(
    session: Session,
    magazine: Magazine,
    payload: MagazineArticleIn,
    issue: MagazineIssue | None = None,
) -> MagazineArticle:
    row = session.scalar(
        select(MagazineArticle).where(
            MagazineArticle.magazine_id == magazine.id,
            MagazineArticle.external_id == payload.external_id,
        )
    )
    if row is None:
        row = MagazineArticle(
            magazine_id=magazine.id,
            external_id=payload.external_id,
            title=payload.title,
            authors=[],
            place_mentions=[],
            site_slugs=[],
            tags=[],
            raw={},
        )
        session.add(row)
    row.issue_id = issue.id if issue else row.issue_id
    row.title = payload.title
    row.url = payload.url
    row.authors = payload.authors
    row.published_on = payload.published_on
    row.language = payload.language
    row.summary = payload.summary
    row.body_text = payload.body_text
    row.place_mentions = payload.place_mentions
    row.tags = payload.tags
    row.confidence = payload.confidence
    row.raw = payload.raw or {}
    session.flush()
    return row


def sync_registry(session: Session, magazines: list[MagazineIn]) -> int:
    for mag in magazines:
        upsert_magazine(session, mag)
    return len(magazines)


def ingest_magazine_crawl(
    session: Session,
    magazine: MagazineIn,
    issues: list[MagazineIssueIn],
    articles: list[MagazineArticleIn],
) -> dict[str, int]:
    mag = upsert_magazine(session, magazine)
    issue_map: dict[str, MagazineIssue] = {}
    for issue in issues:
        issue_map[issue.external_id] = upsert_issue(session, mag, issue)
    for article in articles:
        linked = None
        if article.issue_external_id:
            linked = issue_map.get(article.issue_external_id)
        upsert_article(session, mag, article, linked)
    return {"issues": len(issues), "articles": len(articles)}
