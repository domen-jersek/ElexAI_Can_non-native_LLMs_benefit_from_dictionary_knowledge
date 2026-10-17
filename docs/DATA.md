# DATA.md - what each source contains (Phase 0, verified)

Every number below was produced by `uv run python scripts/inspect_data.py` on the exact
snapshots pinned in `data/MANIFEST.json` (registered 2026-10-15). "Verified" means:
parsed from the actual files / queried from the restored database, not copied from a
description. Regeneration steps: `docs/REPRODUCE.md`.

## 1. DDDS snapshot - the primary dictionary

### Provenance

- **What**: Digital Dictionary Database of Slovene (DDDS), PostgreSQL backup **v3.68**
  (backup date **2026-10-07**), distributed by CJVT, University of Ljubljana.
- **Where**: CJVT wiki, book "Digital Dictionary Database of Slovene", page
  "Domain and data model links" -> "Database dump v3.68 (07.10.2026)",
  <https://nas.cjvt.si/s/gTQjMiKzD53yxyd>. Original folder kept as
  `data/raw/gigabaza-003-068-2026q/` (`003-068` = backup v3.**68**).
- **Format**: `pg_dump` directory format (produced by pg_dump 15.8 from server 15.6):
  `toc.dat` + 102 numbered data files + `restore.sql`, ~25 GB uncompressed text COPY.
- **Restored into**: local Postgres `postgres:15.19-bookworm` via
  `uv run python scripts/db_restore.py` (idempotent; see REPRODUCE.md).

### Data model in one screen

(Verified against the actual DDL and against the CJVT wiki data-model page, v1.17.)

