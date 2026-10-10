# Evaluation: heading-chunks

- Run: 2026-10-10T05:54:19+00:00
- Document: Protecting Controlled Unclassified Information in Nonfederal Systems and Organizations.pdf
- In-scope questions: 36

## Retrieval (page-level relevance)

| Mode | Type | n | hit@1 | hit@5 | hit@10 | MRR@10 |
|---|---|---|---|---|---|---|
| hybrid | all | 36 | 0.667 | 0.972 | 1.0 | 0.808 |
| hybrid | identifier | 8 | 0.125 | 0.875 | 1.0 | 0.5 |
| hybrid | keyword | 10 | 0.9 | 1.0 | 1.0 | 0.95 |
| hybrid | natural | 8 | 1.0 | 1.0 | 1.0 | 1.0 |
| hybrid | paraphrase | 10 | 0.6 | 1.0 | 1.0 | 0.758 |
| vector | all | 36 | 0.667 | 0.778 | 0.778 | 0.718 |
| vector | identifier | 8 | 0.0 | 0.0 | 0.0 | 0.0 |
| vector | keyword | 10 | 0.9 | 1.0 | 1.0 | 0.95 |
| vector | natural | 8 | 0.875 | 1.0 | 1.0 | 0.938 |
| vector | paraphrase | 10 | 0.8 | 1.0 | 1.0 | 0.883 |
| keyword | all | 36 | 0.333 | 0.583 | 0.639 | 0.457 |
| keyword | identifier | 8 | 0.125 | 0.875 | 1.0 | 0.5 |
| keyword | keyword | 10 | 0.7 | 1.0 | 1.0 | 0.833 |
| keyword | natural | 8 | 0.375 | 0.375 | 0.5 | 0.391 |
| keyword | paraphrase | 10 | 0.1 | 0.1 | 0.1 | 0.1 |

## Latency (ms)

| Step | p50 | p95 |
|---|---|---|
| query embedding (cold) | 169.1 | 455.8 |
| search: keyword (warm cache) | 3.7 | 6.6 |
| search: vector (warm cache) | 49.2 | 53.9 |
| search: hybrid (warm cache) | 52.2 | 58.9 |
