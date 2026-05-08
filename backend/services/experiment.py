"""
services/experiment.py - Batch RAG benchmarking service (not yet implemented)

This module is a placeholder for the ExperimentService that will run batch
evaluation of the RAG pipeline against a curated query set.

Planned design:
  ExperimentService.run(experiment_id) iterates over ExperimentQuery rows
  associated with the given experiment, calls the RAG pipeline for each query,
  and computes retrieval quality metrics:

  - Recall@k  — fraction of expected_keywords found in the top-k retrieved chunks.
  - MRR       — Mean Reciprocal Rank; how early in the ranking the first relevant
                chunk appears (1/rank, averaged over all queries).
  - nDCG      — Normalized Discounted Cumulative Gain; ranking quality accounting
                for position (results ranked higher contribute more to the score).
  - avg_latency_ms — mean end-to-end query time including embedding + Qdrant search.

The results are written back to the Experiment row (recall_at_k, mrr, ndcg,
avg_latency_ms) and individual ExperimentQuery rows get per-query metrics.

This service is intentionally stubbed to avoid blocking the router registration
in main.py. When implemented, import ExperimentService in routers/experiments.py.
"""

# TODO: Experiments feature is not yet implemented.
#
# Planned: ExperimentService.run(experiment_id) iterates over
# ExperimentQuery rows, calls the RAG pipeline for each query,
# and computes Recall@k, MRR, and nDCG against expected_keywords.
