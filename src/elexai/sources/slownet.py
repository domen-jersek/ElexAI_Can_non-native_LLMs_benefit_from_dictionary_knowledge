"""sloWNet 3.1 parsing: synset hierarchy relations keyed to OSWN synset ids.

OSWN 1.0 ships synsets, glosses, literals and ILI ids but **no inter-synset
relations** (verified 2026-10-17: zero ``SynsetRelation`` elements). sloWNet
3.1, however, contains the full Princeton WordNet 3.0 relation graph (ILR
elements), and its synset ids (``eng-30-XXXXXXXX-p``) share the PWN offset
format with OSWN ids (``oswn-XXXXXXXX-p``), so the relations map 1:1 by id.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_PREFIX = "eng-30-"


def oswn_id_from_slownet(slownet_id: str) -> str:
    """``eng-30-00001740-a`` -> ``oswn-00001740-a`` (empty if not an eng-30 id)."""
    slownet_id = (slownet_id or "").strip()
    if slownet_id.startswith(_PREFIX):
        return "oswn-" + slownet_id[len(_PREFIX) :]
    return ""


def load_slownet_relations(path: str | Path) -> dict[str, list[tuple[str, str]]]:
    """Map sloWNet ILR relations onto OSWN synset ids.

    Returns ``{oswn_synset_id: [(rel_type, target_oswn_synset_id), ...]}``.
    Relation names are passed through as-is (the loader sanitizes them).
    """
    relations: dict[str, list[tuple[str, str]]] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "SYNSET":
            continue
        synset_id = oswn_id_from_slownet(el.findtext("ID") or "")
        if synset_id:
            out: list[tuple[str, str]] = []
            for ilr in el.findall("ILR"):
                rel_type = ilr.get("type") or ""
                target = oswn_id_from_slownet(ilr.text or "")
                if rel_type and target:
                    out.append((rel_type, target))
            if out:
                relations[synset_id] = out
        el.clear()
    return relations
