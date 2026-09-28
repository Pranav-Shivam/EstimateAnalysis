import subprocess
import sys
from pathlib import Path

import pytest

from core.config.settings import Settings
from core.graph.client import GraphClient, GraphQueryFailed, GraphUnavailable, get_graph_namespace


def test_read_returns_rows_as_dicts(graph_client):
    assert graph_client.read("RETURN $n AS n", n=7) == [{"n": 7}]


def test_write_then_read_round_trips_inside_the_test_namespace(graph_client, graph_ns):
    graph_client.write("CREATE (:Probe {ns: $ns, id: 'p1'})", ns=graph_ns)

    rows = graph_client.read("MATCH (p:Probe {ns: $ns}) RETURN p.id AS id", ns=graph_ns)

    assert rows == [{"id": "p1"}]


def test_a_cypher_error_raises_graph_query_failed(graph_client):
    with pytest.raises(GraphQueryFailed):
        graph_client.read("THIS IS NOT CYPHER")


def test_an_unreachable_server_raises_graph_unavailable():
    client = GraphClient("bolt://localhost:1", "neo4j", "x")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()


def test_a_wrong_password_raises_graph_unavailable(graph_client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    client = GraphClient(settings.neo4j_uri, settings.neo4j_user, "definitely-wrong")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()


def test_graph_ns_sets_the_env_var_get_graph_namespace_reads(graph_ns):
    assert get_graph_namespace() == graph_ns


def test_a_completed_tests_graph_ns_teardown_deletes_its_namespace_nodes(graph_client, tmp_path):
    """Runs a throwaway test in a child pytest process so the real graph_ns fixture teardown executes
    (not a copy of its query), then confirms from here that the namespace it used is empty afterward."""
    backend_dir = Path(__file__).resolve().parents[2]
    probe_file = backend_dir / "tests" / "core" / "_teardown_probe_tmp.py"
    ns_capture_file = tmp_path / "ns.txt"
    probe_file.write_text(
        "def test_probe(graph_client, graph_ns):\n"
        "    graph_client.write(\"CREATE (:Probe {ns: $ns, id: 'teardown-probe'})\", ns=graph_ns)\n"
        f"    open(r'{ns_capture_file}', 'w').write(graph_ns)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe_file), "-v"],
            cwd=backend_dir, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        probed_ns = ns_capture_file.read_text().strip()
        rows = graph_client.read("MATCH (n {ns: $ns}) RETURN n", ns=probed_ns)

        assert rows == []
    finally:
        probe_file.unlink(missing_ok=True)
