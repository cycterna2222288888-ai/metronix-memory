# Multi-hop retrieval in Metronix: evidence from MuSiQue

Status: **draft, 2026-09-24.** Oracle-graph results are final for this slice; results on
the LLM-extracted graph and the end-to-end pipeline are pending (marked *pending*).

## Summary

Metronix's published benchmarks (LoCoMo, LongMemEval, MemoryAgentBench) conclude that
"relevant evidence is usually found". It is not established that those suites exercise
bridge multi-hop retrieval (§5.5 of the #497 notes found LongMemEval's "multi-session"
questions to be independent facts, not bridges). On MuSiQue-Ans 2-hop questions, where
the second paragraph is reachable only through an entity named in the first, and which
were filtered against single-hop shortcuts, the picture is different:

1. **Hybrid dense + SPLADE retrieval misses the bridge paragraph** from its top 30 in
   53 of 150 questions (35%), while finding the first-hop paragraph at median rank 1.
2. **The default BFS graph channel could not traverse at all** before the #508 fix:
   0 of 150 last-hop paragraphs reached via expansion; 145 of 150 after it.
3. With production seeding (`extract_title_entities`), **BFS is seed-bound**: 90 of 150
   queries produce no usable seed, so the channel returns the last-hop paragraph for
   only 60 of 150.
4. The existing, **opt-in PPR channel** (dense-anchored personalized PageRank) returns
   the last-hop paragraph for **135 of 150**, and dense top-30 ∪ PPR covers it for
   **144 of 150** (dense ∪ BFS: 123; dense alone: 97).
5. PPR spends most of its 5 slots re-returning dense's own anchor documents. Excluding
   the anchors (new opt-in flag) raises dense top-30 ∪ PPR to **149 of 150**
   (prototype measurement; formal flag run *pending*).
6. A HippoRAG-2-style teleport (mass on dense anchor documents instead of all entities)
   **did not help** here: 75 of 150 vs 133 for the current uniform teleport.

All of the above uses an **oracle graph** built from MuSiQue's gold decompositions and
is therefore an upper bound on what the graph channels can contribute. The same
measurements on a graph extracted by Metronix's own pipeline (`qwen2.5:3b`) are
*pending*; that comparison decides how much of the gain is real.

## Setup

**Data.** First 150 answerable 2-hop questions of MuSiQue-Ans dev
(`dgslibisey/MuSiQue` @ `c8f4f8c`), all 20 paragraphs per question (2 supporting,
18 distractors). MuSiQue reuses Wikipedia paragraphs across questions; documents are
deduplicated by content hash: 2999 occurrences → 2328 documents (250 supporting).

**Graphs.**

| Graph | How it is built | Used for |
| --- | --- | --- |
| Oracle | Paragraph titles as entities (MENTIONS); each decomposition step `subject -[relation]-> answer`, both mentioned by the step's supporting paragraph; `answer_aliases` as ALIAS | Upper bound; isolates retrieval logic from extraction quality |
| LLM | Production `write_doc_graph` with `qwen2.5:3b` over "title + paragraph" | Realistic graph; first 30 questions (535 documents) — *pending* |

**Stack.** Neo4j 5.26 Community, Qdrant 1.18.0 (versions from `docker-compose.yml`),
Ollama 0.34.4 with `nomic-embed-text` (768-d) for dense vectors, local SPLADE
`naver/splade-cocondenser-ensembledistil` for sparse vectors, production
`add_document` ingestion. Run on a 4-core CPU container.

**Channels measured.** `recall_dense` (hybrid dense + sparse RRF, top 30);
`recall_graph` (BFS, default, top 5); `recall_graph_ppr_async` (opt-in PPR anchored on
the top-5 dense documents, top 5). Seeds: `extract_title_entities(question)`
(production) unless stated as *oracle seeds* (the gold step-0 subject).

**Metrics.** Whether the hop-0 and last-hop gold paragraphs are among a channel's
returned documents, and among dense top-30 ∪ graph channel (the candidate pool fusion
can draw on). End-to-end: whether they reach the fragments handed to the answer model
after merge, signal scoring and cross-encoder rerank (*pending*).

## Results (oracle graph, 150 questions)

### Dense retrieval alone

| | top-5 | top-10 | top-30 |
| --- | --- | --- | --- |
| hop-0 paragraph | 143 | 147 | 149 |
| last-hop paragraph | 62 | 74 | 97 |
| both | 58 | 73 | 97 |

Typical miss: *"Where is Ulrich Walter's employer headquartered?"* — the Ulrich Walter
paragraph is rank 2; the German Aerospace Center → Cologne paragraph shares no terms
with the question and is absent from the top 30.

### Graph channels (production seeds)

