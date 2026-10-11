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

## 2026-10-11: pp-02 citation miss (investigated, not fixed)
Question: "What should happen to old hard drives before we throw them away?" Label: 03.08.03 Media
Sanitization, PDF pp. 55-56.
- Retrieval works: hybrid rank 3, vector rank 4, keyword not found (no shared vocabulary).
- The answer is correct in substance (sanitize before disposal: destroy, cryptographically erase, clear, or
  purge), but it cites a page-54 chunk instead of a page-55 chunk.
- The label is correct. Page 54 holds 03.07.06 and 03.08.01; 03.08.03 starts on page 55. The miss is the
  model choosing a neighboring source, not a labeling error.
- Left as a known miss. Changing the prompt or the question set to fix one question would be overfitting.

## 2026-10-11: Experiment 4, identifier terms inside sentences (adopted)
Problem: bare IDs (`03.05.03`) route to keyword search (Experiment 2), but "What does requirement 03.05.03
say?" took the normal hybrid path, and its keyword leg searched the whole sentence, so the ID was buried
among common words.

Change: `identifier_terms()` pulls tokens that contain a digit plus a letter, period, or hyphen out of the
question. If any are found, the hybrid keyword leg searches only those terms (AND), while the vector leg still
embeds the full question. Flag `IDENTIFIER_TERMS_IN_SENTENCES`, default on after this experiment.

Question set: added 6 `identifier_sentence` questions (is-01 to is-06), for 42 in-scope total.

Decision rule (set before running): adopt if identifier_sentence hybrid MRR improves and no other question
type changes.

Results (runs `in-sentence-off` vs `in-sentence-on`, confirmed by `exp4-final`)
Hybrid identifier_sentence: hit@5 0.0 → 0.667, hit@10 0.167 → 1.0, MRR@10 0.021 → 0.202. hit@1 stays 0.

| Question | Hybrid rank, off | Hybrid rank, on |
|---|---|---|
| is-01 What does requirement 03.05.03 say? | not in top 10 | 5 |
| is-02 What is required by 03.01.08? | not in top 10 | 4 |
| is-03 Explain control 03.13.11. | not in top 10 | 6 |
| is-04 What does 03.08.03 require? | not in top 10 | 4 |
| is-05 Summarize requirement 03.14.02. | not in top 10 | 7 |
| is-06 What does 03.03.03 cover? | 8 | 5 |

Hybrid all 42: hit@1 0.595 → 0.595, hit@5 0.857 → 0.952, hit@10 0.881 → 1.0, MRR@10 0.695 → 0.721.
Every other type is identical, and keyword-only and vector-only rows don't change because the flag only
affects the hybrid keyword leg. Passed the rule; adopted.

Answers (`exp4-final`, flag on): 42/42 answered, 41/42 cite a labeled page (the miss is pp-02, above),
0 unsupported citations, 4/5 out-of-scope refused (oos-03 "How do I reset my Windows password?" gets a
partial answer citing pp. 46 and 48), generation p50/p95 2.0 s / 3.1 s, average 3,273 input / 112 output
tokens. All six identifier_sentence answers cite the labeled page; is-01 now cites page 44 (03.05.03).

Remaining gap: hit@1 is 0 because RRF interleaves the vector leg's results, which have nothing to do with
the ID, above the correct page. Candidate Experiment 5: route ID-in-sentence questions keyword-only, as bare
IDs already are. Expected to land near the bare-ID level (MRR ~0.58) but not yet tested.
