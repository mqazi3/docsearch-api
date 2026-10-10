import hashlib
import logging
import uuid
from pathlib import Path

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin, require_reader
from app.config import get_settings
from app.db import get_db
from app.jobs import IngestionQueue, get_ingestion_queue
from app.models import Chunk, Document, DocumentStatus
from app.schemas import ChunkList, ChunkOut, DocumentList, DocumentOut
from app.storage import LocalStorage, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

READ_CHUNK_BYTES = 1024 * 1024  # read uploads 1 MB at a time


def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload, stopping as soon as it exceeds the size limit."""
    buffer = bytearray()
    while chunk := file.file.read(READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB limit",
            )
    return bytes(buffer)


def _detect_content_type(filename: str, data: bytes) -> str:
    """Decide the type from the file itself, not the client's Content-Type header."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix in {".txt", ".md"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/markdown" if suffix == ".md" else "text/plain"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Only PDF, .txt, and .md files are supported",
    )


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"description": "Duplicate upload: returns the existing document"}},
    dependencies=[Depends(require_admin)],
)
def upload_document(
    file: UploadFile,
    response: Response,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    ingestion: IngestionQueue = Depends(get_ingestion_queue),
) -> Document:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing filename")
    filename = Path(file.filename).name[:255]

    data = _read_limited(file, get_settings().max_upload_mb * 1024 * 1024)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    content_type = _detect_content_type(filename, data)
    sha256 = hashlib.sha256(data).hexdigest()

    existing = db.scalar(select(Document).where(Document.sha256 == sha256))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing

    # Content-addressed key: identical bytes always map to the same file.
    storage_key = f"{sha256}{Path(filename).suffix.lower()}"
    storage.save(storage_key, data)

    document = Document(
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256,
        storage_path=storage_key,
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        # Two identical uploads raced; the unique constraint let exactly one win.
        db.rollback()
        response.status_code = status.HTTP_200_OK
        return db.scalar(select(Document).where(Document.sha256 == sha256))

    db.refresh(document)
    try:
        ingestion.enqueue_ingestion(document.id)
    except redis.RedisError:
        # The file and row are safe; the document stays "pending" until reprocessed.
        logger.exception("Could not queue document %s for ingestion", document.id)
    return document


@router.get("", response_model=DocumentList, dependencies=[Depends(require_reader)])
def list_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> DocumentList:
    total = db.scalar(select(func.count()).select_from(Document))
    documents = db.scalars(
        select(Document)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return DocumentList(
        items=[DocumentOut.model_validate(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentOut, dependencies=[Depends(require_reader)])
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def reprocess_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    ingestion: IngestionQueue = Depends(get_ingestion_queue),
) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is already processing"
        )

    document.status = DocumentStatus.PENDING
    document.error = None
    db.commit()
    db.refresh(document)

    try:
        ingestion.enqueue_ingestion(document.id)
    except redis.RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion queue unavailable; try again shortly",
        ) from exc
    return document


@router.get(
    "/{document_id}/chunks", response_model=ChunkList, dependencies=[Depends(require_reader)]
)
def list_chunks(
    document_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ChunkList:
    if db.get(Document, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    total = db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    chunks = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return ChunkList(
        items=[ChunkOut.model_validate(c) for c in chunks],
        total=total,
        limit=limit,
        offset=offset,
    )
