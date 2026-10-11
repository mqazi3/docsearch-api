from app.config import Settings, get_settings
from app.main import app


def test_landing_page_needs_no_api_key(anon_client):
    response = anon_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DocSearch" in response.text


def test_landing_page_embeds_public_demo_key(anon_client):
    app.dependency_overrides[get_settings] = lambda: Settings(public_demo_key="dsk_public_demo")
    response = anon_client.get("/")
    assert 'const DEMO_KEY = "dsk_public_demo";' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_landing_page_without_demo_key_disables_demo(anon_client):
    for missing in (None, ""):
        app.dependency_overrides[get_settings] = lambda value=missing: Settings(
            public_demo_key=value
        )
        response = anon_client.get("/")
        assert "const DEMO_KEY = null;" in response.text


def test_landing_page_is_not_in_api_docs(anon_client):
    paths = anon_client.get("/openapi.json").json()["paths"]
    assert "/" not in paths


def test_ask_docs_example_has_no_placeholder_document_ids(anon_client):
    schemas = anon_client.get("/openapi.json").json()["components"]["schemas"]
    example = schemas["AskRequest"]["examples"][0]
    assert "document_ids" not in example
    assert example["question"]
