import hashlib
import io
import uuid

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.db import SessionLocal
from app.embeddings import FakeEmbedder
from app.ingestion.pipeline import ingest_document
from app.models import EMBEDDING_DIM, Chunk, Document, DocumentStatus
from app.storage import get_storage


class FailingEmbedder:
    def embed(self, texts):
        raise ConnectionError("embedding API unavailable")


def make_document(data: bytes, filename="doc.txt", content_type="text/plain") -> uuid.UUID:
    sha256 = hashlib.sha256(data).hexdigest()
    key = f"{sha256}.{filename.rsplit('.', 1)[-1]}"
    get_storage().save(key, data)
    with SessionLocal() as db:
        document = Document(
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
            sha256=sha256,
            storage_path=key,
        )
        db.add(document)
        db.commit()
        return document.id


def get_document(document_id) -> Document:
    with SessionLocal() as db:
        return db.get(Document, document_id)


def count_chunks(document_id) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )


def ingest(document_id, embedder=None):
    ingest_document(document_id, SessionLocal, get_storage(), embedder or FakeEmbedder())


def test_ingests_text_document():
    document_id = make_document(b"Access control policy and procedures. " * 50)

    ingest(document_id)

    document = get_document(document_id)
    assert document.status == DocumentStatus.READY
    assert document.error is None
    assert document.page_count == 1
    assert document.chunk_count >= 1
    with SessionLocal() as db:
        chunks = db.scalars(select(Chunk).where(Chunk.document_id == document_id)).all()
    assert len(chunks) == document.chunk_count
    assert all(len(c.embedding) == EMBEDDING_DIM for c in chunks)


def test_long_document_is_split_within_token_limit():
    document_id = make_document(" ".join(f"word{i}" for i in range(3000)).encode())

    ingest(document_id)

    document = get_document(document_id)
    assert document.chunk_count > 1
    with SessionLocal() as db:
        token_counts = db.scalars(
            select(Chunk.token_count).where(Chunk.document_id == document_id)
        ).all()
    assert max(token_counts) <= 500


def test_reingesting_replaces_chunks_instead_of_duplicating():
    document_id = make_document(b"Least privilege. " * 400)
    ingest(document_id)
    first_count = count_chunks(document_id)

    with SessionLocal() as db:
        db.get(Document, document_id).status = DocumentStatus.PENDING
        db.commit()
    ingest(document_id)

    assert count_chunks(document_id) == first_count


def test_transient_failure_marks_failed_and_reraises_for_retry():
    document_id = make_document(b"Incident response plan.")

    with pytest.raises(ConnectionError):
        ingest(document_id, FailingEmbedder())

    document = get_document(document_id)
    assert document.status == DocumentStatus.FAILED
    assert "ConnectionError" in document.error
    assert count_chunks(document_id) == 0


def test_pdf_without_text_fails_permanently_without_raising():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    document_id = make_document(buffer.getvalue(), "blank.pdf", "application/pdf")

    ingest(document_id)  # must not raise: retrying a textless PDF is pointless

    document = get_document(document_id)
    assert document.status == DocumentStatus.FAILED
    assert "No extractable text" in document.error


def test_ready_document_is_skipped():
    document_id = make_document(b"Configuration management.")
    ingest(document_id)

    ingest(document_id, FailingEmbedder())  # would raise if it actually re-ran

    assert get_document(document_id).status == DocumentStatus.READY


def test_missing_document_is_skipped():
    ingest(uuid.uuid4())  # deleted before the worker got to it: no error
