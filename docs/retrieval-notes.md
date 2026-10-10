# Retrieval notes

## 2026-10-09: NIST SP 800-171r3, first manual comparison
Query `03.05.03` (expected: chunk containing the 03.05.03 Multi-Factor Authentication definition, PDF p.44)
- keyword: rank 3 (outranked by appendix tailoring tables, p.107)
- vector: not in top 50 (returns other `03.xx.xx`-dense parameter tables)
- hybrid: rank 5 (vector-only results interleaved above it)

Observations
- Identifier queries: vector adds noise; consider query-type-aware weighting.
- Fixed token windows split controls mid-section (chunk 53 holds the end of 03.05.02 + start of 03.05.03); consider heading-aware chunking.
- Query-embedding cache: 1,543 ms cold vs 10.8 ms cached for the same vector query.

Query `how should passwords be protected` (expected: 03.05.07 Password Management, PDF p.46)
- keyword, vector, hybrid: all rank 1 (hybrid score 0.0328: rank 1 in both lists)

Query `how long should audit logs be kept` (expected: 03.03.03.b "Retain audit records...", PDF p.33)
- keyword: 0 results; websearch_to_tsquery ANDs every term, and the text says "retain ... records", not "kept ... logs"
- vector: rank 3 (vocabulary mismatch handled; chunk also contains half of 03.03.04)
- hybrid: rank 3 (keyword contributed nothing)
- Note for answer generation: the document sets NO retention period; it defers to the organization's records-retention policy. A correct answer must say so, not invent a duration.

Candidate improvements to measure in Stage 5
1. OR-style keyword query for the hybrid keyword leg, so natural-language questions still produce keyword candidates
2. Heading-aware chunking (one control per chunk)
3. Query-type-aware weighting (lean on keyword for identifier queries like `03.05.03`)
4. Optional reranking of the fused top-N

## 2026-10-10: Answer quality, first manual check (POST /ask)
Setup: hybrid retrieval, k=8, context budget 6,000 tokens, model `gpt-6-luna`.

| Question | Result | Cited | Tokens (in/out) | Generation |
|---|---|---|---|---|
| How should passwords be protected? | Correct: transmit only over cryptographically protected channels, store in protected form (salted one-way hashes), protect from disclosure/modification | 03.05.07 (p.46), authenticator mgmt (p.48) | 3,549 / 46 | 2.5 s |
| How long should audit logs be kept? | Correct: no fixed duration; retain per the organization's records-retention policy. **Passed the hallucination test** (no invented period) | 03.03.03 (p.33) | 3,459 / 84 | 1.7 s |
| What is required for multi-factor authentication? | Correct: two or more different factors (know/have/are), for privileged and non-privileged accounts | 03.05.03 via mixed chunk 53 (p.44) | 3,364 / 136 | 2.8 s |
| What is the capital of France? | Correct refusal (exact sentence, `insufficient_context: true`) despite 8 unrelated chunks in context | none | 2,775 / 13 | 1.3 s |

Observations
- 4/4 correct; 0 unsupported citations; every citation pointed to a page that supports the claim.
- Cost: ~3–3.5K input tokens per answer, roughly $0.0004 per question at current gpt-6-luna pricing.
- Latency: generation 1.3–2.8 s dominates. Retrieval is ~11 ms with a cached query embedding vs ~1.5 s cold.
- Mixed chunks (e.g., chunk 53 = end of 03.05.02 + start of 03.05.03) still produced correct answers, but they waste context tokens; heading-aware chunking remains a candidate improvement.

## 2026-10-10: Bug found during manual testing
- Swagger's placeholder `document_ids` UUID filtered retrieval down to zero chunks, so /ask silently refused every question.
- Fix: /ask and /search now return 404 for unknown document IDs instead of failing silently; the zero-source refusal path is now logged.

## 2026-10-10: Experiment 1, OR-style keyword leg in hybrid (adopted)
Hybrid all: hit@1 0.583 → 0.639, hit@5 0.972 → 0.972, MRR@10 0.716 → 0.747.
Gains: keyword-type MRR 0.933 → 1.0; natural MRR 0.833 → 0.900 (nq-02 audit retention rank 3 → 1).
Neutral/noisy: paraphrase MRR 0.728 → 0.720 (3 questions up, 3 down). Identifiers unchanged.
Keyword-only and vector-only rows identical to baseline, so the change was isolated.
Verdict: modest gain (~1 question of MRR); adopted as default with a config flag to disable.

## 2026-10-10: Experiment 2, identifier-aware routing (adopted)
Single-token queries containing a digit (e.g. 03.05.03, AC-2) skip the vector leg in hybrid mode.
Hybrid identifier: hit@1 0.0 → 0.25, hit@5 0.875 → 1.0, MRR 0.312 → 0.583.
Hybrid all: hit@5 0.972 → 1.0, MRR 0.747 → 0.807. All non-identifier types unchanged (classifier never misfired).
Side benefit: identifier lookups skip the embedding API call entirely (not visible in harness latency,
which pre-warms the query cache).

Cumulative vs baseline (hybrid, all): hit@1 0.583 → 0.694, hit@5 0.972 → 1.0, MRR@10 0.716 → 0.807 (+12.7%).

Remaining gaps
- Identifier hit@1 only 0.25: appendix tables mentioning the ID still outrank the definition (ranks 2-3).
- Paraphrase MRR: hybrid 0.720 < vector-only 0.795; fusion adds keyword noise on long paraphrased questions.

## 2026-10-10: Experiment 3, heading-aware chunking (rejected)
Splitting at numbered headings: 159 → 305 chunks.
Hybrid all: MRR 0.807 → 0.808 (flat), hit@5 1.0 → 0.972. Identifier MRR 0.583 → 0.500, keyword 1.0 → 0.95;
natural 0.90 → 1.00, paraphrase 0.720 → 0.758. Failed the pre-set rule (hit@5 dropped; two types fell > 0.03).

Why: vector-only improved substantially (MRR 0.639 → 0.718; paraphrase 0.795 → 0.883) because focused chunks
embed more sharply, but keyword-only regressed (0.504 → 0.457). ts_rank_cd with default normalization favors
long, term-dense chunks, so short focused definitions lost to ID-dense appendix tables.

Follow-up hypothesis (not yet tested): length-normalized keyword ranking (ts_rank_cd normalization flag) with
heading chunks. Needs a larger question set first to avoid overfitting 36 questions.
Code kept behind CHUNK_SPLIT_ON_HEADINGS (default false); index reverted to 159 window chunks.