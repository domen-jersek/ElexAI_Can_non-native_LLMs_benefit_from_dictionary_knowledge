"""Registry of known data sources: provenance, licensing and download info.

Consumed by ``scripts/download_data.py`` (fetch what is missing) and
``scripts/register_data.py`` (hash everything into ``data/MANIFEST.json``).
``subdir`` is the folder under ``data/raw/`` that holds the source.

Keep this file factual: every URL/checksum here was taken from the upstream
record (CLARIN.SI item pages, CJVT wiki) at the time of writing - see
docs/DATA.md for what each source actually contains.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    authors: str
    issued: str
    license: str
    subdir: str
    handle: str | None = None
    download_url: str | None = None
    download_name: str | None = None
    md5: str | None = None
    notes: str = ""


SOURCES: dict[str, SourceSpec] = {
    s.source_id: s
    for s in [
        SourceSpec(
            source_id="ddds_dump",
            title="Digital Dictionary Database of Slovene (DDDS) - PostgreSQL backup v3.68",
            authors="Centre for Language Resources and Technologies (CJVT), University of Ljubljana",
            issued="2026-10-07",
            license=(
                "Not stated on the distribution page - internal research use only; "
                "do NOT redistribute raw files (see docs/DATA.md)"
            ),
            subdir="gigabaza-003-068-2026q",
            handle=None,
            download_url="https://nas.cjvt.si/s/gTQjMiKzD53yxyd",
            notes=(
                "Listed as 'Database dump v3.68 (07.10.2026)' on the CJVT wiki page "
                "'Domain and data model links' "
                "(https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/domain-and-data-model-links). "
                "PostgreSQL 15.6 directory-format dump (pg_dump 15.8). Contains internal "
                "Django/admin/editor tables as well; the restore script excludes those."
            ),
        ),
        SourceSpec(
            source_id="oswn",
            title="Open Slovene WordNet OSWN 1.0",
            authors="Cibej, Jaka; Tercon, Luka; Krek, Simon; et al.",
            issued="2023-11-10",
            license="CC BY-SA 4.0",
            subdir="open_slovene_wordnet_1.0",
            handle="http://hdl.handle.net/11356/1888",
            download_url=(
                "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/1888/"
                "open_slovene_wordnet_1.0.zip?sequence=3&isAllowed=y"
            ),
            download_name="open_slovene_wordnet_1.0.zip",
            md5="22a24fb246e092794715d664a7b07430",
        ),
        SourceSpec(
            source_id="oswn_ddds_link",
            title="List of Linked Senses from OSWN and DDDS 1.0",
            authors="Cibej, Jaka; Krek, Simon; Laskowski, Cyprian; Bombek, Miha",
            issued="2023-11-10",
            license="CC BY 4.0",
            subdir="oswn_ddds_linked_senses",
            handle="http://hdl.handle.net/11356/1897",
            download_url=(
                "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/1897/"
                "oswn_ddds_linked_senses.zip?sequence=5&isAllowed=y"
            ),
            download_name="oswn_ddds_linked_senses.zip",
            md5="d7c98728a15ecbd1501a55c42290599a",
        ),
        SourceSpec(
            source_id="slownet",
            title="Semantic lexicon of Slovene sloWNet 3.1",
            authors="Fiser, Darja",
            issued="2015-05-07",
            license="CC BY-SA 4.0",
            subdir="slownet",
            handle="http://hdl.handle.net/11356/1026",
            download_url=(
                "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/1026/"
                "slownet.zip?sequence=9&isAllowed=y"
            ),
            download_name="slownet.zip",
            md5="15a34fb556ddda0d7f47d99ded114c50",
            notes=(
                "Not used as the pilot dictionary: only 3,177 of 117,658 synsets have "
                "Slovene definitions (and 4,390 Slovene usage sentences). Kept for reference."
            ),
        ),
        SourceSpec(
            source_id="sloleks",
            title="Morphological Lexicon of Slovene Sloleks 3.1",
            authors="Cibej, Jaka; et al.",
            issued="2026-02-03",
            license="CC BY-SA 4.0",
            subdir="sloleks",
            handle="http://hdl.handle.net/11356/2080",
            download_url=(
                "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/2080/"
                "Sloleks.3.1.zip?sequence=1&isAllowed=y"
            ),
            download_name="Sloleks.3.1.zip",
            md5="26dc6adcb250d827f94b287201ee9bf7",
            notes="Used for lemmatization of question sentences only (later phases).",
        ),
        SourceSpec(
            source_id="oewn",
            title="Open English WordNet 2023 (auxiliary: synset relations for the graph hierarchy)",
            authors="Open English WordNet Team (based on Princeton WordNet)",
            issued="2023-10-31",
            license="CC BY 4.0 (plus the Princeton WordNet license)",
            subdir="oewn",
            handle=None,
            download_url=(
                "https://github.com/globalwordnet/english-wordnet/releases/download/"
                "2023-edition/english-wordnet-2023.xml.gz"
            ),
            download_name="english-wordnet-2023.xml.gz",
            notes=(
                "Used for the WordNet hierarchy in the knowledge graph: OSWN synset ids "
                "are OEWN ids with a swapped prefix (verified 95,247/95,262). The .gz "
                "archive stays in data/raw/_downloads/ and is not hash-tracked."
            ),
        ),
    ]
}
