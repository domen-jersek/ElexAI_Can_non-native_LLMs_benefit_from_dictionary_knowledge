"""Tests for variant D neighborhood scoring and context rendering (no Neo4j)."""

from __future__ import annotations

from elexai.graph.ranking import (
    GraphSense,
    build_context,
    build_relation_context,
    rank_candidates,
)


def make(
    sense_id: str,
    position: int,
    indicator: str,
    definition: str = "",
    synonyms: tuple[tuple[str, str], ...] = (),
    collocations: tuple[str, ...] = (),
    synset_literals: tuple[str, ...] = (),
    hypernym_glosses: tuple[str, ...] = (),
    lemma: str = "kos",
) -> GraphSense:
    return GraphSense(
        sense_id=sense_id,
        lemma=lemma,
        pos="noun",
        position=position,
        indicator=indicator,
        definition=f"{indicator} | {definition}" if definition else indicator,
        synonyms=list(synonyms),
        collocations=list(collocations),
        synset_literals=list(synset_literals),
        hypernym_glosses=list(hypernym_glosses),
    )


def kos_candidates() -> list[GraphSense]:
    return [
        make(
            "10",
            1,
            "del celote",
            "del snovi ali živila, navadno ločen od večje celote",
            synonyms=(("s1", "frtalja"),),
            collocations=("kos kruha", "kos pogače", "kos torte"),
        ),
        make(
            "11",
            2,
            "ptica",
            "pogosta ptica pevka, katere samec je črne barve",
            synonyms=(("s2", "kosar"),),
            collocations=("peti kot kos", "gnezdo na veji"),
        ),
    ]


def test_collocations_rank_piece_above_bird():
    ranked = rank_candidates(
        "Kuhar je odrezal tanek kos kruha.", "kos", kos_candidates(), target_word="kos"
    )
    assert ranked[0].sense.sense_id == "10"
    assert "kruha" in ranked[0].matched_collocations
    assert ranked[0].score > ranked[1].score


def test_bird_sentence_ranks_bird_first():
    ranked = rank_candidates(
        "Na veji je gnezdo in ptica tam peti.", "kos", kos_candidates(), target_word="kos"
    )
    assert ranked[0].sense.sense_id == "11"
    assert ranked[0].score > 0


def test_target_lemma_token_is_not_scored():
    ranked = rank_candidates("kos", "kos", kos_candidates(), target_word="kos")
    assert all(r.score == 0.0 for r in ranked)


def test_target_word_inflections_are_not_evidence():
    """Regression: the target word's surface form must not score (v2 bug).

    The real dictionary contains single-word collocation entries that are just
    the lemma's own inflected form (e.g. "boksu"). Before the fix, a sentence
    containing "boksu" gave a 2.0 collocation match to whichever sense owned
    that entry - the false positive the designed v2 set caught.
    """
    piece = make("10", 1, "del celote", collocations=("garažni boks",), lemma="boks")
    other = make("11", 2, "prevozno sredstvo", collocations=("boksu",), lemma="boks")
    ranked = rank_candidates(
        "Sosed v garažnem boksu shranjuje orodje.",
        "boks",
        [piece, other],
        target_word="boksu",
    )
    assert all("boksu" not in r.matched_collocations for r in ranked)
    assert ranked[0].sense.sense_id == "10"  # tie -> dictionary order

    # the same sentence with the lemma form still must not score
    ranked = rank_candidates(
        "Sosed v garažnem boksu shranjuje orodje.", "boks", [piece, other], target_word="boks"
    )
    assert all("boks" not in r.matched_collocations for r in ranked)


def test_target_word_stem_is_excluded():
    sense = make(
        "10", 1, "predmet", collocations=("paličicah", "dišavne paličice")
    )
    ranked = rank_candidates(
        "V sobi je dišalo po paličicah.", "paličica", [sense], target_word="paličicah"
    )
    assert ranked[0].score == 0.0


