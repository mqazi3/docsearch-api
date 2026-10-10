import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.embeddings import Embedder
from app.ingestion.chunking import chunk_pages
from app.ingestion.extract import IngestionError, extract_pages
from app.models import Chunk, Document, DocumentStatus
from app.storage import LocalStorage

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 1000


def ingest_document(
    document_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    storage: LocalStorage,
    embedder: Embedder,
) -> None:
    """Extract, chunk, embed, and store one document. Safe to run more than once."""
    with session_factory() as db:
        document = db.get(Document, document_id)
        if document is None:
            logger.warning("Document %s no longer exists; skipping", document_id)
            return
        if document.status == DocumentStatus.READY:
            logger.info("Document %s is already ingested; skipping", document_id)
            return

        document.status = DocumentStatus.PROCESSING
        document.error = None
        db.commit()

        try:
            settings = get_settings()
            pages = extract_pages(storage.read(document.storage_path), document.content_type)
            chunks = chunk_pages(pages, settings.chunk_size_tokens, settings.chunk_overlap_tokens)
            if not chunks:
                raise IngestionError("No extractable text found (the PDF may be scanned images)")

            vectors = embedder.embed([chunk.content for chunk in chunks])

            # Replace chunks from any earlier partial attempt, then write everything
            # in ONE transaction: the document ends up with all of its chunks or none.
            db.execute(delete(Chunk).where(Chunk.document_id == document.id))
            db.add_all(
                Chunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    token_count=chunk.token_count,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            document.page_count = len(pages)
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.READY
            db.commit()
            logger.info("Ingested %s: %d pages, %d chunks", document_id, len(pages), len(chunks))

        except IngestionError as exc:
            # Permanent: the document itself is the problem. Record it; don't retry.
            _mark_failed(db, document, str(exc))
        except Exception as exc:
            # Transient (network, API, rate limit): record it, then re-raise so the queue retries.
            _mark_failed(db, document, f"{type(exc).__name__}: {exc}")
            raise


def _mark_failed(db: Session, document: Document, message: str) -> None:
    db.rollback()
    document.status = DocumentStatus.FAILED
    document.error = message[:MAX_ERROR_LENGTH]
    db.commit()
