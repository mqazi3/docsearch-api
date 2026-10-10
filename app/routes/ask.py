import logging
import time

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.answering import (
    INSTRUCTIONS,
    REFUSAL,
    AnswerGenerator,
    GenerationError,
    build_prompt,
    extract_citations,
    get_generator,
    is_refusal,
    select_sources,
)
from app.cache import get_redis
from app.config import get_settings
from app.db import get_db
from app.embeddings import Embedder, get_embedder
from app.schemas import AskRequest, AskResponse, Citation, TokenUsage
from app.search import SearchMode, embedding_namespace, missing_document_ids, run_search

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Answers"])

EXCERPT_CHARS = 300


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    cache: redis.Redis = Depends(get_redis),
    generator: AnswerGenerator = Depends(get_generator),
) -> AskResponse:
    missing = missing_document_ids(db, body.document_ids)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown document_ids: {', '.join(str(d) for d in missing)}",
        )
    started = time.perf_counter()
    rows = run_search(
        db,
        query=body.question,
        mode=SearchMode.HYBRID,
        limit=body.k,
        document_ids=body.document_ids,
        embedder=embedder,
        cache=cache,
        cache_namespace=embedding_namespace(),
    )
    sources = select_sources(rows, get_settings().ask_max_context_tokens)
    retrieval_ms = _elapsed_ms(started)

    if not sources:
        # Nothing to ground an answer in: refuse without paying for an LLM call.
        logger.info("ask sources=0 refused_without_model retrieval_ms=%.1f", retrieval_ms)
        return AskResponse(
            question=body.question,
            answer=REFUSAL,
            insufficient_context=True,
            citations=[],
            unsupported_citations=[],
            model=None,
            usage=None,
            retrieval_ms=retrieval_ms,
            generation_ms=0.0,
        )

    started = time.perf_counter()
    try:
        generation = generator.generate(INSTRUCTIONS, build_prompt(body.question, sources))
    except GenerationError as exc:
        logger.exception("Answer generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Answer generation failed; try again shortly",
        ) from exc
    generation_ms = _elapsed_ms(started)

    refused = is_refusal(generation.text)
    cited, invalid = ([], []) if refused else extract_citations(generation.text, sources)
    logger.info(
        "ask sources=%d cited=%d invalid=%d refused=%s tokens_in=%d tokens_out=%d "
        "retrieval_ms=%.1f generation_ms=%.1f",
        len(sources),
        len(cited),
        len(invalid),
        refused,
        generation.input_tokens,
        generation.output_tokens,
        retrieval_ms,
        generation_ms,
    )

    return AskResponse(
        question=body.question,
        answer=generation.text,
        insufficient_context=refused,
        citations=[
            Citation(
                number=s.number,
                chunk_id=s.chunk_id,
                document_id=s.document_id,
                filename=s.filename,
                page_number=s.page_number,
                excerpt=s.content[:EXCERPT_CHARS],
            )
            for s in cited
        ],
        unsupported_citations=invalid,
        model=generation.model,
        usage=TokenUsage(
            input_tokens=generation.input_tokens, output_tokens=generation.output_tokens
        ),
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
    )
