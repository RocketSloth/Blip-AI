from fastapi.testclient import TestClient

from app.main import app, reset_demo_state


def setup_function() -> None:
    reset_demo_state()


def test_homepage_smoke() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Priority Queue" in response.text


def test_seeded_demo_data() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert "Escalated invoice queue" in response.text
    assert "Finance Ops" in response.text


def test_primary_workflow() -> None:
    client = TestClient(app)
    response = client.post(
        "/records/1/act",
        data={"note": "Called vendor and grouped invoices.", "action_taken": "Escalated"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Called vendor and grouped invoices." in response.text
    assert "Escalated" in response.text
