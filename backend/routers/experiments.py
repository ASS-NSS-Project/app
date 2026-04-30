# TODO: Experiments feature is not yet implemented.
# This router is registered but returns 501 for all endpoints.

from fastapi import APIRouter

router = APIRouter(prefix="/experiments", tags=["Experiments"])


# TODO: implement experiment CRUD and run endpoints
# Planned endpoints:
#   GET    /experiments/          — list all experiments
#   POST   /experiments/          — create experiment with query set
#   GET    /experiments/{id}      — get experiment + per-query results
#   POST   /experiments/{id}/run  — run experiment in background
#   DELETE /experiments/{id}      — delete experiment