| | BFS (default) | PPR (opt-in) |
| --- | --- | --- |
| last-hop paragraph in channel top-5 | 60 | **135** |
| both paragraphs in channel top-5 | 60 | 132 |
| empty result | 90 | 0 |
| dense@30 ∪ channel: last hop | 123 | **144** |
| last hop found only via the graph channel | 26 | 47 |
| mean latency per query (contended CPU) | 46 ms | 86 ms |

With oracle seeds BFS reaches the last hop in 146 of 150 — its weakness is seeding, not
traversal. PPR sidesteps seeding by anchoring on dense results.

### PPR variants (prototype script `ppr_proto.py`, branch `wip/ppr-multihop`)

| Teleport | channel top-5: last hop | dense@30 ∪ channel: last hop |
| --- | --- | --- |
| uniform over subgraph entities (current) | 133 | 143 |
| dense anchor documents, weighted by dense score | 75 | 105 |
| 70% anchor documents + 30% query entities | 91 | 117 |
| any of the above, dense anchors excluded from output | 85 | **149** |

The prototype ranks labels directly; the production channel fetches points for the
ranked labels, which is why its uniform-teleport figure (135) differs slightly from
the prototype's (133).

Teleporting onto the anchor documents concentrates probability mass on the documents
dense already returned, so they fill the top 5. The gain comes from **not spending the
graph channel's slots on dense's own documents**, not from changing the walk. This is
the motivation for `METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS`.

The 15 remaining PPR misses are ranking losses around hub entities shared by many
questions (e.g. *Nelson River*, *Vila Franca de Xira*), where the walk's mass spreads
over many documents.

### End-to-end: does the evidence reach the answer model? — *pending*

`pipeline_probe.py`, 30 questions, graph modes off / bfs / ppr / ppr-novel, oracle
and LLM graphs.

### LLM-extracted graph — *pending*

Same channels on the `qwen2.5:3b` graph for the first 30 questions. Early observation:
the extractor misses bridge entities (the *Philae* paragraph yields *Cologne* but not
*German Aerospace Center*), which breaks exactly the links multi-hop depends on.

## Defects found along the way

| Defect | Effect | Status |
| --- | --- | --- |
| `get_graph_relationships` returned bare `RETURN r` (#508) | endpoint names read as `""`; BFS never expanded (0/150) | fixed, branch `fix/508-graph-relationship-projection` |
| Graph channel cuts BFS labels by Qdrant scroll order (UUID) with constant score 1.0 | 5 of the 15 questions where the cut applies lose BFS-found gold | documented, `findings/2026-09-24-graph-channel-unranked-truncation.md` |
| Extraction LLM call had no output cap | `qwen2.5:3b` looped in JSON mode, holding the worker ~20 min per paragraph plus retries | fixed, branch `fix/graph-extraction-output-cap` (`GRAPH_EXTRACTION_MAX_TOKENS`) |
| Harness: per-question paragraph copies | BFS reached another question's copy of the gold text, scored as a miss (23 of 37 misses) | fixed in `convert.py` (content-hash labels) |

## Limitations

- **Oracle graph** for all headline numbers: an upper bound, not a production estimate.
- **150 questions, 2-hop only, one run.** No 3/4-hop, no variance estimate.
- **Candidate-pool metrics**, not answer accuracy (EM/F1).
- **No external baseline.** Numbers are not yet comparable to published MuSiQue results
  (e.g. HippoRAG 2), which use the full dev set and Recall@2/@5 over passages.
- The PPR anchor-exclusion result is a prototype measurement on the oracle graph and
  may not transfer.
- CPU-only run; latency numbers were measured under contention.

## Reproduce

```bash
python -m benchmarks.musique.scripts.dataset --limit 150
python -m benchmarks.musique.scripts.convert --workspace musique-dev --reset
python -m benchmarks.musique.scripts.probe --limit 150 --seeds title --recall --dense --ppr
python -m benchmarks.musique.scripts.probe --limit 150 --seeds title --recall --dense --ppr \
    --ppr-exclude-anchors
python -m benchmarks.musique.scripts.pipeline_probe --graph ppr --limit 30
# LLM graph (slow on CPU):
python -m benchmarks.musique.scripts.convert --graph llm --workspace musique-llm \
    --label-prefix musique-llm --limit 30 --manifest <path>/manifest_llm30.jsonl --reset
```

## Next steps

1. Finish the LLM-graph and end-to-end measurements; update this report.
2. Scale to the full MuSiQue dev set (2/3/4-hop) and 2WikiMultiHopQA on a GPU; report
   passage Recall@2/@5 and answer EM/F1 next to published baselines.
3. Compare extractors (3B, 7B, an API model) to measure how much of the graph gain
   survives extraction quality.
4. Decide #156 (PPR take/park) and #497 (score fusion) with this evidence; the
   unranked-truncation observation belongs to #497.
