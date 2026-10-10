# DocSearch API

Backend service for document ingestion, hybrid (keyword + vector) search, and cited question answering.

Status: in development.

## Run locally

    docker compose up --build

Liveness: http://localhost:8000/health · Readiness: http://localhost:8000/health/ready · Docs: http://localhost:8000/docs

## Design decisions

- **Separate liveness and readiness checks.** Liveness checks nothing external, so a database outage doesn't trigger container restarts; readiness returns 503 when a dependency is down so load balancers stop routing traffic.
- **Asynchronous ingestion with RQ.** Uploads return immediately; a worker extracts, chunks, and embeds in the background. The API and worker are the same image with different commands.
- **Idempotent, atomic ingestion.** Embeddings are computed before any writes, then all chunks commit in one transaction. Re-running a job replaces chunks rather than duplicating them, and already-ready documents are skipped.
- **Permanent vs. transient failures.** Bad documents (encrypted, no extractable text) fail once with a clear error; API and network errors are retried with backoff (10s, 30s, 60s).
- **Page-aware token chunking.** 500-token windows with 75-token overlap, measured with the embedding model's own tokenizer; chunks never cross pages, so every chunk can cite a page.
- **Provider-agnostic embeddings.** The pipeline depends on an `Embedder` interface; a deterministic fake embedder keeps tests offline and free.
- **Grounded answers with validated citations.** `/ask` retrieves via hybrid search, packs sources into a token budget, and instructs the model to answer only from numbered sources and cite every claim. Citations are parsed and checked against the sources actually provided; invalid references are reported, not hidden.
- **Explicit refusals.** The model must reply with a fixed sentence when sources don't contain the answer; with no retrieved sources, the API refuses without calling the model at all.
- **Prompt-injection hygiene.** Document text is wrapped in `<source>` tags, marked as data rather than instructions, and prevented from closing its own tag.
- **Separated latency.** Responses report `retrieval_ms` and `generation_ms` independently; upstream LLM failures return 502.

## Evaluation

A labeled set of 36 questions over NIST SP 800-171r3 (8 control-ID lookups, 10 keyword queries,
10 paraphrases written to avoid the document's wording, 8 natural questions) plus 5 out-of-scope
questions. Relevance is page-level: each question is labeled with control IDs, and the harness maps
controls to page spans from their headings, so labels survive re-chunking. The harness calls the same
service functions as the API. Run it with `python -m evaluation.run_eval --label <name> [--answers]`;
results are committed in `evaluation/results/`.

### Retrieval (hybrid search, 36 questions)

| Configuration | hit@1 | hit@5 | MRR@10 |
|---|---|---|---|
| Keyword only | 0.389 | 0.639 | 0.504 |
| Vector only | 0.556 | 0.778 | 0.639 |
| Hybrid (RRF), baseline | 0.583 | 0.972 | 0.716 |
| + OR-style keyword leg | 0.639 | 0.972 | 0.747 |
| **+ identifier-aware routing (current)** | **0.694** | **1.000** | **0.807** |
| Heading-aware chunking (rejected) | 0.667 | 0.972 | 0.808 |

Each change was run as an A/B against a decision rule set before seeing results. Heading-aware
chunking improved vector-only MRR (0.639 → 0.718) but regressed keyword ranking because of
`ts_rank_cd`'s length bias; it failed the rule and is kept behind a flag, off. Re-running the
restored configuration reproduced identical results.

### Answers (`/ask`, current configuration)

| Metric | Value |
|---|---|
| In-scope questions answered | 36/36 (100%) |
| Citation accuracy (≥1 citation on a relevant page) | 35/36 (97.2%) |
| Unsupported citations | 0 |
| Out-of-scope questions correctly refused | 4/5 (80%) |
| Generation latency p50 / p95 | 2.1 s / 3.1 s |

Answer metrics come from a non-deterministic model and vary slightly between runs (baseline run: 36/36 citation
accuracy; final run: 35/36). Retrieval metrics are deterministic and reproduce exactly.

### Latency
Search (warm query cache): keyword ~4 ms, hybrid ~51 ms p50. Cold query embedding ~170 ms p50.
Identifier-shaped queries skip the embedding call entirely.