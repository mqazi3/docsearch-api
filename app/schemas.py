import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    error: str | None
    page_count: int | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    page_number: int | None
    token_count: int


class ChunkList(BaseModel):
    items: list[ChunkOut]
    total: int
    limit: int
    offset: int
