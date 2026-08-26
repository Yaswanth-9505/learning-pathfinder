"""The recommendation pipeline.

Path generation is retrieval-augmented rather than free-form generation:

  1. Build a retrieval query from the learner profile and target-role skills.
  2. BM25-rank the local catalog to a candidate shortlist.
  3. Compute the skill gap between the learner and the target role.
  4. Ask the LLM to *select, order and justify* courses from that shortlist.
  5. Validate every returned id against the catalog and drop anything invented.
  6. Join catalog metadata back on, so titles, providers and URLs are real.

The model never supplies course facts, only curation and rationale. That is
what makes each recommendation explainable and every resource link genuine.
"""

import json
import random
import re

MAX_CANDIDATES = 16
MIN_COURSES = 6
MAX_COURSES = 10


class RecommenderError(RuntimeError):
    pass


# -- LLM plumbing -----------------------------------------------------------

def _complete(client, model, prompt, max_tokens, json_mode=True):
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        reasoning_effort="low",
        messages=[{"role": "user", "content": prompt}],
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise RecommenderError(
            "The model response was truncated. Try a shorter profile or raise max_tokens."
        )
    return (choice.message.content or "").strip()


def _parse_json(text):
    """Tolerant JSON parse: strips code fences and trailing prose if present."""
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = re.sub(r"^json\s*", "", text.strip(), flags=re.I)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise RecommenderError("Model did not return parseable JSON.")
        return json.loads(match.group(0))


# -- conversational profile extraction --------------------------------------

PROFILE_PROMPT = """Extract a structured learner profile from this message.

Learner said:
\"\"\"{text}\"\"\"

Return ONLY a JSON object with exactly these keys:
{{
  "name": "their name, or empty string if not stated",
  "goals": "what they want to achieve, as a short phrase",
  "interests": "topics/technologies they mention interest in, comma separated",
  "experience_level": "one of: beginner, intermediate, advanced",
  "completed_learning": "what they say they already know, comma separated, empty if none",
  "weekly_hours": integer hours per week they can study, default 8 if unstated,
  "followup": "one short friendly question to ask if something important is missing, else empty string"
}}

Infer experience_level from how they describe themselves. If they say they are
new, a student, or a beginner, use "beginner". Never invent facts they did not
state; use empty strings instead."""


def extract_profile(client, model, text):
    """Turn a natural-language self-description into a structured profile."""
    raw = _complete(client, model, PROFILE_PROMPT.format(text=text), 1200)
    data = _parse_json(raw)
    level = str(data.get("experience_level", "beginner")).lower().strip()
    if level not in {"beginner", "intermediate", "advanced"}:
        level = "beginner"
    try:
        hours = int(data.get("weekly_hours") or 8)
    except (TypeError, ValueError):
        hours = 8
    return {
        "name": str(data.get("name") or "").strip(),
        "goals": str(data.get("goals") or "").strip(),
        "interests": str(data.get("interests") or "").strip(),
        "experience_level": level,
        "completed_learning": str(data.get("completed_learning") or "").strip(),
        "weekly_hours": max(1, min(hours, 80)),
        "followup": str(data.get("followup") or "").strip(),
    }


# -- path generation --------------------------------------------------------

PATH_PROMPT = """You are a learning path architect. Build a personalised roadmap.

LEARNER
  Name: {name}
  Experience: {level}
  Preferred learning style: {style}
  Goal: {goals}
  Interests: {interests}
  Already knows: {known}
  Available: {weekly_hours} hours per week

TARGET ROLE: {role}
SKILLS STILL MISSING: {missing}
{feedback_block}
AVAILABLE COURSES (you MUST choose only from these ids):
{candidates}

Select {min_c}-{max_c} courses that take this learner from where they are to the
target role. Order them so prerequisites come first. Do not include courses
teaching only what they already know.

Return ONLY this JSON:
{{
  "path_name": "short specific name for this roadmap",
  "description": "2 sentence summary of the journey",
  "career_outcome": "1 sentence on what they can do at the end",
  "milestones": ["3 to 5 checkpoint names, in order"],
  "courses": [
    {{
      "course_id": "an id from the list above",
      "reason": "1-2 sentences: why THIS learner needs THIS course at THIS point, referencing their goal, prior knowledge or a missing skill",
      "targets_skills": ["skills from the missing list this closes"],
      "milestone_index": 0,
      "project": "a concrete hands-on project to prove the skill"
    }}
  ]
}}

The "reason" must be specific to this learner, not generic course marketing.
milestone_index maps each course to a milestone by array position."""


