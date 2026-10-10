import time
import uuid
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Session

from app.answering import (
    INSTRUCTIONS,
    REFUSAL,
    AnswerGenerator,
    Generation,
    Source,
    build_prompt,
    extract_citations,
    is_refusal,
    select_sources,
)
from app.config import get_settings
from app.embeddings import Embedder
from app.search import SearchMode, embedding_namespace, run_search


@dataclass
class AnswerResult:
    answer: str
    refused: bool
    sources: list[Source]
    cited: list[Source]
    invalid_citations: list[int]
    generation: Generation | None
    retrieval_ms: float
    generation_ms: float


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def answer_question(
    db: Session,
    *,
    question: str,
    k: int,
    document_ids: list[uuid.UUID] | None,
    embedder: Embedder,
    cache: redis.Redis,
    generator: AnswerGenerator,
) -> AnswerResult:
    """Retrieve, generate, and validate citations. Raises GenerationError if the model fails."""
    started = time.perf_counter()
    rows = run_search(
        db,
        query=question,
        mode=SearchMode.HYBRID,
        limit=k,
        document_ids=document_ids,
        embedder=embedder,
        cache=cache,
        cache_namespace=embedding_namespace(),
    )
    sources = select_sources(rows, get_settings().ask_max_context_tokens)
    retrieval_ms = _elapsed_ms(started)

    if not sources:
        # Nothing to ground an answer in: refuse without paying for a model call.
        return AnswerResult(REFUSAL, True, [], [], [], None, retrieval_ms, 0.0)

    started = time.perf_counter()
    generation = generator.generate(INSTRUCTIONS, build_prompt(question, sources))
    generation_ms = _elapsed_ms(started)

    refused = is_refusal(generation.text)
    cited, invalid = ([], []) if refused else extract_citations(generation.text, sources)
    return AnswerResult(
        generation.text, refused, sources, cited, invalid, generation, retrieval_ms, generation_ms
    )
