"""Eval harness — labeled fixtures, shared result schema, and per-eval scoring.

This package is the foundation for the eval suite. The labeled fixtures and
loader (`dataset.py`) and the shared result schema (`types.py`) live here;
the per-eval scoring modules (`categorize.py`, `rag.py`, `safety.py`,
`compare.py`) and the runner (`run.py`) land in T0033–T0037.
"""