def _format_candidates(courses):
    lines = []
    for c in courses:
        lines.append(
            "- %s | %s (%s) | %s | %dh | teaches: %s"
            % (
                c["id"],
                c["title"],
                c["provider"],
                c["level"],
                c["hours"],
                ", ".join(c["skills"][:6]),
            )
        )
    return "\n".join(lines)


def _feedback_block(signals):
    if not signals:
        return ""
    lines = ["\nLEARNER FEEDBACK ON THE PREVIOUS PATH (adapt accordingly):"]
    for s in signals:
        target = (" on course %s" % s["course_id"]) if s.get("course_id") else ""
        note = (": %s" % s["comment"]) if s.get("comment") else ""
        lines.append("  - %s%s%s" % (s["signal"].replace("_", " "), target, note))
    lines.append(
        "  Adjust difficulty, pacing and topic mix to answer this feedback directly."
    )
    return "\n".join(lines) + "\n"


def generate_path(client, model, index, profile, acquired_skills=(),
                  feedback_signals=(), exclude_ids=()):
    """Run the full RAG pipeline and return an assembled path dict."""
    gap = index.skill_gap(profile, acquired_skills=acquired_skills)

    query = index.build_query(profile)
    if gap["missing_skills"]:
        query += " " + " ".join(gap["missing_skills"])

    candidates = index.search(
        query,
        top_k=MAX_CANDIDATES,
        level=profile.get("experience_level"),
        exclude_ids=exclude_ids,
    )
    if not candidates:
        raise RecommenderError(
            "No courses matched that goal. Try describing it in more detail."
        )

    prompt = PATH_PROMPT.format(
        name=profile.get("name") or "the learner",
        level=profile.get("experience_level", "beginner"),
        style=profile.get("learning_style", "hands-on"),
        goals=profile.get("goals", ""),
        interests=profile.get("interests", "") or "not specified",
        known=", ".join(gap["known_skills"]) or "nothing yet",
        weekly_hours=profile.get("weekly_hours", 8),
        role=gap["role"] or "not matched to a known role",
        missing=", ".join(gap["missing_skills"]) or "none identified",
        feedback_block=_feedback_block(feedback_signals),
        candidates=_format_candidates(candidates),
        min_c=MIN_COURSES,
        max_c=MAX_COURSES,
    )

    data = _parse_json(_complete(client, model, prompt, 3000))
    return assemble_path(index, data, gap, candidates)


