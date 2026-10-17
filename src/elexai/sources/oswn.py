"""OSWN 1.0 (WN-LMF) parsing: entries, synsets, glosses, relations.

Shared by the graph loader (Part B) and the re-link script (Part A). The lemma
unescaping mirrors the OSWN README substitution table (same map as the Phase-0
inspector).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SUBSTITUTIONS = {
    "--hy--": "-",
    "\u2212": "-",
    "--am--": "&",
    "--lt--": "<",
    "--gt--": ">",
    "--qt--": '"',
    "--ap--": "'",
    "_": " ",
    "--cm--": ",",
    "--ex--": "!",
    "\u200b": " ",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "--dt--": "\u2026",
    "--pc--": "%",
    "--pl--": "(",
    "--pr--": ")",
    "--do--": ".",
    "--ss--": "/",
    "--cl--": ":",
    "--qu--": "?",
    "`": "'",
    "--dg--": "\u00b0",
}


def unescape_form(text: str) -> str:
    for key in sorted(SUBSTITUTIONS, key=len, reverse=True):
        text = text.replace(key, SUBSTITUTIONS[key])
    return text


@dataclass
class OswnSense:
    sense_id: str
    synset_id: str


@dataclass
class OswnEntry:
    entry_id: str
    written_form: str  # unescaped
    pos: str
    senses: list[OswnSense] = field(default_factory=list)


@dataclass
class OswnSynset:
    synset_id: str
    ili: str | None
    pos: str | None
    gloss_en: str
    gloss_sl: str
    members: list[str]
    relations: list[tuple[str, str]] = field(default_factory=list)  # (relType, target)


def load_oswn(path: str | Path) -> tuple[list[OswnEntry], dict[str, OswnSynset]]:
    """Parse the OSWN XML into (lexical entries, synsets)."""
    entries: list[OswnEntry] = []
    synsets: dict[str, OswnSynset] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "LexicalEntry":
            lemma_el = el.find("{*}Lemma")
            entry = OswnEntry(
                entry_id=el.get("id") or "",
                written_form=unescape_form(
                    (lemma_el.get("writtenForm") or "") if lemma_el is not None else ""
                ),
                pos=(lemma_el.get("partOfSpeech") or "") if lemma_el is not None else "",
                senses=[
                    OswnSense(s.get("id") or "", s.get("synset") or "")
                    for s in el.findall("{*}Sense")
                ],
            )
            entries.append(entry)
            el.clear()
        elif tag == "Synset":
            gloss_en = gloss_sl = ""
            for definition in el.findall("{*}Definition"):
                language = definition.get("language")
                text = (definition.text or "").strip()
                if language == "en" and not gloss_en:
                    gloss_en = text
                if language == "sl" and not gloss_sl:
                    gloss_sl = text
            relations = [
                (rel.get("relType") or "", rel.get("target") or "")
                for rel in el.findall("{*}SynsetRelation")
            ]
            relations = [(rel, target) for rel, target in relations if rel and target]
            synset_id = el.get("id") or ""
            synsets[synset_id] = OswnSynset(
                synset_id=synset_id,
                ili=el.get("ili"),
                pos=el.get("partOfSpeech"),
                gloss_en=gloss_en,
                gloss_sl=gloss_sl,
                members=(el.get("members") or "").split(),
                relations=relations,
            )
            el.clear()
    return entries, synsets


def literals_for(synset: OswnSynset, entries_by_id: dict[str, OswnEntry], cap: int = 16) -> str:
    """Comma-joined surface forms of a synset's member entries (capped)."""
    forms = []
    for member in synset.members:
        entry = entries_by_id.get(member)
        if entry and entry.written_form:
            forms.append(entry.written_form)
        if len(forms) >= cap:
            break
    return ", ".join(forms)
