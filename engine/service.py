"""Application service layer.

Holds the orchestration that sits between the engine primitives and whatever is
driving them. Both entry points use this and neither owns business logic:

  backend.py       FastAPI  -> HTTP transport over these functions
  streamlit_app.py Streamlit -> direct in-process calls to the same functions

Keeping it here is what makes the Streamlit deployment possible without a second
implementation of the rules, and stops the two surfaces from drifting apart.
"""

import json
import os

from engine import store
from engine.recommender import (
    RecommenderError,
    compute_prerequisites,
    generate_assessment,
    generate_path,
    grade,
    hydrate_courses,
    next_actions,
    normalize_assessment,
    public_questions,
)
from engine.retrieval import CourseIndex

DEFAULT_MODEL = "openai/gpt-oss-120b"


class ServiceError(RuntimeError):
    """Something the caller should show the user, not a crash."""


def get_model():
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL)


def build_client(api_key):
    """Construct the Groq client. Kept here so both surfaces build it alike."""
    if not api_key:
        raise ServiceError(
            "GROQ_API_KEY is not set. Add it to .env locally, or to the app's "
            "secrets when deploying."
        )
    from groq import Groq
    return Groq(api_key=api_key)


# -- path assembly ----------------------------------------------------------

def build_path_payload(index, path):
    """Full path view: hydrated courses, derived prerequisites, progress."""
    if path is None:
        return None

    courses = hydrate_courses(index, store.get_path_courses(path["id"]))
    prereqs = compute_prerequisites(courses)
    for c in courses:
        c["prerequisites"] = prereqs.get(c["course_id"], [])

    done = sum(1 for c in courses if c["completed"])
    total_hours = sum(c["hours"] for c in courses)
    done_hours = sum(c["hours"] for c in courses if c["completed"])

    return {
        "path_id": path["id"],
        "version": path["version"],
        "path_name": path["path_name"],
        "description": path["description"],
        "career_outcome": path["career_outcome"],
        "target_role": path["target_role"],
        "adaptation_note": path["adaptation_note"],
        "created_at": path["created_at"],
        "milestones": json.loads(path["milestones"] or "[]"),
        "skill_gap": json.loads(path["skill_gap"] or "{}"),
        "courses": courses,
        "total_hours": total_hours,
        "completed_hours": done_hours,
        "completed_count": done,
        "course_count": len(courses),
        "progress_percent": round(done / len(courses) * 100, 1) if courses else 0.0,
    }


def active_path(index, learner_id):
    return build_path_payload(index, store.get_active_path(learner_id))


def acquired_skills(learner_id):
    return [s["skill"] for s in store.get_skills(learner_id)]


def generate_and_store(client, index, learner, feedback_signals=(),
                       adapted_from=None, note="", exclude_ids=()):
    """Run the pipeline and persist the result. Raises ServiceError on failure."""
    try:
        path_data, selected = generate_path(
            client, get_model(), index, dict(learner),
            acquired_skills=acquired_skills(learner["id"]),
            feedback_signals=feedback_signals,
            exclude_ids=exclude_ids,
        )
    except RecommenderError as exc:
        raise ServiceError(str(exc))
    except Exception as exc:
        raise ServiceError("Path generation failed: %s" % exc)

    path_id = store.save_path(
        learner["id"], path_data, selected, adapted_from=adapted_from, note=note
    )
    return build_path_payload(index, store.get_path(path_id))


def adapt(client, index, learner, note=""):
    """Rebuild the active path around recorded feedback."""
    current = store.get_active_path(learner["id"])
    if current is None:
        raise ServiceError("No path to adapt yet. Generate one first.")

    signals = store.get_feedback(learner["id"], current["id"])
    if note:
        signals = list(signals) + [
            {"signal": "note", "comment": note, "course_id": None}
        ]
    if not signals:
        raise ServiceError(
            "No feedback recorded yet. Rate a course or add a note first."
        )

    return generate_and_store(
        client, index, learner,
        feedback_signals=signals,
        adapted_from=current["id"],
        note=note or "Adapted from %d feedback signal(s)." % len(signals),
    )


def complete_course(index, path_course_id, completed=True):
    """Mark a course done and credit its skills to the learner."""
    row = store.set_course_completed(path_course_id, completed)
    if row is None:
        raise ServiceError("Course entry not found.")

    path = store.get_path(row["path_id"])
    course = index.by_id.get(row["course_id"])
    if completed and course:
        for skill in course["skills"]:
            store.add_skill(path["learner_id"], skill,
                            source="course:%s" % course["id"])
    return build_path_payload(index, path)


# -- dashboard --------------------------------------------------------------

