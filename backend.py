"""Learning Pathfinder REST API.

A thin HTTP transport over `engine.service`. All business logic lives in the
service layer so this and the Streamlit app (`streamlit_app.py`) behave
identically rather than drifting into two implementations of the same rules.
"""

import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine import service, store
from engine.recommender import RecommenderError, extract_profile
from engine.retrieval import CourseIndex
from engine.service import ServiceError

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY not set. Copy .env.example to .env and add your key."
    )

GROQ_MODEL = service.get_model()

# Wildcard origins and credentials are mutually exclusive in the CORS spec, so
# list the dev origins explicitly and keep credentials working.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",") if o.strip()
]

app = FastAPI(title="Learning Pathfinder API", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = service.build_client(GROQ_API_KEY)
index = CourseIndex()
store.init_db()


# -- schemas ----------------------------------------------------------------

class ProfileIn(BaseModel):
    name: str = "Learner"
    experience_level: str = "beginner"
    learning_style: str = "hands-on"
    goals: str = ""
    interests: str = ""
    completed_learning: str = ""
    weekly_hours: int = 8


class ProfilePatch(BaseModel):
    name: Optional[str] = None
    experience_level: Optional[str] = None
    learning_style: Optional[str] = None
    goals: Optional[str] = None
    interests: Optional[str] = None
    completed_learning: Optional[str] = None
    weekly_hours: Optional[int] = None


class DescribeIn(BaseModel):
    text: str = Field(min_length=3)


class SkillIn(BaseModel):
    skill: str
    source: str = "manual"


class FeedbackIn(BaseModel):
    signal: str
    course_id: Optional[str] = None
    comment: str = ""


class CompleteIn(BaseModel):
    completed: bool = True


class ChatIn(BaseModel):
    message: str = Field(min_length=1)


class AttemptIn(BaseModel):
    answers: List[int] = []


class AdaptIn(BaseModel):
    note: str = ""
    drop_courses: List[str] = []


# -- helpers ----------------------------------------------------------------

NOT_FOUND_HINTS = ("not found", "no such", "not in the active path",
                   "no path generated")
BAD_REQUEST_HINTS = ("before taking", "no feedback recorded",
                     "no path to adapt", "has no courses")


def _svc(fn, *args, **kwargs):
    """Run a service call, mapping ServiceError onto an HTTP status."""
    try:
        return fn(*args, **kwargs)
    except ServiceError as exc:
        message = str(exc)
        low = message.lower()
        if any(h in low for h in NOT_FOUND_HINTS):
            raise HTTPException(404, message)
        if any(h in low for h in BAD_REQUEST_HINTS):
            raise HTTPException(400, message)
        raise HTTPException(422, message)


def _learner_or_404(learner_id: int):
    learner = store.get_learner(learner_id)
    if learner is None:
        raise HTTPException(404, "Learner %s not found" % learner_id)
    return learner


# -- meta -------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Learning Pathfinder API",
        "model": GROQ_MODEL,
        "catalog_courses": len(index.courses),
        "known_roles": len(index.roles),
    }


@app.get("/api/catalog")
def catalog(q: str = "", limit: int = 20):
    """Browse or search the course corpus directly."""
    if q:
        return {"results": index.search(q, top_k=limit)}
    return {"results": index.courses[:limit], "total": len(index.courses)}


# -- conversational intake --------------------------------------------------

@app.post("/api/profile/extract")
def profile_extract(body: DescribeIn):
    """Turn a free-text self-description into a structured profile."""
    try:
        profile = extract_profile(client, GROQ_MODEL, body.text)
    except RecommenderError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, "Profile extraction failed: %s" % exc)
    return {"profile": profile, "skill_gap_preview": index.skill_gap(profile)}


# -- learners ---------------------------------------------------------------

@app.post("/api/learners", status_code=201)
def create_learner(body: ProfileIn):
    return store.get_learner(store.create_learner(body.model_dump()))


@app.get("/api/learners")
def list_learners():
    return {"learners": store.list_learners()}


@app.get("/api/learners/{learner_id}")
def get_learner(learner_id: int):
    return _learner_or_404(learner_id)


@app.patch("/api/learners/{learner_id}")
def patch_learner(learner_id: int, body: ProfilePatch):
    _learner_or_404(learner_id)
    return store.update_learner(
        learner_id, {k: v for k, v in body.model_dump().items() if v is not None}
    )


# -- paths ------------------------------------------------------------------

@app.post("/api/learners/{learner_id}/generate-path")
def generate(learner_id: int):
    learner = _learner_or_404(learner_id)
    if not learner["goals"]:
        raise HTTPException(400, "Set a goal on the profile before generating a path.")
    return _svc(service.generate_and_store, client, index, learner)