def test_idf_downweights_generic_words():
    """A word shared by many candidates must not outvote a distinctive one."""
    generic = [
        make(str(i), i, "splošno", collocations=("vplivalo",)) for i in range(1, 5)
    ]
    gold = make("10", 5, "fizikalna količina", collocations=("zviševanje temperature",))
    ranked = rank_candidates(
        "Zviševanje temperature je vplivalo na potek.",
        "zviševanje",
        [*generic, gold],
        target_word="zviševanje",
    )
    assert ranked[0].sense.sense_id == "10"


def test_tie_breaks_by_dictionary_order():
    ranked = rank_candidates(
        "cislo nic se ne ujema", "kos", kos_candidates(), target_word="kos"
    )
    assert [r.sense.sense_id for r in ranked] == ["10", "11"]
    assert all(r.score == 0.0 for r in ranked)


def test_stopwords_ignored():
    ranked = rank_candidates("kruha je in na v", "kos", kos_candidates(), target_word="kos")
    assert "kruha" in ranked[0].matched_collocations


def test_build_context_renders_same_block_format_as_c():
    text, shown, scores = build_context(
        "Kuhar je odrezal tanek kos kruha.", "kos", kos_candidates(), target_word="kos"
    )
    assert shown[0] == "10"
    assert "ID: 10" in text
    assert "Zveze: kos kruha" in text
    assert "Sopomenke: frtalja" in text  # relations shown like variant C
    assert scores[0]["sense_id"] == "10"
    assert scores[0]["score"] > 0


def test_context_degenerates_to_dictionary_order_without_matches():
    _, shown, _ = build_context("povsem nic", "kos", kos_candidates(), target_word="kos")
    assert shown == ["10", "11"]


def test_candidate_cap():
    _, shown, _ = build_context(
        "kruha", "kos", kos_candidates(), target_word="kos", max_candidates=1
    )
    assert shown == ["10"]


def test_synset_literals_signal():
    piece = make("10", 1, "del celote", synset_literals=("frtalja", "kolač"))
    bird = make("11", 2, "ptica")
    ranked = rank_candidates(
        "V pekarni so prodajali kolač.", "kos", [piece, bird], target_word="kos"
    )
    assert ranked[0].sense.sense_id == "10"
    assert "kolač" in ranked[0].matched_synset_literals


def test_hypernym_gloss_signal():
    piece = make("10", 1, "del celote")
    bird = make("11", 2, "ptica", hypernym_glosses=("vretenčar in ptica pevka",))
    ranked = rank_candidates(
        "Na drevesu je sedela ptica pevka.", "kos", [piece, bird], target_word="kos"
    )
    assert ranked[0].sense.sense_id == "11"
    assert "ptica" in ranked[0].matched_hypernym_glosses


def test_build_relation_context_adds_evidence_lines():
    text, shown, scores = build_relation_context(
        "vprašanje o odnosu",
        "kos",
        kos_candidates(),
        {"10": "Graf: ta pomen je sopomenka pomena 999."},
        target_word="kos",
    )
    assert shown == ["10", "11"]
    assert text.count("Graf:") == 1
    assert "Graf: ta pomen je sopomenka pomena 999." in text
    assert "ID: 10" in text and "ID: 11" in text


def test_build_relation_context_oracle_selects_gold_first():
    text, shown, _ = build_relation_context(
        "x",
        "kos",
        kos_candidates(),
        {},
        target_word="kos",
        gold_sense_id="11",
        max_candidates=1,
    )
    assert shown == ["11"]
    assert "Graf:" not in text


def test_build_relation_context_cap_keeps_ranking_order():
    _, shown, _ = build_relation_context(
        "x", "kos", kos_candidates(), {}, target_word="kos", max_candidates=1
    )
    assert shown == ["10"]


def test_build_relation_context_evidence_first():
    text, shown, scores = build_relation_context(
        "cislo nic se ne ujema",
        "kos",
        kos_candidates(),
        {"11": "Graf: ta pomen je sopomenka pomena 999."},
        target_word="kos",
    )
    assert shown == ["11", "10"]  # evidence-bearing candidate moves to the top
    assert text.index("ID: 11") < text.index("ID: 10")
    assert "Graf: ta pomen je sopomenka pomena 999." in text
