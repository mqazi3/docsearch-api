# DocSearch API

Backend service for document ingestion, hybrid (keyword + vector) search, and cited question answering.

Status: in development.

## Run locally

    docker compose up --build

Liveness: http://localhost:8000/health · Readiness: http://localhost:8000/health/ready · Docs: http://localhost:8000/docs

## Design decisions

- **Separate liveness and readiness checks.** Liveness checks nothing external, so a database outage doesn't trigger container restarts; readiness returns 503 when a dependency is down so load balancers stop routing traffic.