import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User, Experiment, ExperimentQuery, ExperimentStatus, UserRole
from routers.auth import get_authenticated_user, require_role
from services.auth_service import log_action
from services.experiment_service import ExperimentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["Experiments"])


class ExperimentQueryIn(BaseModel):
    query_text: str = Field(..., min_length=1)
    expected_keywords: list[str] = Field(default_factory=list)


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    top_k: int = Field(5, ge=1, le=50)
    model_name: Optional[str] = None
    queries: list[ExperimentQueryIn] = Field(..., min_length=1)


class ExperimentQueryResponse(BaseModel):
    id: str
    query_text: str
    expected_keywords: list[str]
    recall_at_k: Optional[float]
    mrr: Optional[float]
    ndcg: Optional[float]
    latency_ms: Optional[float]
    retrieved_chunk_ids: Optional[list[str]]
    generated_answer: Optional[str]

    class Config:
        from_attributes = True


class ExperimentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    top_k: int
    model_name: Optional[str]
    recall_at_k: Optional[float]
    mrr: Optional[float]
    ndcg: Optional[float]
    avg_latency_ms: Optional[float]
    created_at: datetime
    finished_at: Optional[datetime]
    error_message: Optional[str]
    queries: list[ExperimentQueryResponse]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ExperimentResponse])
def list_experiments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.analyst)),
):
    return db.query(Experiment).order_by(Experiment.created_at.desc()).limit(100).all()


@router.post("/", response_model=ExperimentResponse, status_code=201)
def create_experiment(
    body: ExperimentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.analyst)),
):
    experiment = Experiment(
        name=body.name,
        description=body.description,
        created_by=current_user.id,
        top_k=body.top_k,
        model_name=body.model_name,
        status=ExperimentStatus.pending,
    )
    db.add(experiment)
    db.flush()

    for q in body.queries:
        db.add(ExperimentQuery(
            experiment_id=experiment.id,
            query_text=q.query_text,
            expected_keywords=q.expected_keywords,
        ))

    db.commit()
    db.refresh(experiment)
    log_action(db, current_user.id, "EXPERIMENT_CREATED", "experiment", experiment.id)
    logger.info("Experiment created", extra={
        "event": "experiment_created", "experiment_id": experiment.id,
        "experiment_name": experiment.name, "query_count": len(body.queries), "user_id": current_user.id,
    })
    return experiment


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.analyst)),
):
    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@router.post("/{experiment_id}/run", response_model=ExperimentResponse)
def run_experiment(
    experiment_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.analyst)),
):
    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if exp.status == ExperimentStatus.running:
        raise HTTPException(status_code=409, detail="Experiment is already running — wait for it to finish or restart the API to reset it")

    log_action(db, current_user.id, "EXPERIMENT_RUN", "experiment", experiment_id)
    logger.info("Experiment run triggered", extra={
        "event": "experiment_run_triggered", "experiment_id": experiment_id, "user_id": current_user.id,
    })

    def _run():
        from database import SessionLocal
        session = SessionLocal()
        try:
            ExperimentService(session).run(experiment_id)
        except Exception as e:
            logger.error("Background experiment task crashed", extra={
                "event": "experiment_background_crashed",
                "experiment_id": experiment_id,
                "error": str(e),
            }, exc_info=True)
        finally:
            session.close()

    background_tasks.add_task(_run)
    exp.status = ExperimentStatus.running
    db.commit()
    db.refresh(exp)
    return exp


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(
    experiment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.analyst)),
):
    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    db.delete(exp)
    db.commit()
    log_action(db, current_user.id, "EXPERIMENT_DELETED", "experiment", experiment_id)
    logger.info("Experiment deleted", extra={
        "event": "experiment_deleted", "experiment_id": experiment_id, "user_id": current_user.id,
    })
