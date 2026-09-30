from fastapi.testclient import TestClient

from main import app

ALLOWED = "http://localhost:5173"


def _preflight(origin: str):
    return TestClient(app).options(
        "/v1/review",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_preflight_from_the_allowed_origin_is_accepted():
    response = _preflight(ALLOWED)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_preflight_from_another_origin_is_rejected():
    response = _preflight("http://evil.example")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
