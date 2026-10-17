"""Tests for the sloWNet -> OSWN relation mapping (fixture XML, no network)."""

from __future__ import annotations

import textwrap

from elexai.sources.slownet import load_slownet_relations, oswn_id_from_slownet

FIXTURE = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <WN>
    <SYNSET>
    <ID>eng-30-00001740-a</ID>
    <POS>a</POS>
    <SYNONYM xml:lang="en"><LITERAL>able</LITERAL></SYNONYM>
    <ILR type="hypernym">eng-30-05616246-n</ILR>
    <ILR type="near_antonym">eng-30-00002098-a</ILR>
    </SYNSET>
    <SYNSET>
    <ID>eng-30-05616246-n</ID>
    <POS>n</POS>
    <ILR type="hypernym">not-a-pwn-id</ILR>
    </SYNSET>
    </WN>
    """
)


def test_id_transform():
    assert oswn_id_from_slownet("eng-30-00001740-a") == "oswn-00001740-a"
    assert oswn_id_from_slownet(" oswn-00001740-a ") == ""
    assert oswn_id_from_slownet("") == ""


def test_load_slownet_relations(tmp_path):
    path = tmp_path / "slownet.xml"
    path.write_text(FIXTURE, encoding="utf-8")
    relations = load_slownet_relations(path)

    assert set(relations) == {"oswn-00001740-a"}
    rels = relations["oswn-00001740-a"]
    assert ("hypernym", "oswn-05616246-n") in rels
    assert ("near_antonym", "oswn-00002098-a") in rels
    # the second synset has only a non-eng-30 target -> no relations recorded
    assert "oswn-05616246-n" not in relations
