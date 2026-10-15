"""ELEXAI pilot.

Comparing, on one dictionary (DDDS) and one question type (sense
disambiguation of polysemous words):

- variant A: base LLM, no external sources
- variant B: same LLM + text RAG over dictionary senses
- variant C: same LLM + graph RAG (DDDS + Open Slovene WordNet in Neo4j)

Same LLM, same questions, same prompts; only the retrieved context differs.
See docs/DECISIONS.md for the decisions behind the pipeline and
docs/DATA.md for what each source contains.
"""

__version__ = "0.1.0"
