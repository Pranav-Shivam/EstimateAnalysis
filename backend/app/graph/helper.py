import hashlib
from collections import Counter

from app.graph.constant import MAX_EXAMPLE_SKUS, MAX_MEMBER_NAMES
from app.graph.schemas import CommunityStats


def match_site(hint: str, sites) -> str | None:
    """The one site a free-text hint points at. A zip in the hint is the more specific signal, so it is checked
    first and on its own; a street name is only consulted when the hint names no zip at all. None when the
    signal in play names no site or more than one."""
    text = hint.lower()
    zip_matches = [site.site_id for site in sites if site.zip in text]
    if zip_matches:
        return zip_matches[0] if len(zip_matches) == 1 else None
    street_matches = [site.site_id for site in sites if _street(site) and _street(site) in text]
    return street_matches[0] if len(street_matches) == 1 else None


def _street(site) -> str:
    return site.address.split(",")[0].strip().lower()


def member_hash(sku_ids) -> str:
    """Identity of a community by its members, so a relabeled community still finds its cached summary."""
    return hashlib.sha256("\n".join(sorted(sku_ids)).encode("utf-8")).hexdigest()


def build_community_stats(rows: list[dict]) -> list[CommunityStats]:
    by_community: dict[int, list[dict]] = {}
    for row in rows:
        by_community.setdefault(row["community"], []).append(row)

    stats = []
    for community_id in sorted(by_community):
        members = sorted(by_community[community_id], key=lambda m: m["sku_id"])
        categories = Counter(m["category"] for m in members)
        dominant, count = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[0]
        stats.append(CommunityStats(
            community_id=community_id, size=len(members),
            families=tuple(sorted({m["family"] for m in members if m["family"]})),
            dominant_category=dominant, dominant_category_share=round(count / len(members), 3),
            discontinued_count=sum(1 for m in members if m["discontinued"]),
            requirement_count=sum(1 for m in members if m["has_requirements"]),
            example_sku_ids=tuple(m["sku_id"] for m in members[:MAX_EXAMPLE_SKUS]),
            member_names=tuple(m["name"] for m in members[:MAX_MEMBER_NAMES]),
            member_hash=member_hash(m["sku_id"] for m in members),
        ))
    return stats
