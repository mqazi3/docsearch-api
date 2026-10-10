import logging

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.answering import AnswerGenerator, GenerationError, get_generator
from app.cache import get_redis
from app.db import get_db
from app.embeddings import Embedder, get_embedder
from app.qa import answer_question
from app.ratelimit import ask_rate_limit
from app.schemas import AskRequest, AskResponse, Citation, TokenUsage
from app.search import missing_document_ids

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Answers"])

EXCERPT_CHARS = 300


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(ask_rate_limit)])
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

    try:
        result = answer_question(
            db,
            question=body.question,
            k=body.k,
            document_ids=body.document_ids,
            embedder=embedder,
            cache=cache,
            generator=generator,
        )
    except GenerationError as exc:
        logger.exception("Answer generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Answer generation failed; try again shortly",
        ) from exc

    generation = result.generation
    logger.info(
        "ask sources=%d cited=%d invalid=%d refused=%s tokens_in=%d tokens_out=%d "
        "retrieval_ms=%.1f generation_ms=%.1f",
        len(result.sources),
        len(result.cited),
        len(result.invalid_citations),
        result.refused,
        generation.input_tokens if generation else 0,
        generation.output_tokens if generation else 0,
        result.retrieval_ms,
        result.generation_ms,
    )

    return AskResponse(
        question=body.question,
        answer=result.answer,
        insufficient_context=result.refused,
        citations=[
            Citation(
                number=s.number,
                chunk_id=s.chunk_id,
                document_id=s.document_id,
                filename=s.filename,
                page_number=s.page_number,
                excerpt=s.content[:EXCERPT_CHARS],
            )
            for s in result.cited
        ],
        unsupported_citations=result.invalid_citations,
        model=generation.model if generation else None,
        usage=(
            TokenUsage(input_tokens=generation.input_tokens, output_tokens=generation.output_tokens)
            if generation
            else None
        ),
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
    )
