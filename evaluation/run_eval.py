"""Evaluate retrieval (and optionally answers) against the labeled question set.

Usage (from the project root, with Docker's db and redis running):
    python -m evaluation.run_eval --label baseline
    python -m evaluation.run_eval --label baseline --answers   # also calls the answer model
"""

import argparse
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.answering import GenerationError, get_generator
from app.cache import redis_client
from app.db import SessionLocal
from app.embeddings import get_embedder
from app.models import Chunk, Document, DocumentStatus
from app.qa import answer_question
from app.search import SearchMode, embed_query, embedding_namespace, run_search
from evaluation.labels import control_pages, find_headings
from evaluation.metrics import first_relevant_rank, hit_at_k, mean, percentile, reciprocal_rank

EVAL_DIR = Path(__file__).parent
QUESTIONS_FILE = EVAL_DIR / "questions.jsonl"
RESULTS_DIR = EVAL_DIR / "results"

SEARCH_LIMIT = 10
K_VALUES = (1, 5, 10)
ANSWER_K = 8

# Pages verified by hand during manual testing (docs/retrieval-notes.md).
# If heading detection disagrees with these, every label would be wrong.
KNOWN_HEADING_PAGES = {
    "03.01.08": 22,
    "03.03.03": 33,
    "03.05.03": 44,
    "03.05.07": 46,
    "03.13.11": 71,
}


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def load_questions() -> list[dict]:
    lines = QUESTIONS_FILE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def pick_document(db, document_id: str | None) -> Document:
    if document_id:
        document = db.get(Document, uuid.UUID(document_id))
        if document is None:
            raise SystemExit(f"Document {document_id} not found")
        return document
    candidates = db.scalars(
        select(Document).where(
            Document.status == DocumentStatus.READY,
            Document.content_type == "application/pdf",
        )
    ).all()
    if len(candidates) != 1:
        names = ", ".join(d.filename for d in candidates) or "none"
        raise SystemExit(f"Expected exactly one ready PDF; found: {names}. Use --document-id.")
    return candidates[0]


def build_labels(db, document: Document) -> dict[str, set[int]]:
    rows = db.execute(
        select(Chunk.page_number, Chunk.chunk_index, Chunk.content)
        .where(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
    ).all()
    headings = find_headings(rows)
    by_control = {h.control: h for h in headings}

    wrong = {
        control: (expected, by_control[control].page if control in by_control else None)
        for control, expected in KNOWN_HEADING_PAGES.items()
        if control not in by_control or by_control[control].page != expected
    }
    if wrong:
        raise SystemExit(f"Heading detection failed sanity check (expected, found): {wrong}")

    print(f"Detected {len(headings)} control headings in {document.filename}")
    return control_pages(headings)


def relevant_pages(question: dict, pages: dict[str, set[int]]) -> set[int]:
    unknown = [c for c in question["controls"] if c not in pages]
    if unknown:
        raise SystemExit(f"{question['id']}: unknown control(s) {unknown}; fix questions.jsonl")
    return set().union(*(pages[c] for c in question["controls"]))


def evaluate_retrieval(db, questions, pages, document_id, repeat):
    embedder = get_embedder()
    namespace = embedding_namespace()

    # Cold query-embedding latency (direct API call), then warm the cache so the
    # search timings below measure retrieval itself.
    embed_ms = []
    for q in questions:
        started = time.perf_counter()
        embedder.embed([q["question"]])
        embed_ms.append(elapsed_ms(started))
        embed_query(q["question"], embedder, redis_client, namespace)

    records = []
    latency = {mode.value: [] for mode in SearchMode}
    for q in questions:
        relevant = relevant_pages(q, pages)
        ranks = {}
        for mode in SearchMode:
            for _ in range(repeat):
                started = time.perf_counter()
                rows = run_search(
                    db,
                    query=q["question"],
                    mode=mode,
                    limit=SEARCH_LIMIT,
                    document_ids=[document_id],
                    embedder=embedder,
                    cache=redis_client,
                    cache_namespace=namespace,
                )
                latency[mode.value].append(elapsed_ms(started))
            ranks[mode.value] = first_relevant_rank(
                [chunk.page_number for _hit, chunk, _doc in rows], relevant
            )
        records.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "relevant_pages": sorted(relevant),
                "ranks": ranks,
            }
        )
    return records, latency, embed_ms


def retrieval_metrics(records: list[dict], mode: str) -> dict:
    ranks = [r["ranks"][mode] for r in records]
    metrics = {"n": len(ranks)}
    for k in K_VALUES:
        metrics[f"hit@{k}"] = round(mean([hit_at_k(r, k) for r in ranks]), 3)
    metrics["mrr@10"] = round(mean([reciprocal_rank(r) for r in ranks]), 3)
    return metrics


