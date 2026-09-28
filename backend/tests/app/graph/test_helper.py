from types import SimpleNamespace

from app.graph.helper import match_site

SITES = [
    SimpleNamespace(site_id="SITE-1", address="12 Elm Street, Springfield, IL", zip="62701"),
    SimpleNamespace(site_id="SITE-2", address="12 Elm Street, Portland, OR", zip="97201"),
    SimpleNamespace(site_id="SITE-3", address="9 Oak Avenue, Austin, TX", zip="73301"),
]


def test_a_zip_in_the_hint_picks_that_site():
    assert match_site("job over at 62701 next week", SITES) == "SITE-1"


def test_a_unique_street_in_the_hint_picks_that_site():
    assert match_site("the 9 oak avenue job", SITES) == "SITE-3"


def test_matching_is_case_insensitive():
    assert match_site("9 OAK AVENUE", SITES) == "SITE-3"


def test_a_street_shared_by_two_sites_is_ambiguous():
    assert match_site("12 Elm Street", SITES) is None


def test_a_street_plus_a_zip_that_agree_is_still_one_site():
    assert match_site("12 Elm Street, 97201", SITES) == "SITE-2"


def test_a_hint_naming_two_different_sites_is_ambiguous():
    assert match_site("62701 or maybe 73301", SITES) is None


def test_a_hint_naming_no_site_matches_nothing():
    assert match_site("the downtown project", SITES) is None
    assert match_site("", SITES) is None


def test_no_sites_matches_nothing():
    assert match_site("62701", []) is None