def assemble_path(index, data, gap, candidates):
    """Validate model output against the catalog and join real course data on.

    Any course id the model invented is dropped rather than surfaced, so the
    UI can never show a course that does not exist.
    """
    milestones = [str(m) for m in (data.get("milestones") or [])][:6]
    selected, seen, dropped = [], set(), []

    for item in (data.get("courses") or []):
        cid = str(item.get("course_id", "")).strip()
        course = index.by_id.get(cid)
        if course is None:
            dropped.append(cid)
            continue
        if cid in seen:
            continue
        seen.add(cid)

        try:
            m_idx = int(item.get("milestone_index", 0) or 0)
        except (TypeError, ValueError):
            m_idx = 0
        m_idx = max(0, min(m_idx, max(len(milestones) - 1, 0)))

        targets = [str(s) for s in (item.get("targets_skills") or [])]
        selected.append({
            "course_id": cid,
            "reason": str(item.get("reason", "")).strip(),
            "targets_skills": targets,
            "milestone_index": m_idx,
            "project": str(item.get("project", "")).strip(),
        })

    # Fall back to pure retrieval ranking if the model returned too little.
    if len(selected) < MIN_COURSES:
        for c in candidates:
            if len(selected) >= MIN_COURSES:
                break
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            selected.append({
                "course_id": c["id"],
                "reason": "Ranked highly for your goal by catalog relevance.",
                "targets_skills": [
                    s for s in c["skills"] if s in gap["missing_skills"]
                ][:4],
                "milestone_index": 0,
                "project": "",
                "fallback": True,
            })

    if not milestones:
        milestones = ["Foundations", "Core skills", "Applied projects"]

    path = {
        "path_name": str(data.get("path_name") or "Personalised Learning Path"),
        "description": str(data.get("description") or ""),
        "career_outcome": str(data.get("career_outcome") or ""),
        "target_role": gap["role"],
        "milestones": milestones,
        "skill_gap": gap,
        "dropped_course_ids": dropped,
    }
    return path, selected


ASSESSMENT_PROMPT = """Write a short checkpoint assessment for a learner who has
just finished this stage of their learning path.

STAGE: {milestone}
COURSES COVERED IN THIS STAGE:
{courses}
SKILLS THIS STAGE WAS MEANT TO BUILD: {skills}
LEARNER LEVEL: {level}

Write {n} multiple-choice questions that check whether they can actually APPLY
these skills. Prefer questions about doing the thing over questions about
definitions. Each question needs exactly 4 options with exactly one correct.

Return ONLY this JSON:
{{
  "title": "short name for this checkpoint",
  "questions": [
    {{
      "question": "the question text",
      "options": ["option A", "option B", "option C", "option D"],
      "answer_index": 0,
      "explains": "1 sentence on why the correct answer is correct",
      "skill": "which of the listed skills this tests"
    }}
  ]
}}

Make the distractors plausible - wrong for a specific reason, not obviously silly."""


def generate_assessment(client, model, milestone_name, courses, skills,
                        level="beginner", n=5):
    """Generate a milestone checkpoint grounded in the courses actually taken."""
    course_lines = "\n".join(
        "- %s (%s): teaches %s"
        % (c["title"], c["provider"], ", ".join(c["skills"][:6]))
        for c in courses
    ) or "- (no courses recorded for this stage)"

    prompt = ASSESSMENT_PROMPT.format(
        milestone=milestone_name,
        courses=course_lines,
        skills=", ".join(skills) or "general fundamentals",
        level=level,
        n=n,
    )
    data = _parse_json(_complete(client, model, prompt, 2600))
    return normalize_assessment(data, n)


