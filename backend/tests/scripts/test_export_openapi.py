import json

from export_openapi import write_openapi


def test_write_openapi_emits_the_phase_7_paths(tmp_path):
    out = tmp_path / "openapi.json"

    write_openapi(out)

    paths = json.loads(out.read_text(encoding="utf-8"))["paths"]
    assert "/v1/quotes" in paths
    assert "/v1/quotes/{quote_request_id}" in paths
    assert "/v1/metrics" in paths
    assert "/v1/review" in paths
