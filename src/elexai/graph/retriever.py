"""Neo4j-backed neighborhood retrieval for variant D (graph RAG).

Same candidate universe and same context rendering as variant C - the only
difference is the ORDER: candidates are ranked by how well the sentence matches
each sense's neighborhood (definitions, synonyms, typical collocations), which
this retriever pulls from the graph. The ``neo4j`` driver is imported lazily so
that the rest of the pipeline runs without a database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from elexai.config import GraphConfig
from elexai.graph.ranking import GraphSense, build_context, build_relation_context

if TYPE_CHECKING:  # pragma: no cover - typing only
    from neo4j import Driver

_SENSES_Q = """
MATCH (l:Lexeme)-[:HAS_SENSE]->(s:Sense)
WHERE l.lemma = $lemma
RETURN s.id AS sense_id, s.position AS position, s.indicator AS indicator,
       s.definition AS definition, s.lu_type AS lu_type,
       coalesce(s.example_count, 0) AS example_count, l.pos AS pos
"""

_COLLOCATIONS_Q = """
MATCH (l:Lexeme)-[:HAS_SENSE]->(s:Sense)-[:COLLOCATES_WITH]->(p:Phrase)
WHERE l.lemma = $lemma
RETURN s.id AS sense_id, collect(DISTINCT p.form) AS forms
"""

_SYNSET_Q = """
MATCH (l:Lexeme)-[:HAS_SENSE]->(s:Sense)-[:IN_SYNSET]->(y:Synset)
WHERE l.lemma = $lemma
OPTIONAL MATCH (y)-[:HYPERNYM|INSTANCE_HYPERNYM]->(hy:Synset)
RETURN s.id AS sense_id,
       collect(DISTINCT y.literals) AS literals,
       collect(DISTINCT hy.gloss_sl) AS hypernym_glosses
"""

_SYNONYMS_Q = """
MATCH (l:Lexeme)-[:HAS_SENSE]->(s:Sense)-[:SYNONYM]->(o:Sense)
WHERE l.lemma = $lemma
OPTIONAL MATCH (ol:Lexeme)-[:HAS_SENSE]->(o)
RETURN s.id AS sense_id, o.id AS other_id, ol.lemma AS other_lemma
"""

# --- relation-question evidence (D-022): which candidate senses of $lemma
# stand in the asked relation to the given sense $rid? -----------------------

_REL_EVIDENCE_LABELS = {
    "synonym": "sopomenka",
    "antonym": "protipomenka",
    "hypernym": "nadpomenka",
    "hyponym": "podpomenka",
}

_REL_EVIDENCE_Q: dict[str, list[str]] = {
    "synonym": [
        # dictionary-native sense-to-sense synonym edge (either direction)
        """
MATCH (r:Sense {id: $rid})-[:SYNONYM]-(c:Sense)<-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
        # WordNet: both senses linked to the same synset
        """
MATCH (r:Sense {id: $rid})-[:IN_SYNSET]->(y:Synset)<-[:IN_SYNSET]-(c:Sense)
      <-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
    ],
    "antonym": [
        """
MATCH (r:Sense {id: $rid})-[:ANTONYM]-(c:Sense)<-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
        """
MATCH (r:Sense {id: $rid})-[:IN_SYNSET]->(y1:Synset)-[:ANTONYM]-(y2:Synset)
      <-[:IN_SYNSET]-(c:Sense)<-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
    ],
    "hypernym": [
        # the candidate's synset is a direct hypernym of the given sense's synset
        """
MATCH (r:Sense {id: $rid})-[:IN_SYNSET]->(y1:Synset)
      -[:HYPERNYM|INSTANCE_HYPERNYM]->(y2:Synset)<-[:IN_SYNSET]-(c:Sense)
      <-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
    ],
    "hyponym": [
        """
MATCH (r:Sense {id: $rid})-[:IN_SYNSET]->(y1:Synset)
      <-[:HYPERNYM|INSTANCE_HYPERNYM]-(y2:Synset)<-[:IN_SYNSET]-(c:Sense)
      <-[:HAS_SENSE]-(l:Lexeme {lemma: $lemma})
RETURN DISTINCT c.id AS sense_id
""",
    ],
}


@dataclass
class GraphContext:
    text: str
    shown_sense_ids: list[str]
    scores: list[dict]  # full ranking: [{sense_id, score, matched_*...}]
    evidence_sense_ids: list[str] = field(default_factory=list)