def evaluate_answers(db, questions, pages, document_id):
    embedder = get_embedder()
    generator = get_generator()
    records = []
    for q in questions:
        in_scope = q["type"] != "out_of_scope"
        relevant = relevant_pages(q, pages) if in_scope else set()
        try:
            result = answer_question(
                db,
                question=q["question"],
                k=ANSWER_K,
                document_ids=[document_id],
                embedder=embedder,
                cache=redis_client,
                generator=generator,
            )
        except GenerationError as exc:
            records.append({"id": q["id"], "type": q["type"], "error": str(exc)})
            continue
        cited_pages = [s.page_number for s in result.cited]
        generation = result.generation
        records.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "answer": result.answer,
                "refused": result.refused,
                "cited_pages": cited_pages,
                "citation_hit": any(p in relevant for p in cited_pages),
                "unsupported_citations": result.invalid_citations,
                "input_tokens": generation.input_tokens if generation else 0,
                "output_tokens": generation.output_tokens if generation else 0,
                "generation_ms": result.generation_ms,
            }
        )
    return records


def answer_metrics(records: list[dict]) -> dict:
    ok = [r for r in records if "error" not in r]
    in_scope = [r for r in ok if r["type"] != "out_of_scope"]
    out_of_scope = [r for r in ok if r["type"] == "out_of_scope"]
    generated = [r for r in ok if r["generation_ms"] > 0]
    return {
        "errors": len(records) - len(ok),
        "in_scope_n": len(in_scope),
        "answered_rate": round(mean([0.0 if r["refused"] else 1.0 for r in in_scope]), 3),
        "citation_hit_rate": round(mean([1.0 if r["citation_hit"] else 0.0 for r in in_scope]), 3),
        "unsupported_citations": sum(len(r["unsupported_citations"]) for r in ok),
        "out_of_scope_n": len(out_of_scope),
        "correct_refusal_rate": round(
            mean([1.0 if r["refused"] else 0.0 for r in out_of_scope]), 3
        ),
        "generation_ms_p50": round(percentile([r["generation_ms"] for r in generated], 50), 1),
        "generation_ms_p95": round(percentile([r["generation_ms"] for r in generated], 95), 1),
        "avg_input_tokens": round(mean([r["input_tokens"] for r in generated])),
        "avg_output_tokens": round(mean([r["output_tokens"] for r in generated])),
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# Evaluation: {report['label']}",
        "",
        f"- Run: {report['run_at']}",
        f"- Document: {report['document']}",
        f"- In-scope questions: {report['retrieval']['n_questions']}",
        "",
        "## Retrieval (page-level relevance)",
        "",
        "| Mode | Type | n | hit@1 | hit@5 | hit@10 | MRR@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode, by_type in report["retrieval"]["metrics"].items():
        for qtype, m in by_type.items():
            lines.append(
                f"| {mode} | {qtype} | {m['n']} | {m['hit@1']} | {m['hit@5']} "
                f"| {m['hit@10']} | {m['mrr@10']} |"
            )
    lat = report["retrieval"]["latency_ms"]
    lines += ["", "## Latency (ms)", "", "| Step | p50 | p95 |", "|---|---|---|"]
    lines.append(
        f"| query embedding (cold) | {lat['embedding']['p50']} | {lat['embedding']['p95']} |"
    )
    for mode in ("keyword", "vector", "hybrid"):
        lines.append(f"| search: {mode} (warm cache) | {lat[mode]['p50']} | {lat[mode]['p95']} |")
    if "answers" in report:
        a = report["answers"]["metrics"]
        lines += ["", "## Answers", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| {key} | {value} |" for key, value in a.items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="name for this run, e.g. baseline")
    parser.add_argument("--answers", action="store_true", help="also evaluate /ask answers")
    parser.add_argument("--repeat", type=int, default=3, help="search repetitions for latency")
    parser.add_argument("--document-id", help="document to evaluate (default: the only PDF)")
    args = parser.parse_args()

    questions = load_questions()
    in_scope = [q for q in questions if q["type"] != "out_of_scope"]

    with SessionLocal() as db:
        document = pick_document(db, args.document_id)
        pages = build_labels(db, document)
        records, latency, embed_ms = evaluate_retrieval(
            db, in_scope, pages, document.id, args.repeat
        )

        types = sorted({r["type"] for r in records})
        metrics = {
            mode.value: {
                "all": retrieval_metrics(records, mode.value),
                **{
                    t: retrieval_metrics([r for r in records if r["type"] == t], mode.value)
                    for t in types
                },
            }
            for mode in SearchMode
        }
        report = {
            "label": args.label,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "document": document.filename,
            "retrieval": {
                "n_questions": len(records),
                "metrics": metrics,
                "latency_ms": {
                    "embedding": {
                        "p50": round(percentile(embed_ms, 50), 1),
                        "p95": round(percentile(embed_ms, 95), 1),
                    },
                    **{
                        mode: {
                            "p50": round(percentile(values, 50), 1),
                            "p95": round(percentile(values, 95), 1),
                        }
                        for mode, values in latency.items()
                    },
                },
                "per_question": records,
            },
        }

        if args.answers:
            answer_records = evaluate_answers(db, questions, pages, document.id)
            report["answers"] = {
                "metrics": answer_metrics(answer_records),
                "per_question": answer_records,
            }

    RESULTS_DIR.mkdir(exist_ok=True)
    stem = f"{datetime.now(UTC):%Y%m%d-%H%M}-{args.label}"
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (RESULTS_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Saved evaluation/results/{stem}.json and .md")


if __name__ == "__main__":
    main()
