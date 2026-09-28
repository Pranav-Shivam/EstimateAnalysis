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
