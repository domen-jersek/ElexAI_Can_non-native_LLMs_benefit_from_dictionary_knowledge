"""Neo4j-backed neighborhood retrieval for variant D (graph RAG).

Same candidate universe and same context rendering as variant C - the only
difference is the ORDER: candidates are ranked by how well the sentence matches
each sense's neighborhood (definitions, synonyms, typical collocations), which
this retriever pulls from the graph. The ``neo4j`` driver is imported lazily so
that the rest of the pipeline runs without a database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elexai.config import GraphConfig
from elexai.graph.ranking import GraphSense, build_context

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


@dataclass
class GraphContext:
    text: str
    shown_sense_ids: list[str]
    scores: list[dict]  # full ranking: [{sense_id, score, matched_*...}]


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

    def close(self) -> None:
        self.driver.close()