def dashboard(index, learner_id):
    """Everything the progress view needs, computed once."""
    learner = store.get_learner(learner_id)
    if learner is None:
        raise ServiceError("Learner not found.")

    payload = active_path(index, learner_id)
    acquired = acquired_skills(learner_id)
    gap = index.skill_gap(dict(learner), acquired_skills=acquired)

    courses = payload["courses"] if payload else []
    milestones = []
    if payload:
        for i, name in enumerate(payload["milestones"]):
            group = [c for c in courses if c["milestone_index"] == i]
            done = sum(1 for c in group if c["completed"])
            milestones.append({
                "index": i,
                "name": name,
                "total": len(group),
                "completed": done,
                "percent": round(done / len(group) * 100, 1) if group else 0.0,
                "reached": bool(group) and done == len(group),
            })

    weekly = learner["weekly_hours"] or 8
    remaining = (payload["total_hours"] - payload["completed_hours"]) if payload else 0
    skills = store.get_skills(learner_id)

    return {
        "learner": learner,
        "has_path": payload is not None,
        "path": payload,
        "path_summary": {
            "path_name": payload["path_name"],
            "target_role": payload["target_role"],
            "version": payload["version"],
            "progress_percent": payload["progress_percent"],
            "completed_count": payload["completed_count"],
            "course_count": payload["course_count"],
            "total_hours": payload["total_hours"],
            "completed_hours": payload["completed_hours"],
        } if payload else None,
        "skill_gap": gap,
        "skills_acquired": acquired,
        "skills_by_source": {
            "from_courses": [s["skill"] for s in skills
                             if s["source"].startswith("course:")],
            "from_assessments": [s["skill"] for s in skills
                                 if s["source"].startswith("assessment:")],
            "self_reported": [s["skill"] for s in skills
                              if s["source"] == "manual"],
        },
        "milestones": milestones,
        "estimated_weeks_remaining": round(remaining / weekly, 1) if weekly else None,
        "next_actions": next_actions(courses, gap) if payload else [],
        "feedback_count": len(store.get_feedback(learner_id)),
    }


# -- assessments ------------------------------------------------------------

def assessment_status(index, learner_id):
    """Checkpoint state for every milestone of the active path."""
    path = store.get_active_path(learner_id)
    if path is None:
        return []

    milestones = json.loads(path["milestones"] or "[]")
    courses = hydrate_courses(index, store.get_path_courses(path["id"]))
    existing = {a["milestone_index"]: a for a in store.list_assessments(path["id"])}

    out = []
    for i, name in enumerate(milestones):
        group = [c for c in courses if c["milestone_index"] == i]
        assessment = existing.get(i)
        best = store.best_attempt(assessment["id"], learner_id) if assessment else None
        out.append({
            "milestone_index": i,
            "milestone": name,
            "courses_total": len(group),
            "courses_completed": sum(1 for c in group if c["completed"]),
            "unlocked": bool(group) and all(c["completed"] for c in group),
            "assessment_id": assessment["id"] if assessment else None,
            "title": assessment["title"] if assessment else None,
            "question_count": len(json.loads(assessment["questions"]))
                              if assessment else 0,
            "pass_mark": assessment["pass_mark"] if assessment else 70,
            "best_percent": best["percent"] if best else None,
            "passed": bool(best["passed"]) if best else False,
            "attempts": store.count_attempts(assessment["id"], learner_id)
                        if assessment else 0,
        })
    return out


def get_or_create_assessment(client, index, learner, milestone_index,
                             regenerate=False):
    """Return a milestone checkpoint, generating it if needed.

    Gated on completing the stage, so questions only cover worked material.
    """
    path = store.get_active_path(learner["id"])
    if path is None:
        raise ServiceError("No path generated yet.")

    milestones = json.loads(path["milestones"] or "[]")
    if not 0 <= milestone_index < len(milestones):
        raise ServiceError("No such milestone.")

    existing = store.get_assessment_for_milestone(path["id"], milestone_index)
    if existing and not regenerate:
        return {
            "assessment_id": existing["id"],
            "title": existing["title"],
            "pass_mark": existing["pass_mark"],
            "questions": public_questions(json.loads(existing["questions"])),
        }

    courses = [c for c in hydrate_courses(index, store.get_path_courses(path["id"]))
               if c["milestone_index"] == milestone_index]
    if not courses:
        raise ServiceError("That milestone has no courses.")
    if not all(c["completed"] for c in courses):
        raise ServiceError(
            "Finish all %d courses in this stage before taking its checkpoint."
            % len(courses)
        )

    skills = sorted({s for c in courses for s in c["targets_skills"]}) or \
        sorted({s for c in courses for s in c["skills"]})[:8]

    try:
        built = generate_assessment(
            client, get_model(), milestones[milestone_index], courses, skills,
            level=learner["experience_level"],
        )
    except RecommenderError as exc:
        raise ServiceError(str(exc))
    except Exception as exc:
        raise ServiceError("Assessment generation failed: %s" % exc)

    assessment_id = store.save_assessment(
        path["id"], milestone_index, built["title"], built["questions"], skills
    )
    return {
        "assessment_id": assessment_id,
        "title": built["title"],
        "pass_mark": 70,
        "questions": public_questions(built["questions"]),
    }