def normalize_assessment(data, n=5):
    """Validate model output into a gradeable assessment.

    Drops any question that is not a well-formed 4-option single-answer item,
    so a malformed generation can never produce an ungradeable checkpoint.
    """
    questions = []
    for q in (data.get("questions") or []):
        options = [str(o) for o in (q.get("options") or []) if str(o).strip()]
        if len(options) != 4:
            continue
        try:
            answer_index = int(q.get("answer_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= answer_index < 4:
            continue
        text = str(q.get("question", "")).strip()
        if not text:
            continue

        # The model has a strong position bias and tends to put the correct
        # option first every time, which makes the checkpoint gameable by
        # answering "A" to everything. Shuffle server-side. Seeded from the
        # question text so a given question always lays out the same way.
        correct = options[answer_index]
        shuffled = list(options)
        random.Random(text).shuffle(shuffled)

        questions.append({
            "question": text,
            "options": shuffled,
            "answer_index": shuffled.index(correct),
            "explains": str(q.get("explains", "")).strip(),
            "skill": str(q.get("skill", "")).strip(),
        })
        if len(questions) >= n:
            break

    if not questions:
        raise RecommenderError(
            "Could not build a valid assessment for this stage. Try again."
        )
    return {
        "title": str(data.get("title") or "Checkpoint").strip(),
        "questions": questions,
    }


def public_questions(questions):
    """Strip correct answers before sending an assessment to the client."""
    return [
        {"question": q["question"], "options": q["options"], "skill": q.get("skill", "")}
        for q in questions
    ]


def grade(questions, answers):
    """Grade server-side. Answers are indices; anything invalid counts wrong."""
    results, score = [], 0
    for i, q in enumerate(questions):
        given = answers[i] if i < len(answers) else None
        try:
            given = int(given)
        except (TypeError, ValueError):
            given = -1
        correct = given == q["answer_index"]
        if correct:
            score += 1
        results.append({
            "question": q["question"],
            "your_answer": given,
            "correct_answer": q["answer_index"],
            "correct": correct,
            "explains": q.get("explains", ""),
            "skill": q.get("skill", ""),
        })
    return score, results


def hydrate_courses(index, rows):
    """Attach catalog metadata to stored path_courses rows for the API."""
    out = []
    for r in rows:
        course = index.by_id.get(r["course_id"])
        if course is None:
            continue
        targets = r.get("targets_skills")
        if isinstance(targets, str):
            try:
                targets = json.loads(targets)
            except json.JSONDecodeError:
                targets = []
        out.append({
            "path_course_id": r.get("id"),
            "position": r.get("position", 0),
            "course_id": course["id"],
            "title": course["title"],
            "provider": course["provider"],
            "url": course["url"],
            "level": course["level"],
            "hours": course["hours"],
            "skills": course["skills"],
            "domains": course["domains"],
            "format": course.get("format", []),
            "description": course["description"],
            "reason": r.get("reason", ""),
            "targets_skills": targets or [],
            "milestone_index": r.get("milestone_index", 0),
            "project": r.get("project", ""),
            "completed": bool(r.get("completed", 0)),
            "completed_at": r.get("completed_at"),
        })
    return out


def compute_prerequisites(courses):
    """Derive prerequisites from ordering and skill overlap.

    A course depends on an earlier course when that earlier course teaches a
    skill this one builds on. Computed rather than asked of the model, so the
    dependency graph is always internally consistent with the ordering.
    """
    prereqs = {}
    for i, course in enumerate(courses):
        needed = set(course["skills"])
        deps = []
        for earlier in courses[:i]:
            if set(earlier["skills"]) & needed:
                deps.append(earlier["title"])
        prereqs[course["course_id"]] = deps[-2:]
    return prereqs


def next_actions(courses, gap, limit=3):
    """The 'what should I do right now' feed for the dashboard."""
    actions = []
    pending = [c for c in courses if not c["completed"]]

    if pending:
        nxt = pending[0]
        actions.append({
            "kind": "course",
            "title": "Start %s" % nxt["title"],
            "detail": nxt["reason"] or nxt["description"],
            "course_id": nxt["course_id"],
            "url": nxt["url"],
        })
        if nxt.get("project"):
            actions.append({
                "kind": "project",
                "title": "Build: %s" % nxt["project"],
                "detail": "Hands-on proof for %s" % nxt["title"],
                "course_id": nxt["course_id"],
            })

    still_missing = [
        s for s in gap.get("missing_skills", [])
        if not any(s in c["skills"] and c["completed"] for c in courses)
    ]
    if still_missing:
        actions.append({
            "kind": "skill",
            "title": "Close skill gap: %s" % ", ".join(still_missing[:3]),
            "detail": "%d of %d target skills still open for %s."
                      % (len(still_missing), len(gap.get("target_skills", [])) or 0,
                         gap.get("role") or "your goal"),
        })

    if not pending and courses:
        actions.append({
            "kind": "done",
            "title": "Path complete - regenerate for the next level",
            "detail": "You finished every course. Ask for an advanced path.",
        })
    return actions[:limit]
