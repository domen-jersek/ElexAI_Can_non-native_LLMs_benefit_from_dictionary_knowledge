# LinkingTK spike result (2026-10-16)

**Question.** The published 2023 OSWN↔DDDS link list is stale against DDDS v3.68
(D-012). Could the [LinkingTK](https://github.com/jmccrae/linkingtk) toolkit
(by John McCrae; Apache 2.0) do the word-sense alignment (WSA) for us?

**Verdict: yes — adopt it for a scoped re-link package.** Details below.

## What was actually tested (reproducible)

- Isolated scratch venv (no repo lockfile pollution):
  `uv venv` + `uv pip install "git+https://github.com/jmccrae/linkingtk"` (base
  package, no extras).
- Data: 12 sample lemmas (kos, list, greda, obraz, vlak, pero, most, jabolko,
  kolo, mesec, zvezda, srce) — 90 DDDS senses (from `lexical_core.jsonl`,
  descriptions = attached definitions) vs 61 OSWN senses (parsed from the OSWN
  XML, Slovene glosses).
- Linker: `StringSimilarityLinker(source_field="description",
  target_field="description", metric="word_overlap")` with `LabelOverlap`
  blocking (`max_matches=5`), i.e. the documented WSA baseline from the
  toolkit's Getting Started page.
- Script: `run_spike.py` (kept in the scratch directory; the method above is
  enough to reproduce).

## Results

- **84 of 90 DDDS senses (93%) got at least one link.**
- Scores are bimodal: 46 links with meaningful description overlap vs 38 with
  overlap ≤ 0.2 (junk-level, trivially filterable by a threshold).
- Eyeballed quality on clear cases is good:
  - *mesec*: 3/3 correct (del leta → "ena od dvanajstih razdelitev leta";
    30 dni → "približno 30 dni"; Zemljin satelit → "naravni satelit Zemlje").
  - *most*: the object/bridge sense maps to "objekt, ki omogoča ... prehod
    preko ovire" (score 1); the metaphorical senses land on junk pairs with
    score 0 — separable.
  - *kos*: "izdelek; primerek" → "predmet, ki je primer neke vrste" (correct);
    "del celote" → "del nečesa, ki je dolg in ozek" (wrong OSWN sense chosen;
    the right one exists in OSWN but needs better scoring to win).

## Observations / caveats

1. Score scale is raw overlap counts (0, 1, 2, 3...), not normalized similarity —
   fine for ranking/thresholding, not directly comparable across datasets.
2. The baseline is string-only. The toolkit additionally offers
   `EmbeddingSimilarityBlocker`, `VectorIndexEntitySource` (any embedder; we
   could plug in our BGE-M3), `OptimalMatcher` (Hungarian 1:1) and
   `LlmRerankerLinker` (same OpenRouter setup as the pilot) — the spike did not
   test those (LLM rerank skipped deliberately, no key in the spike).
3. Alignment is many-to-many-ish: DDDS has ~1.5-1.7x more senses than OSWN for
   the same lemmas (consistent with the old link table's 164,889 links for
   95,255 synsets), so GreedyMatcher (many sources → same target) fits better
   than strict 1:1.
4. Six unlinked DDDS senses are multi-word/other-lemma edge cases — expected
   under strict label blocking; label normalization can shrink that.

## Recommended scope if adopted (after Klemen's OK)

- Full run: DDDS 131k definition-bearing senses × OSWN 165k senses, blocked by
  normalized lemma; baseline string similarity + a top-K embedding re-rank
  (BGE-M3, already pinned) + optionally LLM re-ranking of the shortlist;
  emit a versioned table (`oswn_ddds_link_v2.tsv`-style: synset_id, sense_id,
  score, method, DDDS backup version) plus a hand-checked quality sample.
- **Do NOT** adopt for the pilot experiment itself: the A/B/C runner, prompt
  protocol and LLM-free scoring stay ours (D-014); LinkingTK's `Evaluator` is
  only useful for the re-link task's own precision/recall checks.
- Licence is compatible (Apache 2.0); it is a separate tool, used offline to
  produce a derived dataset, not a runtime dependency of the pilot.
