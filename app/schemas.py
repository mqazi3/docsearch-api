import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class SearchResult(BaseModel):
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    score: float
    vector_rank: int | None
    keyword_rank: int | None


class SearchResponse(BaseModel):
    query: str
    mode: str
    took_ms: float
    results: list[SearchResult]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(8, ge=1, le=20, description="Chunks to retrieve")
    document_ids: list[uuid.UUID] | None = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value.strip()


class Citation(BaseModel):
    number: int
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    excerpt: str


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class AskResponse(BaseModel):
    question: str
    answer: str
    insufficient_context: bool
    citations: list[Citation]
    unsupported_citations: list[int]
    model: str | None
    usage: TokenUsage | None
    retrieval_ms: float
    generation_ms: float
