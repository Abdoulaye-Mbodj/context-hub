import json
import os
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DEMO_MODE"] = "true"
os.environ["CORS_ORIGINS"] = "http://testserver"
os.environ["APP_SECRET_KEY"] = "test-only-secret-key-with-at-least-32-characters"

from fastapi.testclient import TestClient

from app.connectors import GOOGLE_SCOPES
from app.main import app
from app.source_apps import _drive_list

ROOT_DIR = Path(__file__).resolve().parents[1]


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


def test_google_connector_configuration_is_encrypted_and_masked():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/connectors/google/configure",
            json={
                "client_id": "123456789.apps.googleusercontent.com",
                "client_secret": "GOCSPX-test-secret-value",
            },
        )
        assert response.status_code == 200
        connector = response.json()
        assert connector["status"] == "configured"
        assert connector["configured"] is True
        assert "client_secret" not in connector["configuration"]
        assert connector["configuration"]["redirect_uri"].endswith("/api/v1/connectors/google/callback")

        listed = client.get("/api/v1/connectors").json()
        google = next(item for item in listed if item["provider"] == "google")
        assert google["configuration"]["client_id"] == "123456789.apps.googleusercontent.com"
        assert "GOCSPX" not in str(google)


def test_browser_extension_is_downloadable():
    with TestClient(app) as client:
        response = client.get("/browser-extension.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(response.content)) as archive:
            assert "browser-extension/manifest.json" in archive.namelist()
            assert "browser-extension/sidepanel.html" in archive.namelist()
            assert "browser-extension/hub-bridge.js" not in archive.namelist()
            assert "browser-extension/workspace.css" in archive.namelist()
            manifest = json.loads(archive.read("browser-extension/manifest.json"))
            assert manifest["version"] == "0.5.0"


def test_connected_source_search_endpoint_is_available():
    with TestClient(app) as client:
        response = client.get("/api/v1/resources/search", params={"source": "gmail", "q": "test"})
        assert response.status_code in {400, 502}
        assert "Google" in response.json()["detail"]


def test_context_ui_uses_neutral_contexts_and_source_picker():
    page = (ROOT_DIR / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'name="context_type"' not in page
    assert 'data-resource-source="gmail"' in page
    assert 'id="resource-search-results"' in page


def test_extension_context_creation_keeps_form_reference_across_awaits():
    script = (ROOT_DIR / "browser-extension" / "sidepanel.js").read_text(encoding="utf-8")
    assert "const form = event.currentTarget" in script
    assert "event.currentTarget.reset" not in script


def test_hub_navigation_is_never_intercepted_by_extension():
    page = (ROOT_DIR / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT_DIR / "app" / "static" / "assets" / "app.js").read_text(encoding="utf-8")
    worker = (ROOT_DIR / "browser-extension" / "service-worker.js").read_text(encoding="utf-8")
    assert "source-app-button" in page
    assert "embedded-browser" not in page
    assert "open-extension-mode" not in page
    assert "context-hub-open-app" not in script
    assert '"context-hub-web"' in worker
    assert "unregisterLegacyHubScript" in worker
    assert "NAVIGATE_APP_IN_PLACE" not in worker


def test_contexts_can_be_deleted_in_bulk():
    with TestClient(app) as client:
        ids = []
        for suffix in ("A", "B"):
            response = client.post(
                "/api/v1/contexts",
                json={"title": f"Contexte temporaire {suffix}", "context_type": "project"},
            )
            assert response.status_code == 201
            ids.append(response.json()["id"])
        deleted = client.post("/api/v1/contexts/bulk-delete", json={"ids": ids})
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": 2}
        remaining = {context["id"] for context in client.get("/api/v1/contexts").json()}
        assert not remaining.intersection(ids)


def test_chromium_is_fully_removed_from_runtime():
    compose = (ROOT_DIR / "compose.yaml").read_text(encoding="utf-8")
    main = (ROOT_DIR / "app" / "main.py").read_text(encoding="utf-8")
    assert "chromium" not in compose.lower()
    assert "browser_router" not in main
    assert not (ROOT_DIR / "app" / "browser.py").exists()


def test_native_application_routes_require_connected_sources():
    with TestClient(app) as client:
        google = client.get("/api/v1/apps/gmail/items")
        assert google.status_code in {400, 502}
        assert "Google" in google.json()["detail"] or "gmail" in google.json()["detail"].lower()


def test_native_google_scopes_allow_crud_and_chat_messages():
    assert "https://www.googleapis.com/auth/gmail.modify" in GOOGLE_SCOPES
    assert "https://www.googleapis.com/auth/drive" in GOOGLE_SCOPES
    assert "https://www.googleapis.com/auth/calendar" in GOOGLE_SCOPES
    assert "https://www.googleapis.com/auth/chat.messages" in GOOGLE_SCOPES


def test_drive_listing_includes_shared_drives_and_shared_with_me():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"files": []}

    class FakeClient:
        params = None

        def get(self, _url, params):
            self.params = params
            return FakeResponse()

    client = FakeClient()
    assert _drive_list(client, "", 20, "shared") == []
    assert client.params["corpora"] == "user"
    assert client.params["includeItemsFromAllDrives"] == "true"
    assert client.params["supportsAllDrives"] == "true"
    assert "sharedWithMe" in client.params["q"]


def test_native_ui_has_preview_and_no_embedded_source_application():
    page = (ROOT_DIR / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT_DIR / "app" / "static" / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="resource-preview"' in page
    assert "Conversation entière" in script
    assert "Ce message uniquement" in script
    assert "<iframe" not in page.lower()
    assert "window.location =" not in script
