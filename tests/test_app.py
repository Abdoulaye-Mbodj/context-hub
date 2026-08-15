import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DEMO_MODE"] = "true"
os.environ["CORS_ORIGINS"] = "http://testserver"

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_seeded_dashboard():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        dashboard = client.get("/api/v1/dashboard").json()
        assert dashboard["total_contexts"] >= 4
        assert dashboard["linked_resources"] >= 10
        assert set(dashboard["by_source"]) == {"gmail", "chat", "drive", "calendar", "odoo"}


def test_context_lifecycle_and_reference_deduplication():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/contexts",
            json={
                "title": "Migration ERP Nord",
                "summary": "Contexte de test transverse",
                "context_type": "project",
                "owner_name": "Alice Test",
                "tags": ["ERP", "Nord"],
            },
        )
        assert created.status_code == 201
        context_id = created.json()["id"]

        resource = {
            "source": "drive",
            "external_id": "file-123",
            "title": "Plan de migration",
            "url": "https://drive.google.com/open?id=file-123",
            "resource_type": "document",
        }
        assert client.post(f"/api/v1/contexts/{context_id}/resources", json=resource).status_code == 201
        assert client.post(f"/api/v1/contexts/{context_id}/resources", json=resource).status_code == 409

        search = client.get("/api/v1/contexts", params={"q": "migration"}).json()
        assert any(item["id"] == context_id for item in search)
        detail = client.get(f"/api/v1/contexts/{context_id}").json()
        assert detail["resource_count"] == 1
        assert detail["sources"] == ["drive"]


def test_workspace_and_chat_entrypoints():
    with TestClient(app) as client:
        home = client.post("/integrations/workspace/home", json={})
        assert home.status_code == 200
        assert home.json()["action"]["navigations"][0]["pushCard"]["header"]["title"] == "Context Hub"

        chat = client.post(
            "/integrations/google-chat/events",
            json={"type": "MESSAGE", "message": {"argumentText": "Helios"}},
        )
        assert chat.status_code == 200
        assert chat.json()["cardsV2"]


def test_odoo_smart_link_redirects_existing_context():
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/integrations/odoo/open",
            params={"model": "crm.lead", "record_id": "1842", "title": "Helios"},
        )
        assert response.status_code == 302
        assert "?context=" in response.headers["location"]
