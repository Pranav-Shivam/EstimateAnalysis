import pytest

from app.retrieval.router import Route, route_question


@pytest.mark.parametrize("question, route, rule, entity", [
    ("which product groups have the most discontinued items", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("Which PRODUCT GROUPS are most exposed", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("give me the biggest groups across the catalog", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("something like a 3 ton condenser", Route.VECTOR, "similarity_phrasing", None),
    ("similar to SKU-0001", Route.VECTOR, "similarity_phrasing", "SKU-0001"),
    ("an alternative to sku-0542", Route.VECTOR, "similarity_phrasing", "SKU-0542"),
    ("what is SKU-0542 replaced by", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "SKU-0542"),
    ("what parts does sku-0601 require", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "SKU-0601"),
    ("what does CTR-0004 cover", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "CTR-0004"),
    ("how is CUST-0001 connected to its contracts", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "CUST-0001"),
    ("price of SKU-0001", Route.SQL, "id_lookup", "SKU-0001"),
    ("CUST-0001 details", Route.SQL, "id_lookup", "CUST-0001"),
    ("show CTR-0004", Route.SQL, "id_lookup", "CTR-0004"),
    ("info on SITE-0001", Route.GRAPH_LOCAL, "non_sql_id", "SITE-0001"),
    ("what is FAM-0003", Route.GRAPH_LOCAL, "non_sql_id", "FAM-0003"),
    ("brass elbow 1 in", Route.SQL, "name_search", None),
    ("", Route.SQL, "name_search", None),
    ("   ", Route.SQL, "name_search", None),
])
def test_questions_are_routed_by_rule(question, route, rule, entity):
    decision = route_question(question)

    assert (decision.route, decision.rule, decision.entity_id) == (route, rule, entity)


def test_portfolio_phrasing_beats_similarity_and_ids():
    """(Review Focus) A question matching several rules takes the first in precedence order."""
    decision = route_question("which product groups are similar to SKU-0001")

    assert decision.route is Route.GRAPH_GLOBAL and decision.entity_id == "SKU-0001"


def test_similarity_beats_relationship_phrasing():
    decision = route_question("an alternative to SKU-0001 that replaces it")

    assert decision.route is Route.VECTOR


def test_ids_are_uppercased_and_letter_ids_are_recognised():
    """(Review Focus) Lowercase ids and the test-data style ids with letters."""
    assert route_question("price of sku-e-a1").entity_id == "SKU-E-A1"
    assert route_question("price of Sku-0001, please").entity_id == "SKU-0001"


def test_an_id_embedded_in_a_longer_word_is_not_an_id():
    assert route_question("the SKU-0001x thing").entity_id == "SKU-0001X"
    assert route_question("MYSKU-0001").entity_id is None


def test_unicode_text_around_an_id_still_routes():
    decision = route_question("prix de SKU-0001 s'il vous plaît, très vite")

    assert (decision.route, decision.entity_id) == (Route.SQL, "SKU-0001")