def submit_assessment(assessment_id, answers):
    """Grade server-side and credit skills only on a pass."""
    assessment = store.get_assessment(assessment_id)
    if assessment is None:
        raise ServiceError("Assessment not found.")

    path = store.get_path(assessment["path_id"])
    learner_id = path["learner_id"]

    questions = json.loads(assessment["questions"])
    score, results = grade(questions, answers)
    total = len(questions)
    percent = round(score / total * 100, 1) if total else 0.0
    passed = percent >= assessment["pass_mark"]

    store.record_attempt(assessment_id, learner_id, score, total, passed, answers)

    credited = []
    if passed:
        for skill in json.loads(assessment["targets_skills"] or "[]"):
            store.add_skill(learner_id, skill, source="assessment:%d" % assessment_id)
            credited.append(skill)

    return {
        "score": score, "total": total, "percent": percent, "passed": passed,
        "pass_mark": assessment["pass_mark"], "results": results,
        "skills_credited": credited,
    }


# -- assistant --------------------------------------------------------------

CHAT_PROMPT = """You are a learning advisor for {name}.

Their goal: {goals}
Experience level: {level}
Target role: {role}
Skills they have: {have}
Skills still missing: {missing}

Their current path:
{path}

Recent conversation:
{history}

Learner asks: {question}

Answer helpfully and concretely, grounded in their actual path above. If they
ask why a course was recommended, quote the stored reason for it. Keep it under
150 words unless they ask for detail."""


def chat(client, index, learner, message):
    """Answer a question grounded in the learner's stored path."""
    payload = active_path(index, learner["id"])
    gap = index.skill_gap(dict(learner),
                          acquired_skills=acquired_skills(learner["id"]))

    if payload:
        path_lines = "\n".join(
            "%d. %s (%s, %dh)%s - why: %s"
            % (i + 1, c["title"], c["provider"], c["hours"],
               " [DONE]" if c["completed"] else "", c["reason"] or "n/a")
            for i, c in enumerate(payload["courses"])
        )
    else:
        path_lines = "No path generated yet."

    history = "\n".join(
        "%s: %s" % (m["role"], m["content"][:200])
        for m in store.get_messages(learner["id"], limit=6)
    ) or "none"

    prompt = CHAT_PROMPT.format(
        name=learner["name"], goals=learner["goals"] or "not set",
        level=learner["experience_level"], role=gap["role"] or "not matched",
        have=", ".join(gap["covered_skills"]) or "none yet",
        missing=", ".join(gap["missing_skills"][:10]) or "none",
        path=path_lines, history=history, question=message,
    )

    try:
        resp = client.chat.completions.create(
            model=get_model(), max_tokens=1200, reasoning_effort="low",
            messages=[{"role": "user", "content": prompt}],
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        raise ServiceError("Assistant unavailable: %s" % exc)

    store.add_message(learner["id"], "user", message)
    store.add_message(learner["id"], "assistant", answer)
    return answer


def explain(index, learner, course_id):
    """Structured 'why this course' for a single recommendation."""
    path = store.get_active_path(learner["id"])
    if path is None:
        raise ServiceError("No path generated yet.")

    ordered = store.get_path_courses(path["id"])
    row = next((r for r in ordered if r["course_id"] == course_id), None)
    if row is None:
        raise ServiceError("Course not in the active path.")

    course = index.by_id[course_id]
    gap = index.skill_gap(dict(learner),
                          acquired_skills=acquired_skills(learner["id"]))
    targets = json.loads(row["targets_skills"] or "[]")
    earlier = [index.by_id[r["course_id"]]["title"] for r in ordered
               if r["position"] < row["position"]
               and set(index.by_id[r["course_id"]]["skills"]) & set(course["skills"])]

    return {
        "course_id": course_id,
        "title": course["title"],
        "reason": row["reason"],
        "closes_skill_gaps": [s for s in targets if s in gap["missing_skills"]],
        "all_targeted_skills": targets,
        "position": row["position"] + 1,
        "of": len(ordered),
        "builds_on": earlier[-2:],
        "matched_because": {
            "target_role": gap["role"],
            "learner_level": learner["experience_level"],
            "course_level": course["level"],
            "retrieval": "BM25 match on goal, interests and missing skills",
        },
    }


__all__ = [
    "CourseIndex", "ServiceError", "acquired_skills", "active_path", "adapt",
    "assessment_status", "build_client", "build_path_payload", "chat",
    "complete_course", "dashboard", "explain", "generate_and_store",
    "get_model", "get_or_create_assessment", "normalize_assessment",
    "submit_assessment",
]