@app.post("/api/learners/{learner_id}/adapt-path")
def adapt(learner_id: int, body: AdaptIn):
    """Regenerate the path taking accumulated feedback into account."""
    learner = _learner_or_404(learner_id)
    return _svc(service.adapt, client, index, learner, body.note)


@app.get("/api/learners/{learner_id}/path")
def get_path(learner_id: int):
    _learner_or_404(learner_id)
    payload = service.active_path(index, learner_id)
    if payload is None:
        raise HTTPException(404, "No path generated yet.")
    return payload


@app.get("/api/learners/{learner_id}/paths")
def path_history(learner_id: int):
    _learner_or_404(learner_id)
    return {"paths": store.list_paths(learner_id)}


@app.post("/api/path-courses/{path_course_id}/complete")
def complete_course(path_course_id: int, body: CompleteIn):
    """Mark a course done. Its skills are credited to the learner."""
    return _svc(service.complete_course, index, path_course_id, body.completed)


# -- skills -----------------------------------------------------------------

@app.get("/api/learners/{learner_id}/skills")
def list_skills(learner_id: int):
    _learner_or_404(learner_id)
    return {"skills": store.get_skills(learner_id)}


@app.post("/api/learners/{learner_id}/skills", status_code=201)
def add_skill(learner_id: int, body: SkillIn):
    _learner_or_404(learner_id)
    skill = store.add_skill(learner_id, body.skill, body.source)
    if skill is None:
        raise HTTPException(400, "Skill cannot be empty")
    return {"skill": skill}


@app.delete("/api/learners/{learner_id}/skills/{skill}")
def delete_skill(learner_id: int, skill: str):
    _learner_or_404(learner_id)
    store.remove_skill(learner_id, skill)
    return {"removed": skill}


# -- feedback ---------------------------------------------------------------

@app.post("/api/learners/{learner_id}/feedback", status_code=201)
def add_feedback(learner_id: int, body: FeedbackIn):
    _learner_or_404(learner_id)
    allowed = {"too_easy", "too_hard", "not_relevant", "helpful", "note"}
    if body.signal not in allowed:
        raise HTTPException(400, "signal must be one of %s" % sorted(allowed))
    path = store.get_active_path(learner_id)
    fid = store.add_feedback(
        learner_id, body.signal, path_id=path["id"] if path else None,
        course_id=body.course_id, comment=body.comment,
    )
    return {"id": fid, "signal": body.signal}


@app.get("/api/learners/{learner_id}/feedback")
def list_feedback(learner_id: int):
    _learner_or_404(learner_id)
    return {"feedback": store.get_feedback(learner_id)}


# -- assessments ------------------------------------------------------------

@app.get("/api/learners/{learner_id}/assessments")
def list_assessments(learner_id: int):
    """Checkpoint status for every milestone in the active path."""
    _learner_or_404(learner_id)
    if store.get_active_path(learner_id) is None:
        raise HTTPException(404, "No path generated yet.")
    return {"assessments": service.assessment_status(index, learner_id)}


@app.post("/api/learners/{learner_id}/assessments/{milestone_index}")
def create_assessment(learner_id: int, milestone_index: int,
                      regenerate: bool = False):
    """Generate (or return) the checkpoint for one milestone."""
    learner = _learner_or_404(learner_id)
    return _svc(service.get_or_create_assessment, client, index, learner,
                milestone_index, regenerate)


@app.post("/api/assessments/{assessment_id}/submit")
def submit_assessment(assessment_id: int, body: AttemptIn):
    """Grade server-side and credit skills only on a pass."""
    return _svc(service.submit_assessment, assessment_id, body.answers)


# -- dashboard --------------------------------------------------------------

@app.get("/api/learners/{learner_id}/dashboard")
def dashboard(learner_id: int):
    """Everything the progress view needs, computed server-side."""
    _learner_or_404(learner_id)
    data = _svc(service.dashboard, index, learner_id)
    # REST clients fetch the full path from /path; keep this payload lean.
    data.pop("path", None)
    return data


# -- assistant --------------------------------------------------------------

@app.post("/api/learners/{learner_id}/chat")
def chat(learner_id: int, body: ChatIn):
    learner = _learner_or_404(learner_id)
    try:
        return {"response": service.chat(client, index, learner, body.message)}
    except ServiceError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/learners/{learner_id}/chat")
def chat_history(learner_id: int, limit: int = 30):
    _learner_or_404(learner_id)
    return {"messages": store.get_messages(learner_id, limit=limit)}


@app.get("/api/learners/{learner_id}/explain/{course_id}")
def explain(learner_id: int, course_id: str):
    """Structured 'why this course' for a single recommendation."""
    learner = _learner_or_404(learner_id)
    return _svc(service.explain, index, learner, course_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