class GraphRetriever:
    def __init__(self, driver: Driver, cfg: GraphConfig):
        self.driver = driver
        self.cfg = cfg

    @staticmethod
    def from_env(cfg: GraphConfig) -> GraphRetriever:
        try:
            from neo4j import GraphDatabase  # lazy: only needed for variant D
        except ImportError as exc:  # pragma: no cover
            raise ConnectionError("the 'neo4j' package is not installed") from exc
        uri = os.environ.get(cfg.uri_env) or cfg.default_uri
        user = os.environ.get(cfg.user_env, "neo4j")
        password = os.environ.get(cfg.password_env, "")
        if not password:
            raise ConnectionError(f"environment variable {cfg.password_env!r} is not set")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            driver.close()
            raise ConnectionError(f"cannot reach Neo4j at {uri}: {exc}") from exc
        return GraphRetriever(driver, cfg)

    def _fetch(self, lemma: str) -> list[GraphSense]:
        with self.driver.session() as session:
            sense_rows = {row["sense_id"]: row for row in session.run(_SENSES_Q, lemma=lemma)}
            collocations: dict[Any, list[str]] = {
                row["sense_id"]: [f for f in row["forms"] if f]
                for row in session.run(_COLLOCATIONS_Q, lemma=lemma)
            }
            synonyms: dict[Any, list[tuple[str, str]]] = {}
            for row in session.run(_SYNONYMS_Q, lemma=lemma):
                if row["other_id"] is not None:
                    synonyms.setdefault(row["sense_id"], []).append(
                        (str(row["other_id"]), row["other_lemma"] or "")
                    )
            synset_literals: dict[Any, list[str]] = {}
            hypernym_glosses: dict[Any, list[str]] = {}
            if self.cfg.use_synsets:
                for row in session.run(_SYNSET_Q, lemma=lemma):
                    synset_literals[row["sense_id"]] = sorted(
                        {
                            word.strip()
                            for chunk in row["literals"]
                            if chunk
                            for word in chunk.split(",")
                            if word.strip()
                        }
                    )
                    hypernym_glosses[row["sense_id"]] = sorted(
                        {g for g in row["hypernym_glosses"] if g}
                    )
        out: list[GraphSense] = []
        for sid, row in sense_rows.items():
            out.append(
                GraphSense(
                    sense_id=str(sid),
                    lemma=lemma,
                    pos=row["pos"],
                    position=row["position"],
                    indicator=row["indicator"] or "",
                    definition=row["definition"] or "",
                    example_count=int(row["example_count"] or 0),
                    lu_type=row["lu_type"],
                    synonyms=sorted(set(synonyms.get(sid, []))),
                    collocations=sorted(set(collocations.get(sid, []))),
                    synset_literals=synset_literals.get(sid, []),
                    hypernym_glosses=hypernym_glosses.get(sid, []),
                )
            )
        return out

    def context_for(self, lemma: str, sentence: str) -> GraphContext:
        candidates = self._fetch(lemma)
        text, shown_ids, scores = build_context(
            sentence,
            lemma,
            candidates,
            max_candidates=self.cfg.max_candidates,
            synonyms_shown=self.cfg.synonyms_shown,
            collocations_shown=self.cfg.collocations_shown,
            weight_definition=self.cfg.weight_definition,
            weight_collocation=self.cfg.weight_collocation,
            weight_synonym=self.cfg.weight_synonym,
            weight_synset_literal=self.cfg.weight_synset_literal if self.cfg.use_synsets else 0.0,
            weight_hypernym_gloss=self.cfg.weight_hypernym_gloss if self.cfg.use_synsets else 0.0,
        )
        return GraphContext(text=text, shown_sense_ids=shown_ids, scores=scores)

    def _relation_evidence(self, lemma: str, related_sense_id: int, relation: str) -> set[str]:
        """Sense ids of ``lemma`` that stand in ``relation`` to the given sense."""
        queries = _REL_EVIDENCE_Q.get(relation)
        if queries is None:
            raise ValueError(f"unknown relation {relation!r}")
        found: set[str] = set()
        with self.driver.session() as session:
            for query in queries:
                for row in session.run(query, rid=related_sense_id, lemma=lemma):
                    found.add(str(row["sense_id"]))
        return found

    def relation_context_for(
        self,
        lemma: str,
        related_sense_id: str,
        relation: str,
        *,
        sentence: str,
        gold_sense_id: str | None = None,
        max_candidates: int | None = None,
    ) -> GraphContext:
        """Context for a relation question: candidate blocks of ``lemma`` plus an
        explicit graph evidence line for candidates linked to ``related_sense_id``.

        With ``gold_sense_id`` set the gold sense + nearest siblings are shown
        (oracle semantics, same evidence); otherwise candidates are ranked by
        ``sentence`` (the question text) like in variant D.
        """
        label = _REL_EVIDENCE_LABELS.get(relation)
        if label is None:
            raise ValueError(f"unknown relation {relation!r}")
        evidence_ids = self._relation_evidence(lemma, int(related_sense_id), relation)
        evidence = {
            sid: f"Graf: ta pomen je {label} pomena {related_sense_id}."
            for sid in evidence_ids
        }
        candidates = self._fetch(lemma)
        text, shown_ids, scores = build_relation_context(
            sentence,
            lemma,
            candidates,
            evidence,
            max_candidates=max_candidates or self.cfg.max_candidates,
            synonyms_shown=self.cfg.synonyms_shown,
            collocations_shown=self.cfg.collocations_shown,
            gold_sense_id=gold_sense_id,
            weight_definition=self.cfg.weight_definition,
            weight_collocation=self.cfg.weight_collocation,
            weight_synonym=self.cfg.weight_synonym,
            weight_synset_literal=self.cfg.weight_synset_literal if self.cfg.use_synsets else 0.0,
            weight_hypernym_gloss=self.cfg.weight_hypernym_gloss if self.cfg.use_synsets else 0.0,
        )
        return GraphContext(
            text=text,
            shown_sense_ids=shown_ids,
            scores=scores,
            evidence_sense_ids=sorted(evidence_ids),
        )

    def close(self) -> None:
        self.driver.close()