- **LexicalUnit** is central: composed of a type (`single_lexeme_unit` | `compound` |
  `phrase` = independent headwords; `collocation` | `combination` = dependent units),
  a syntactic structure, and one or more parts (`LexicalUnit_Part` -> structure
  component + a form encoding of the part's lexeme).
- **Sense** belongs to exactly one lexical unit. For independent units, senses with a
  non-null `position` are "real" senses; every independent unit additionally has a
  "dummy" sense with null position. Dependent units have only null-position senses.
- **Definition** attaches to a sense; `definitiontype` distinguishes kinds
  (`indicator` is the most common).
- **SenseRelation** relates two senses (`synonym`, `hypernym`/`hyponym` pairs,
  `subsense`, `dependency`, ...); some relations group under semantic cluster types.
- **Word forms**: Lexeme -> WordForm (per MSD) -> FormRepresentation
  (orthography/accentuation/pronunciation) -> **FormEncoding** (the actual strings).
- **Corpus examples**: Example = sequence of ExampleSentence entries that reference
  sentences by id **inside an external corpus** (e.g. Gigafida 1.0/2.0); the sentence
  text itself is NOT stored - it is fetched through a concordancer/API. `Sense_Example`
  links senses to examples; `jedro_senseexampletoken` tracks which tokens of the
  example represent the lexical unit.
- **Resources**: `Resource` registers dictionary "views" (portals/projects);
  `LexicalUnit_Status` assigns headwords to a resource with a status
  (the inventory of resources and statuses per headword is printed by the inspector).
- **Translations** (e.g. into Hungarian), **frames**, **generic features**
  (labels via `Feature`/`FeatureValue` + `Object_Feature` generic relations),
  **measures** (per-sense corpus frequency etc.) complete the model.

### What is NOT in the dump

- **Example sentence text** (see above) - only corpus sentence ids. Consequence:
  variant B chunks contain definitions (no corpus sentences), and question context
  sentences must come from elsewhere (plan: hand-authored, lexicographer-verified -
  see D-006 in docs/DECISIONS.md).
- The corpus itself (Gigafida) is a separate resource and is not bundled.

### Excluded on restore (privacy / not needed)

`scripts/db_restore.py` does not restore internal Django/auth tables (`auth_*`,
`django_*` except `django_content_type`, `jet_*`), editor working logs
(`metadata_actionlog`, `metadata_comment`, `metadata_lexicalunitlog*`, ...) and the
~4 GB token-alignment table `jedro_senseexampletoken`. The dump is a snapshot of a
production-like database and must be treated as internal data (see Licensing).

### Verified counts (restored snapshot; `metadata_version` says data 3.68 / model 1.18, 2026-10-06)

| Table | Rows |
|---|---|
| `jedro_lexeme` | 400,836 |
| `jedro_lexicalunit` | 4,144,571 |
| `jedro_sense` | 8,156,531 = **221,517 real senses** (with position) + 7,935,014 dummy senses |
| `jedro_definition` | 231,027 (131,051 indicator + 99,976 general) on 131,057 senses (~59% of real senses); avg 1.76/sense |
| `jedro_senserelation` | 7,959,451 |
| `jedro_example` | 15,628,972 |
| `jedro_sense_example` | 19,047,805 links; 94,549 real senses (~43%) have >= 1 example |
| `jedro_examplesentence` | 15,629,969 |
| `jedro_lexicalunitpart` | 10,248,758 |
| `jedro_wordform` | 9,067,142 |
| `jedro_formrepresentation` | 31,929,516 |
| `jedro_formencoding` | 41,717,311 |
| `jedro_lexemerelation` | 66,180 |
| `jedro_sensepart` | 27,936,560 |
| `jedro_object_feature` | 69,050,952 |

**Polysemy** (real senses per unit): 42,993 lexical units with >= 2, **26,876 with >= 3**,
17,101 with >= 4, 1,216 with >= 10. At lemma level: **25,853 lemmas with >= 3 senses**
(of 370,378 lemmas carrying at least one real sense).

**Real senses by lexical-unit type**: single_lexeme_unit 170,506; quasi 29,043;
compound 18,422; phrase 3,546 (collocations/combinations carry no real senses).
**By lexeme category**: noun 96,003; adjective 71,295; verb 37,682; adverb 12,549;
other 1,988.

**Sense relation types**: dependency 7,572,739; synonym 362,496 (97,738 real senses
have an outgoing synonym); antonym 6,898; gender_pair 6,112; hypernym and hyponym
5,415 each; variant 376.

**Resources (dictionary views)**: kssj, vsms, ssss, ddds. Headwords per
resource/status (top): ddds/dsb-automatic 428,561; ssss/ssss-automatic 92,882;
kssj/kssj-automatic 70,228; ddds/dsb-sense-generated 22,647; vsms/vsms-finished 18,986;
ddds/dsb-sense-manual 14,572; ddds/default 14,443; ddds/dsb-inprogress 11,953;
kssj/kssj-sense 9,079; ssss/ssss-manual 7,848 (full inventory in the inspection JSON).

**Corpora referenced** by examples/measures: gigafida 1.0/2.0/2.1/2.2, kdz, trendi.
**Measures**: frequency (3,570,790 sense rows), sketch_engine_salience (3,562,836).

**Interpretation**: the 8.16M "senses" are dominated by dummy senses of imported
data (Sloleks lexemes, collocation imports). The lexicographic core is the
**221.5k positioned senses** (~131k with definitions), especially the 170.5k
single-lexeme senses - that core is the candidate pool for the pilot's questions
and for variant B chunks. The `ddds`/`ssss`/`kssj`/`vsms` resource+status inventory
is the menu for choosing "one dictionary" with the mentor.

### Quality notes

- Data is maintained with an editorial workflow (statuses per resource, per-object
  `last_modified`, audit context) - this is a curated dictionary, not raw crawl data.
- The snapshot contains multiple dictionary resources; the mentor must pick the
  working subset for the experiment (see open items list in the Phase-0 report).
- Internal `metadata_comment`/log tables contain editor remarks (some dated during
  2026) - excluded from the restore and never part of any artifact.

## 2. Open Slovene WordNet 1.0 (graph layer)

<a id="oswn"></a>

- **Verified**: 107,699 lexical entries, 164,903 senses, **95,262 synsets**, all with
  an ILI id. 10,774 entries have >= 3 senses (4,225 have >= 5).
- Definitions: every synset has **both** an English original (`status="manual"`) and a
  Slovene definition (`status="machine_translated"`, 95,262 each). 18 Slovene
  definitions are empty strings.
- **No inter-synset relations in the XML** (verified 2026-10-17: zero relation
  elements despite the DTD), and OSWN ids are OEWN ids with a swapped prefix
  (verified: 95,247 of 95,262 present in the OEWN 2023 release) - so the graph
  hierarchy comes from the OEWN 2023 XML. (A sloWNet/PWN-offset mapping was
  tried and rejected: OEWN renumbered synsets, only 1,108/95,262 align.)
  Lemma coverage gaps exist (e.g. *vlak* is absent).
- Lemma attribute escaping: `--hy--`, `--am--`, `_` (space), ... implemented in
  `elexai/questions.py` (see `unescape_oswn_lemma` in the inspector).
- POS distribution of synsets: nouns 63,719; verbs 12,406; participle adjectives
  9,344; adjectives 6,483; adverbs 3,310.
- **Caveat**: Slovene glosses are ChatGPT translations; fine for structure/graph use,
  not as authoritative gold text. This is why DDDS is the pilot dictionary (D-001).

## 3. OSWN <-> DDDS linked senses

- **Verified**: 164,889 rows; sense ids are unique and 1:1 with DDDS senses
  (164,889 unique). 95,255 of 95,262 OSWN synsets are linked (7 unlinked);
  104,623 unique DDDS lexical units are covered.
- 56,260 rows (34%) are multi-word forms. Format: TSV, CRLF line endings,
  header `synset_id, sense_id, lexical_unit_id, lexical_unit_form`.
- **Stale against v3.68 (verified)**: none of the 164,889 sense ids exist in the
  current snapshot - DDDS sense ids were rebased since 2023 (see D-012 in
  docs/DECISIONS.md). 102,726 of the 164,889 lexical unit ids still exist and the
  linked forms are ordinary Slovene words, so a rebuild from forms + LU anchors is
  plausible.
- Intended purpose (currently blocked by the staleness above): resolve DDDS senses
  to OSWN synsets for graph variant C.
- **Re-link v2 executed (2026-10-17, internal)**: two-pass LinkingTK alignment
  (exact lemma first: 83,179 links / 63.5% of senses; approximate fallback:
  46,751; overall 99.1% matched) - see docs/DECISIONS.md D-019. Artifact:
  `data/processed/ddds/oswn_ddds_link_v2.tsv` (+stats +sample). The published
  2023 list stays untouched in data/raw for provenance.

## 4. sloWNet 3.1 (reference only)

- **Verified**: 117,658 synsets (the complete Princeton WordNet 3.0 frame), but only
  **3,177** synsets have a Slovene definition; Slovene literals: 71,803 (38,257
  flagged `lnote="auto"`); sl usage sentences: 4,390 (en: 47,977).
- Top ILR relation types: hypernym (89,088), eng_derivative (63,656),
  similar_to (21,386), holo_member (12,293), holo_part (9,097),
  instance_hypernym (8,577), near_antonym (7,604).
- **Role**: kept in the manifest for reference; not used as the pilot dictionary.

## 5. Sloleks 3.1 (lemmatization only)

- Morphological lexicon of Slovene (372,341 entries; 100k manually checked from
  Sloleks 2.0, ~265k generated from Gigafida 2.0, 7,001 from spoken corpora),
  with word forms, MSDs, frequencies and (partly automatic) accentuation/IPA/SAMPA.
- **Role**: lemmatize question context sentences and inflected forms later phases;
  not a source of senses or definitions.

## Licensing and attribution

| Source | License | Notes |
|---|---|---|
| DDDS snapshot v3.68 | **not stated** on the distribution page | internal research use; do NOT redistribute raw files or internal tables; confirm derived-data publication with the mentor |
| OSWN 1.0 | CC BY-SA 4.0 | attribute: Cibej et al. 2023, CLARIN.SI, hdl 11356/1888 |
| OSWN<->DDDS link | CC BY 4.0 | Cibej, Krek, Laskowski, Bombek 2023, hdl 11356/1897 |
| sloWNet 3.1 | CC BY-SA 4.0 | Fiser 2015, hdl 11356/1026 |
| Sloleks 3.1 | CC BY-SA 4.0 | Cibej et al. 2026, hdl 11356/2080 |

Share-alike sources (OSWN, sloWNet, Sloleks): derived data may inherit CC BY-SA
obligations - keep attribution in `data/MANIFEST.json` and here.

## Known gotchas (for parsers and query authors)

- DDDS sense ids are 1-based integers in ranges that can exceed 10 million - keep them
  as strings in artifacts to avoid float/format surprises.
- Null `position` on `jedro_sense` = "dummy" sense; exclude from polysemy counts.
- `jedro_definition.description` may contain multiple definitions per sense (different
  `definitiontype`s); the inspector reports the type distribution.
- The link TSV uses CRLF; the OSWN XML uses escaped lemma characters; sloWNet is
  DEBVisDic XML with `xml:lang` attributes.
- Restoring the dump produces a few harmless `pg_restore` errors (e.g.
  `ALTER SEQUENCE ... OWNED BY jedro_senseexampletoken` -> table excluded on purpose).
  `scripts/db_restore.py` treats this as a warning and verifies core table counts.
- Joining `jedro_sense` -> `jedro_lexicalunit` -> the part chain multiplies rows
  (one row per lexical-unit part); use `DISTINCT ON (sense id)` or aggregate.
- DDDS sense ids were rebased between the 2023 link list and v3.68 (see D-012);
  always pin the DDDS snapshot version when joining external id lists.
- The re-link's approximate pass mixes useful morphological variants with junk
  (e.g. EMŠO -> nemški); the graph loader therefore defaults to exact links
  (D-019/D-020).
- The Docker Postgres container needs `shm_size: 2gb` and heavy analytic queries
  should disable per-gather parallelism (see D-011).
- Some common lemmas have **no lexeme rows** in v3.68 at all (verified: *miška*,
  *ključ*, *žerjav* return zero matches, even with diacritic variants) - check lemma
  existence before assuming coverage; the pilot questions avoid such words.
- The pilot's working artifact is `data/processed/ddds/lexical_core.jsonl`:
  131,056 senses with definitions, all definitions attached, plus one-hop relations
  (18,283 synonyms, 1,168 antonyms, 5,414 hypernyms, 3,890 hyponyms and 986,354
  typical-collocation `dependency` rows, capped at 24/sense). Regenerate: `make core`.
