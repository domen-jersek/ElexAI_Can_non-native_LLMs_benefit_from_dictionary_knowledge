"""Tests for the OSWN parsing helpers (fixture XML, no network)."""

from __future__ import annotations

import textwrap

from elexai.sources.oswn import literals_for, load_oswn, unescape_form

FIXTURE = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <LexicalResource xmlns:dc="https://globalwordnet.github.io/schemas/dc/">
    <Lexicon id="t" label="t" language="sl" email="e@e" license="x">
    <LexicalEntry id="oswn-kos-Som-n">
    <Lemma partOfSpeech="n" writtenForm="kos"/>
    <Sense id="oswn-kos-Som-n__1" synset="oswn-1-n"/>
    <Sense id="oswn-kos-Som-n__2" synset="oswn-2-n"/>
    </LexicalEntry>
    <LexicalEntry id="oswn-gnezdo-Son-n">
    <Lemma partOfSpeech="n" writtenForm="gnezdo"/>
    <Sense id="oswn-gnezdo-Son-n__1" synset="oswn-1-n"/>
    </LexicalEntry>
    <LexicalEntry id="oswn-x--hy--y-Son-n">
    <Lemma partOfSpeech="n" writtenForm="x--hy--y"/>
    <Sense id="oswn-x--hy--y-Son-n__1" synset="oswn-3-n"/>
    </LexicalEntry>
    <Synset id="oswn-1-n" ili="i1" members="oswn-kos-Som-n oswn-gnezdo-Son-n" partOfSpeech="n">
    <Definition language="en" status="manual">a nest</Definition>
    <Definition language="sl" status="machine_translated">gnezdo</Definition>
    <SynsetRelation relType="hypernym" target="oswn-9-n"/>
    <SynsetRelation relType="part_holonym" target="oswn-8-n"/>
    </Synset>
    <Synset id="oswn-2-n" ili="i2" members="oswn-kos-Som-n" partOfSpeech="n">
    <Definition language="en" status="manual">blackbird</Definition>
    </Synset>
    <Synset id="oswn-3-n" ili="i3" members="oswn-x--hy--y-Son-n" partOfSpeech="n"/>
    </Lexicon>
    </LexicalResource>
    """
)


def test_unescape_form():
    assert unescape_form("x--hy--y") == "x-y"
    assert unescape_form("a_b") == "a b"


def test_load_oswn_entries_and_synsets(tmp_path):
    path = tmp_path / "oswn.xml"
    path.write_text(FIXTURE, encoding="utf-8")
    entries, synsets = load_oswn(path)

    assert len(entries) == 3
    kos = next(e for e in entries if e.entry_id == "oswn-kos-Som-n")
    assert kos.written_form == "kos"
    assert kos.pos == "n"
    assert [s.synset_id for s in kos.senses] == ["oswn-1-n", "oswn-2-n"]

    nest = synsets["oswn-1-n"]
    assert nest.ili == "i1"
    assert nest.gloss_en == "a nest"
    assert nest.gloss_sl == "gnezdo"
    assert nest.members == ["oswn-kos-Som-n", "oswn-gnezdo-Son-n"]
    assert ("hypernym", "oswn-9-n") in nest.relations
    assert ("part_holonym", "oswn-8-n") in nest.relations

    # escaped lemma unescaped in the entry
    assert any(e.written_form == "x-y" for e in entries)

    entries_by_id = {e.entry_id: e for e in entries}
    assert literals_for(synsets["oswn-1-n"], entries_by_id) == "kos, gnezdo"
