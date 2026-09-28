from types import SimpleNamespace

from app.graph.helper import build_community_stats, match_site, member_hash

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


def _row(sku_id, community, *, category="Cat-A", discontinued=False, family="Fam", has_requirements=False, name=None):
    return {"sku_id": sku_id, "name": name or f"name {sku_id}", "category": category, "discontinued": discontinued,
            "community": community, "family": family, "has_requirements": has_requirements}


def test_member_hash_ignores_order_and_changes_with_membership():
    assert member_hash(["b", "a", "c"]) == member_hash(["c", "a", "b"])
    assert member_hash(["a", "b"]) != member_hash(["a", "b", "c"])
    assert len(member_hash(["a"])) == 64


def test_community_stats_summarise_each_community():
    rows = [
        _row("S1", 7, category="Cat-A", family="Fam One", has_requirements=True),
        _row("S2", 7, category="Cat-A", family="Fam One", discontinued=True),
        _row("S3", 7, category="Cat-B", family="Fam Two"),
        _row("S9", 3, category="Cat-B", family="Fam Nine"),
    ]

    stats = build_community_stats(rows)

    assert [s.community_id for s in stats] == [3, 7]
    seven = stats[1]
    assert seven.size == 3
    assert seven.families == ("Fam One", "Fam Two")
    assert (seven.dominant_category, seven.dominant_category_share) == ("Cat-A", 0.667)
    assert seven.discontinued_count == 1 and seven.requirement_count == 1
    assert seven.example_sku_ids == ("S1", "S2", "S3")
    assert seven.member_names == ("name S1", "name S2", "name S3")
    assert seven.member_hash == member_hash(["S1", "S2", "S3"])


def test_dominant_category_ties_break_alphabetically_and_missing_families_are_skipped():
    rows = [_row("S1", 1, category="Cat-B", family=None), _row("S2", 1, category="Cat-A", family=None)]

    stat = build_community_stats(rows)[0]

    assert stat.dominant_category == "Cat-A"
    assert stat.families == ()


def test_example_skus_and_member_names_are_capped_and_sorted():
    rows = [_row(f"S{i:02d}", 1) for i in range(40, 0, -1)]

    stat = build_community_stats(rows)[0]

    assert stat.size == 40
    assert stat.example_sku_ids == ("S01", "S02", "S03", "S04", "S05")
    assert len(stat.member_names) == 30
