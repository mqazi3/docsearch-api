import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.embeddings import Embedder
from app.models import Chunk, Document

logger = logging.getLogger(__name__)

RRF_K = 60  # standard constant from the original RRF paper
CANDIDATES_PER_METHOD = 50
QUERY_EMBEDDING_TTL_SECONDS = 24 * 60 * 60


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    VECTOR = "vector"
    KEYWORD = "keyword"


@dataclass
class SearchHit:
    chunk_id: int
    score: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None


def reciprocal_rank_fusion(
    vector_ids: list[int], keyword_ids: list[int], k: int = RRF_K
) -> list[SearchHit]:
    """Merge two rankings. Each list contributes 1 / (k + rank) for every item it contains."""
    hits: dict[int, SearchHit] = {}
    for rank, chunk_id in enumerate(vector_ids, start=1):
        hit = hits.setdefault(chunk_id, SearchHit(chunk_id=chunk_id))
        hit.vector_rank = rank
        hit.score += 1 / (k + rank)
    for rank, chunk_id in enumerate(keyword_ids, start=1):
        hit = hits.setdefault(chunk_id, SearchHit(chunk_id=chunk_id))
        hit.keyword_rank = rank
        hit.score += 1 / (k + rank)
    # Ties broken by chunk_id so results are deterministic.
    return sorted(hits.values(), key=lambda h: (-h.score, h.chunk_id))


def vector_search(
    db: Session, query_vector: list[float], limit: int, document_ids: list[uuid.UUID] | None
) -> list[int]:
    distance = Chunk.embedding.cosine_distance(query_vector)
    stmt = select(Chunk.id).where(Chunk.embedding.is_not(None)).order_by(distance).limit(limit)
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    return list(db.scalars(stmt))


def keyword_search(
    db: Session, query: str, limit: int, document_ids: list[uuid.UUID] | None
) -> list[int]:
    # websearch_to_tsquery accepts user-style input ("quoted phrases", -exclusions)
    # and never raises a syntax error on arbitrary text.
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(Chunk.content_tsv, tsquery)
    stmt = (
        select(Chunk.id)
        .where(Chunk.content_tsv.op("@@")(tsquery))
        .order_by(rank.desc(), Chunk.id)
        .limit(limit)
    )
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    return list(db.scalars(stmt))


def embed_query(query: str, embedder: Embedder, cache: redis.Redis, namespace: str) -> list[float]:
    """Embed a query, caching the vector in Redis. Falls back to the API if Redis is down."""
    key = "query-embedding:" + hashlib.sha256(f"{namespace}\x00{query}".encode()).hexdigest()
    try:
        cached = cache.get(key)
        if cached is not None:
            return json.loads(cached)
    except redis.RedisError:
        logger.warning("Query-embedding cache unavailable; calling the embedder directly")

    vector = [float(x) for x in embedder.embed([query])[0]]
    try:
        cache.set(key, json.dumps(vector), ex=QUERY_EMBEDDING_TTL_SECONDS)
    except redis.RedisError:
        logger.warning("Could not store query embedding in cache")
    return vector


def run_search(
    db: Session,
    *,
    query: str,
    mode: SearchMode,
    limit: int,
    document_ids: list[uuid.UUID] | None,
    embedder: Embedder,
    cache: redis.Redis,
    cache_namespace: str,
) -> list[tuple[SearchHit, Chunk, Document]]:
    vector_ids: list[int] = []
    keyword_ids: list[int] = []

    if mode in (SearchMode.HYBRID, SearchMode.VECTOR):
        query_vector = embed_query(query, embedder, cache, cache_namespace)
        vector_ids = vector_search(db, query_vector, CANDIDATES_PER_METHOD, document_ids)
    if mode in (SearchMode.HYBRID, SearchMode.KEYWORD):
        keyword_ids = keyword_search(db, query, CANDIDATES_PER_METHOD, document_ids)

    # With a single mode, RRF over one list simply preserves its order: one code path.
    hits = reciprocal_rank_fusion(vector_ids, keyword_ids)[:limit]
    if not hits:
        return []

    rows = db.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_([h.chunk_id for h in hits]))
        # Don't haul 1,536 floats per row back just to display text.
        .options(defer(Chunk.embedding), defer(Chunk.content_tsv))
    ).all()
    by_id = {chunk.id: (chunk, document) for chunk, document in rows}
    return [(hit, *by_id[hit.chunk_id]) for hit in hits if hit.chunk_id in by_id]
