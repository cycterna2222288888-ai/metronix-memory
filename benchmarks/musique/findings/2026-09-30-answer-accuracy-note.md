# Answer accuracy (EM / F1) of production vs learned "ppr+" on the #515 held-out sets

Date: 2026-09-30. Follows `2026-09-26-fusion-research-note.md` (PR #515), whose §7 lists
"passage recall, not answer accuracy; no reader/EM/F1 was run" as a limitation.

Status: **protocol only** (§1-§6). This part was committed before any reader call on
the evaluation questions and is not edited afterwards; deviations and results go into
later sections and later commits (git history of this file).

## 1. Question and hypotheses

#515 showed that learned fusion with the "ppr+" graph channel raises passage recall over
the production pipeline on held-out questions (R@5 +4.5 on the MuSiQue confirm half,
+13.8 on 2Wiki). Does that turn into more correct answers when one fixed reader model
answers from the retrieved passages?

- **H1 (MuSiQue)**: on the MuSiQue confirm half (500 questions), mean answer F1 of
  configuration B is higher than that of configuration A.
- **H2 (2Wiki)**: the same on the 2Wiki set (1,000 questions).

Expectation, stated before the run: positive on both, clearly smaller than the R@5 gain
on MuSiQue (a 3B reader fails many 3- and 4-hop questions even with every gold passage in
front of it, and B loses some R@2), larger on 2Wiki. A null result on MuSiQue at 500
questions is a plausible outcome and will be reported as such.

## 2. What is compared

The two configurations of #515's headline comparison, run by the production pipeline
(`pipeline_probe`) exactly as in #515 §4 / §8: `k = 25`, query expansion and query
classifier off, `--skip-graph-enrichment`, cross-encoder `bge-reranker-v2-m3`, hybrid
nomic-embed-text + SPLADE first stage.

| | configuration | `pipeline_probe` arguments |
| --- | --- | --- |
| A | production default, `bfs:signal` | `--graph bfs --fusion signal` |
| B | learned fusion + "ppr+" | `--graph ppr-novel --fusion learned --env METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific --env METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=ranked` (shipped model `src/metronix/retrieval/fusion_models/default.json`, fitted on the MuSiQue tune half) |

Data, identical to #515 and never used for fitting or selection:

- MuSiQue: HippoRAG MuSiQue-1000 with the released Llama-3.3-70B OpenIE graph; the confirm
  half = odd question index, 500 questions (same qids and order as
  `results/2026-09-27/hipporag_musique_runs.json.gz`, `confirm_*`);
- 2Wiki: HippoRAG 2Wiki-1000 with the title-mention graph, all 1,000 questions.

#515's per-question files hold only the ranks of gold passages, not the retrieved lists,
so both configurations are re-run on a freshly loaded stack with `--keep-top 5` (new flag;
records the first 5 distinct `retrieved_doc_labels`). **Reproduction check**: per
question, the gold ranks of the re-run are compared with #515's rows. Expected: R@5
within 0.5 points of #515 (A: 58.2 / 71.8, B: 62.8 / 85.7); any difference is reported
(Ollama is 0.35.0 here vs 0.34.4 in #515, and PPR ties depend on Neo4j element ids,
#515 §5.10). The reader uses the re-run lists, whatever the check shows.

## 3. Reader (identical for A and B)

- Model: `qwen2.5:3b` in Ollama 0.35.0, Q4_K_M, model id `357c53fb659c`, weights blob
  `sha256:5ee4f07cdb9b...`; the full digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` equals the sha256 of the registry.ollama.ai manifest of `qwen2.5:3b` on 2026-09-30; the
  script refuses to run if the local digest does not start with `357c53fb659c`.
- Options: `temperature 0`, `seed 0`, `num_ctx 4096`, `num_predict 256`; nothing else.
- Input: the **top 5 passages of the final ranking** (post-rerank `retrieved_doc_labels`,
  in rank order), each as `Wikipedia Title: <title>\n<text>`. This is HippoRAG 2's QA
  protocol (`qa_top_k = 5`). It is *not* the production answer context (`fragments`, up
  to 25 passages under a token budget): the production prompt asks for long answers,
  which EM / F1 cannot score, and 25 passages per call are too slow for a 3B model on
  CPU. Consequence: the "both gold passages in context" gain of #515 (+13.4 / +34.5
  points) is not what is measured here; the top-5 ranking is.
- Prompt: HippoRAG 2's `rag_qa_musique` template verbatim (system message, the one-shot
  "Neville A. Stanton" example, `Question: ...\nThought: `), which HippoRAG 2 uses for
  both datasets; HippoRAG commit `398bfdc`. Answer = text after the first `Answer:`,
  else the whole response (HippoRAG's rule). Implemented in
  `scripts/answer_eval.py` (`qa_messages`, `extract_answer`).
- Identical prompts are answered once and reused (with temperature 0 the reader is a
  function of the prompt), so a question whose top 5 is the same list under A and B gets
  the same answer by construction. Determinism is checked in the pilot (§6) by calling
  the model twice on the same prompts.

## 4. Metrics

- Per question: **EM** and **F1** with the standard SQuAD / HippoRAG normalisation
  (lower case, punctuation removed, articles `a`/`an`/`the` removed, whitespace
  collapsed), maximum over the gold answer and its `answer_aliases` (HippoRAG's
  `get_gold_answers`; 2Wiki has no aliases).
- **Primary metric: F1**, mean over questions, per dataset. EM is secondary.

## 5. Analysis (fixed now)

- Per dataset, paired over questions: mean of the per-question difference B - A, bootstrap
  95% CI (10,000 resamples of questions, seed 0) and exact two-sided sign test on the
  questions where the two differ (ties dropped): `compare_runs.bootstrap_ci` /
  `sign_test`, the same functions as #515.
- H1 and H2 are tested on F1 with the sign test, Holm correction over the two at
  alpha = 0.05. A hypothesis "holds" if its Holm-adjusted p < 0.05 **and** the mean F1
  difference is positive. The bootstrap CI is reported alongside.
- EM gets the same table, uncorrected, as secondary.
- Descriptive, not tested: counts of questions with identical top 5 under A and B; the
  breakdown by hop count (MuSiQue) and question type (2Wiki); R@5 of the re-run next to
  F1, to show how much of the recall gain becomes answer gain.
- Absolute EM / F1 are **not** compared with published HippoRAG / HippoRAG 2 QA numbers:
  their reader is Llama-3.3-70B / GPT-4o-mini, ours is a 3B quantised model. Only A vs B
  is interpreted.

## 6. Procedure and budget

1. Load both sets (`hipporag_set.py`, as in #515 §8).
2. **Pilot for timing** (the user decides on the full run from it): the first 10 questions
   of the MuSiQue confirm half, both configurations, retrieval then reader; each reader
   prompt is sent twice (determinism). The pilot's answers are part of the full run and
   are not rerun. Only timing and determinism are read from the pilot; its EM / F1 are
   not looked at before the decision.
3. If the projected full run exceeds 6 hours, a subsample is proposed. Rule, fixed now:
   the first N questions of each set in manifest order (the dataset's own order, which
   does not depend on any result), with N chosen from the timing alone, and the loss of
   power stated before the run. It is recorded here as an amendment before the run.
4. Full run: retrieval A and B, then the reader, per dataset.
5. Stored in the repository: per question `{qid, answer, em, f1}` per configuration,
   gzipped JSONL (`results/2026-09-30/`). Responses, prompts and retrieved lists stay out
   (regenerable with the commands of this note).
