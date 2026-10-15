"""Source adapters: one per lexicographic dataset (DDDS, OSWN, ...).

Adapters normalize a concrete source into a common stream of sense records so
that retrieval, graph building and evaluation never depend on a specific file
format or database schema. See `base.py` for the interface and `catalog.py`
for the registry of known sources and their provenance.
"""
