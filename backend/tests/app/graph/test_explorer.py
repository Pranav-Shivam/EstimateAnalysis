from app.graph.constant import NEIGHBOR_LIMIT
from app.graph.service import neighborhood


class HubClient:
    """A graph whose one node has more neighbors than the explorer returns."""

    def __init__(self, neighbors: int) -> None:
        self._neighbors = neighbors

    def read(self, query: str, **params) -> list[dict]:
        if "RETURN m.id" in query:
            return [
                {"id": f"S{i}", "label": "SKU", "name": f"S{i}", "community": None, "type": "IN_FAMILY",
                 "source": f"S{i}", "target": "HUB"}
                for i in range(min(params["fetch"], self._neighbors))
            ]
        return [{"id": "HUB", "label": "ProductFamily", "name": "Hub", "community": None}]


def test_a_hub_over_the_limit_is_cut_and_flagged():
    result = neighborhood(HubClient(NEIGHBOR_LIMIT + 40), "ns", "HUB")
    assert len(result["nodes"]) == NEIGHBOR_LIMIT and result["truncated"] is True


def test_a_node_at_the_limit_is_not_flagged():
    result = neighborhood(HubClient(NEIGHBOR_LIMIT), "ns", "HUB")
    assert len(result["nodes"]) == NEIGHBOR_LIMIT and result["truncated"] is False
