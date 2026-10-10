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