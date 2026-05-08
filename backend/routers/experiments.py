"""
routers/experiments.py - Batch RAG benchmarking endpoints (not yet implemented)

This router is registered in main.py and appears in the OpenAPI spec, but all
endpoints are planned for a future milestone. The file exists so that:
- The frontend can already reference /experiments paths without a 404.
- The router prefix and tag appear in /docs for documentation purposes.
- Planned endpoint shapes are documented here for the developer who implements them.

Planned endpoints:
  GET    /experiments/          — list all experiments (paginated)
  POST   /experiments/          — create an experiment with a named query set
  GET    /experiments/{id}      — get one experiment plus all per-query results
  POST   /experiments/{id}/run  — run the experiment in the background worker
  DELETE /experiments/{id}      — delete the experiment and its query rows

An experiment consists of:
- A name and optional description.
- A set of ExperimentQuery rows, each with a query_text and expected_keywords.
- After running: per-query metrics (Recall@k, MRR, nDCG, latency_ms) and
  aggregate statistics stored on the Experiment row.

See services/experiment.py for the planned ExperimentService implementation.
"""
from fastapi import APIRouter

# All routes here will be grouped under /experiments in the OpenAPI spec.
router = APIRouter(prefix="/experiments", tags=["Experiments"])

# TODO: implement experiment CRUD and run endpoints
# Planned endpoints:
#   GET    /experiments/          — list all experiments
#   POST   /experiments/          — create experiment with query set
#   GET    /experiments/{id}      — get experiment + per-query results
#   POST   /experiments/{id}/run  — run experiment in background
#   DELETE /experiments/{id}      — delete experiment
