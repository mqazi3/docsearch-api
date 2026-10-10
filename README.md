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