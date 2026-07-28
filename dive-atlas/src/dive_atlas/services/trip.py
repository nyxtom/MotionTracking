from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite
from dive_atlas.models.capabilities import PhenomenonOccurrence, SiteProfile


@dataclass
class TripRequest:
    """Natural-language trip intent, structured."""

    days: int = 10
    certs: list[str] = field(default_factory=lambda: ["aow"])
    want: list[str] = field(default_factory=list)  # caves, pelagics, wreck, ...
    max_depth_m: float | None = 30.0
    avoid_monsoon: bool = True
    travel_month: int | None = None  # 1–12; default = now
    allow_overhead: bool = False
    allow_deco: bool = False
    country_codes: list[str] = field(default_factory=list)
    limit: int = 25


@dataclass
class TripCandidate:
    site_id: str
    slug: str
    name: str
    score: float
    reasons: list[str]
    site_types: list[str]
    depth_max_m: float | None
    country_code: str | None
    locality: str | None
    backup: bool = False


def _month(req: TripRequest) -> int:
    return req.travel_month or date.today().month


_WANT_SYNONYMS: dict[str, set[str]] = {
    "caves": {"cave", "cavern", "cenote"},
    "cave": {"cave", "cavern", "cenote"},
    "cenote": {"cenote", "cave", "cavern"},
    "cenotes": {"cenote", "cave", "cavern"},
    "pelagics": {"pelagics", "pelagic", "manta", "shark", "whale_shark", "drift"},
    "pelagic": {"pelagics", "pelagic", "manta", "shark"},
    "wrecks": {"wreck"},
    "wreck": {"wreck"},
    "reefs": {"reef", "wall", "coral"},
    "reef": {"reef", "wall"},
    "macro": {"muck", "macro"},
    "muck": {"muck", "macro"},
}


def _expand_want(want: set[str]) -> set[str]:
    out: set[str] = set()
    for w in want:
        out |= _WANT_SYNONYMS.get(w, {w})
        out.add(w)
    return out


def compose_trip(session: Session, req: TripRequest) -> list[TripCandidate]:
    """Rank sites for a trip intent.

    Uses site_profiles when present; falls back to dive_sites.site_types / skill_level.
    Phenomena windows boost score when overlapping travel month.
    """
    month = _month(req)
    want = _expand_want({w.lower() for w in req.want})
    certs = {c.lower() for c in req.certs}

    # Always include curated/profiled sites, then a broader sample for discovery.
    profiled = select(DiveSite, SiteProfile).join(
        SiteProfile, SiteProfile.site_id == DiveSite.id
    )
    broad = select(DiveSite, SiteProfile).outerjoin(
        SiteProfile, SiteProfile.site_id == DiveSite.id
    )
    for stmt_base in (profiled, broad):
        stmt = stmt_base
        if req.country_codes:
            stmt = stmt.where(DiveSite.country_code.in_([c.upper() for c in req.country_codes]))
        if req.max_depth_m is not None:
            stmt = stmt.where(
                or_(
                    DiveSite.depth_max_m.is_(None),
                    DiveSite.depth_max_m <= req.max_depth_m + 5,
                )
            )
        if want & {"cave", "cavern", "cenote"}:
            # Prefer ontology hits in SQL when caves requested
            stmt = stmt.where(
                or_(
                    DiveSite.site_types.overlap(list(want & {"cave", "cavern", "cenote"})),
                    SiteProfile.experiences.overlap(list(want)),
                    SiteProfile.site_id.is_not(None),
                )
            )
        if stmt_base is profiled:
            profiled_rows = session.execute(stmt).all()
        else:
            broad_rows = session.execute(stmt.limit(3000)).all()

    seen_ids: set[str] = set()
    rows: list = []
    for site, profile in list(profiled_rows) + list(broad_rows):
        if site.id in seen_ids:
            continue
        seen_ids.add(site.id)
        rows.append((site, profile))

    candidates: list[TripCandidate] = []

    phenom_sites: set[str] = set()
    phenom_rows = session.execute(
        select(PhenomenonOccurrence.site_id).where(
            PhenomenonOccurrence.site_id.is_not(None),
        )
    ).all()
    for (site_id,) in phenom_rows:
        if site_id:
            phenom_sites.add(site_id)

    for site, profile in rows:
        reasons: list[str] = []
        score = 0.35 * float(site.confidence or 0.5)
        if profile:
            score += 0.2  # prefer profiled / curated sites for itineraries

        types = {t.lower() for t in (site.site_types or [])}
        experiences = set((profile.experiences if profile else []) or [])
        experiences |= types
        tags = {t.lower() for t in (site.tags or [])}
        experiences |= tags

        if want:
            overlap = want & experiences
            if not overlap:
                score -= 0.25
            else:
                score += 0.3 * min(len(overlap), 3)
                reasons.append("matches:" + ",".join(sorted(overlap)[:4]))

        # Skill gate
        if profile:
            if profile.overhead_class in {"cave", "cavern", "wreck_penetration"} and not req.allow_overhead:
                cave_certs = {"cave", "full_cave", "intro_cave", "cavern"}
                if not (cave_certs & certs):
                    if not (want & {"cave", "cavern", "cenote"}):
                        continue
                    # asked for caves without cave cert → skip
                    if profile.overhead_class == "cave" and "cavern" not in certs:
                        continue
            if profile.deco_likely and not req.allow_deco:
                continue
            if profile.monsoon_months and req.avoid_monsoon and month in profile.monsoon_months:
                continue
            if profile.best_months and month in profile.best_months:
                score += 0.2
                reasons.append(f"best_month:{month}")
            if profile.beginner_ok and "ow" in certs:
                score += 0.05
            req_certs = {c.lower() for c in (profile.cert_required or [])}
            hard = req_certs & {"full_cave", "intro_cave", "cave"}
            if hard and not (hard & certs) and "cavern" not in certs:
                continue
        else:
            if site.skill_level == "cave_trained" and not (
                {"cave", "full_cave", "intro_cave", "cavern"} & certs
            ):
                if not (want & {"cave", "cavern", "cenote"}):
                    continue
            if site.skill_level == "technical" and not req.allow_deco:
                continue

        if req.max_depth_m is not None and site.depth_max_m and site.depth_max_m > req.max_depth_m:
            if site.depth_min_m and site.depth_min_m <= req.max_depth_m:
                reasons.append("stay_shallower")
                score -= 0.05
            else:
                continue

        if site.id in phenom_sites:
            score += 0.1
            reasons.append("phenomenon_window")

        backup = bool(want) and not (want & experiences)
        candidates.append(
            TripCandidate(
                site_id=site.id,
                slug=site.slug,
                name=site.name,
                score=round(max(score, 0.0), 3),
                reasons=reasons,
                site_types=list(site.site_types or []),
                depth_max_m=site.depth_max_m,
                country_code=site.country_code,
                locality=site.locality,
                backup=backup,
            )
        )

    candidates.sort(key=lambda c: (c.backup, -c.score, c.name))
    primary = [c for c in candidates if not c.backup][: req.limit]
    if len(primary) < req.limit:
        primary += [c for c in candidates if c.backup][: req.limit - len(primary)]
    return primary
