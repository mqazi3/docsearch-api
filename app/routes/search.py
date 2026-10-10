import logging
import time
import uuid

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.cache import get_redis
from app.db import get_db
from app.embeddings import Embedder, get_embedder
from app.schemas import SearchResponse, SearchResult
from app.search import SearchMode, embedding_namespace, missing_document_ids, run_search

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    mode: SearchMode = SearchMode.HYBRID,
    k: int = Query(10, ge=1, le=50, description="Number of results"),
    document_id: list[uuid.UUID] | None = Query(None, description="Limit to these documents"),
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    cache: redis.Redis = Depends(get_redis),
) -> SearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Query must not be blank"
        )

    missing = missing_document_ids(db, document_id)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown document_id: {', '.join(str(d) for d in missing)}",
        )

    started = time.perf_counter()
    rows = run_search(
        db,
        query=query,
        mode=mode,
        limit=k,
        document_ids=document_id,
        embedder=embedder,
        cache=cache,
        cache_namespace=embedding_namespace(),
    )
    took_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info("search mode=%s k=%d results=%d took_ms=%.2f", mode, k, len(rows), took_ms)

    return SearchResponse(
        query=query,
        mode=mode,
        took_ms=took_ms,
        results=[
            SearchResult(
                chunk_id=chunk.id,
                document_id=document.id,
                filename=document.filename,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=round(hit.score, 6),
                vector_rank=hit.vector_rank,
                keyword_rank=hit.keyword_rank,
            )
            for hit, chunk, document in rows
        ],
    )
