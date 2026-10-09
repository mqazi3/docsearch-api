import hashlib
import uuid
from pathlib import Path

from app.config import get_settings

PDF_BYTES = b"%PDF-1.4\n% minimal fake PDF used only for upload tests\n"


def upload(client, filename, data, content_type="application/octet-stream"):
    return client.post("/documents", files={"file": (filename, data, content_type)})


def test_upload_text_document_is_accepted(client):
    data = b"AC-1 Policy and Procedures: develop and document an access control policy."
    response = upload(client, "policy.txt", data, "text/plain")

    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "policy.txt"
    assert body["status"] == "pending"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(data)
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert "storage_path" not in body


def test_upload_saves_file_to_storage(client):
    response = upload(client, "sp800-53.pdf", PDF_BYTES, "application/pdf")

    assert response.status_code == 202
    stored = Path(get_settings().upload_dir) / f"{response.json()['sha256']}.pdf"
    assert stored.read_bytes() == PDF_BYTES


def test_duplicate_upload_returns_existing_document(client):
    first = upload(client, "a.txt", b"identical bytes")
    second = upload(client, "renamed.txt", b"identical bytes")

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert client.get("/documents").json()["total"] == 1


def test_rejects_unsupported_extension(client):
    assert upload(client, "program.exe", b"MZ\x90\x00").status_code == 415


def test_rejects_pdf_without_pdf_signature(client):
    assert upload(client, "fake.pdf", b"this is not a pdf").status_code == 415


def test_rejects_text_file_that_is_not_utf8(client):
    assert upload(client, "binary.txt", b"\xff\xfe\x00\x01").status_code == 415


def test_rejects_empty_file(client):
    assert upload(client, "empty.txt", b"").status_code == 400


def test_rejects_file_over_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    response = upload(client, "big.txt", b"a" * (1024 * 1024 + 1))
    assert response.status_code == 413


def test_get_document_by_id(client):
    created = upload(client, "notes.md", b"# Notes").json()

    response = client.get(f"/documents/{created['id']}")

    assert response.status_code == 200
    assert response.json()["content_type"] == "text/markdown"


def test_get_unknown_document_returns_404(client):
    assert client.get(f"/documents/{uuid.uuid4()}").status_code == 404


def test_get_document_with_invalid_id_returns_422(client):
    assert client.get("/documents/not-a-uuid").status_code == 422


def test_list_documents_paginates(client):
    for i in range(3):
        upload(client, f"doc{i}.txt", f"document number {i}".encode())

    first_page = client.get("/documents", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/documents", params={"limit": 2, "offset": 2}).json()

    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    ids = {d["id"] for d in first_page["items"] + second_page["items"]}
    assert len(ids) == 3
