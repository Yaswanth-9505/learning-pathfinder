"""Tests for the retrieval, persistence and assembly logic.

These cover everything that does not require the LLM, so the suite runs offline
and without burning API quota. The model-dependent stages (profile extraction,
course curation) are exercised through assemble_path with recorded payloads.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import store  # noqa: E402
from engine.recommender import (  # noqa: E402
    RecommenderError,
    _parse_json,
    assemble_path,
    compute_prerequisites,
    grade,
    hydrate_courses,
    next_actions,
    normalize_assessment,
    public_questions,
)
from engine.retrieval import CourseIndex, tokenize  # noqa: E402


@pytest.fixture(scope="module")
def index():
    return CourseIndex()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the store at a throwaway database per test."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()
    return store


# -- catalog integrity ------------------------------------------------------

def test_catalog_is_well_formed(index):
    assert len(index.courses) >= 50
    ids = [c["id"] for c in index.courses]
    assert len(ids) == len(set(ids)), "duplicate course ids"
    for c in index.courses:
        assert c["url"].startswith("http")
        assert c["level"] in {"beginner", "intermediate", "advanced"}
        assert c["hours"] > 0
        assert c["skills"] and c["domains"]


def test_every_role_skill_is_teachable(index):
    """A role must not demand a skill no course in the catalog teaches."""
    taught = {s for c in index.courses for s in c["skills"]}
    for role in index.roles:
        missing = set(role["skills"]) - taught
        assert not missing, "%s needs untaught skills: %s" % (role["name"], missing)


# -- tokenizing and skill extraction ---------------------------------------

def test_tokenize_drops_stopwords_and_splits_hyphens():
    assert tokenize("I want to learn REST-API design") == ["rest", "api", "design"]


def test_normalize_skills_requires_whole_words(index):
    """Regression: 'basic' must not yield the skill 'c'."""
    assert index.normalize_skills("basic python and some SQL") == ["python", "sql"]
    assert "c" not in index.normalize_skills("I have basic knowledge")


def test_normalize_skills_matches_multiword(index):
    assert "linear-algebra" in index.normalize_skills("I studied linear algebra")


# -- retrieval --------------------------------------------------------------

def test_search_ranks_relevant_courses_first(index):
    results = index.search("postgresql database schema design", top_k=5)
    assert results
    titles = " ".join(r["title"].lower() for r in results[:3])
    assert "postgresql" in titles or "database" in titles


def test_search_respects_exclusions(index):
    excluded = index.search("python programming", top_k=5)[0]["id"]
    again = index.search("python programming", top_k=5, exclude_ids=(excluded,))
    assert excluded not in [c["id"] for c in again]


def test_search_returns_empty_for_meaningless_query(index):
    assert index.search("the and of to") == []


def test_level_preference_biases_ranking(index):
    """The same query must order differently for learners at different levels.

    Needs a query whose matches actually span levels: a query matching only
    same-level courses is scaled uniformly and cannot reorder.
    """
    query = "python api database backend deployment docker"
    beginner = index.search(query, top_k=6, level="beginner")
    advanced = index.search(query, top_k=6, level="advanced")
    assert beginner and advanced

    def rank_of(results, level):
        return next(i for i, c in enumerate(results) if c["level"] == level)

    # The advanced course sits higher for the advanced learner.
    assert rank_of(advanced, "advanced") < rank_of(beginner, "advanced")


# -- skill gap --------------------------------------------------------------

def test_skill_gap_identifies_role_and_missing(index):
    gap = index.skill_gap({
        "goals": "I want to become a backend engineer",
        "completed_learning": "python, sql",
    })
    assert gap["role"] == "Backend Engineer"
    assert "python" in gap["covered_skills"]
    assert "docker" in gap["missing_skills"]
    assert 0 < gap["coverage_percent"] < 100


def test_acquired_skills_shrink_the_gap(index):
    profile = {"goals": "backend engineer", "completed_learning": ""}
    before = index.skill_gap(profile)
    after = index.skill_gap(profile, acquired_skills=["docker", "git", "testing"])
    assert after["coverage_percent"] > before["coverage_percent"]
    assert "docker" not in after["missing_skills"]


def test_unmatched_goal_degrades_gracefully(index):
    gap = index.skill_gap({"goals": "become a professional trombonist"})
    assert gap["role"] is None
    assert gap["missing_skills"] == []


# -- assembly / validation --------------------------------------------------

def test_assemble_drops_hallucinated_course_ids(index):
    gap = index.skill_gap({"goals": "backend engineer"})
    candidates = index.search("backend python api", top_k=10)
    payload = {
        "path_name": "Test Path",
        "milestones": ["Start", "Finish"],
        "courses": [
            {"course_id": "fastapi-docs", "reason": "real", "milestone_index": 0},
            {"course_id": "totally-made-up-course", "reason": "fake", "milestone_index": 1},
        ],
    }
    path, selected = assemble_path(index, payload, gap, candidates)
    ids = [c["course_id"] for c in selected]
    assert "fastapi-docs" in ids
    assert "totally-made-up-course" not in ids
    assert "totally-made-up-course" in path["dropped_course_ids"]


def test_assemble_backfills_when_model_returns_too_few(index):
    gap = index.skill_gap({"goals": "backend engineer"})
    candidates = index.search("backend python api", top_k=10)
    payload = {"path_name": "Thin", "milestones": ["A"],
               "courses": [{"course_id": "fastapi-docs", "reason": "x"}]}
    _, selected = assemble_path(index, payload, gap, candidates)
    assert len(selected) >= 6, "should backfill from retrieval ranking"


def test_assemble_deduplicates(index):
    gap = index.skill_gap({"goals": "backend engineer"})
    candidates = index.search("backend", top_k=10)
    payload = {"path_name": "Dupes", "milestones": ["A"], "courses": [
        {"course_id": "fastapi-docs", "reason": "1"},
        {"course_id": "fastapi-docs", "reason": "2"},
    ]}
    _, selected = assemble_path(index, payload, gap, candidates)
    assert [c["course_id"] for c in selected].count("fastapi-docs") == 1


def test_milestone_index_is_clamped(index):
    gap = index.skill_gap({"goals": "backend engineer"})
    candidates = index.search("backend", top_k=10)
    payload = {"path_name": "P", "milestones": ["A", "B"], "courses": [
        {"course_id": "fastapi-docs", "reason": "x", "milestone_index": 99},
    ]}
    _, selected = assemble_path(index, payload, gap, candidates)
    assert selected[0]["milestone_index"] <= 1


def test_parse_json_handles_code_fences():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('{"a": 2}') == {"a": 2}


def test_parse_json_raises_on_garbage():
    with pytest.raises(RecommenderError):
        _parse_json("no json here at all")


# -- derived structure ------------------------------------------------------

def test_prerequisites_only_point_backwards(index):
    rows = [
        {"id": 1, "position": 0, "course_id": "py-4-everybody", "targets_skills": "[]"},
        {"id": 2, "position": 1, "course_id": "fastapi-docs", "targets_skills": "[]"},
        {"id": 3, "position": 2, "course_id": "sqlalchemy", "targets_skills": "[]"},
    ]
    courses = hydrate_courses(index, rows)
    prereqs = compute_prerequisites(courses)
    assert prereqs["py-4-everybody"] == []
    titles = {c["course_id"]: c["title"] for c in courses}
    assert titles["py-4-everybody"] in prereqs["fastapi-docs"]


def test_next_actions_points_at_first_incomplete(index):
    rows = [
        {"id": 1, "position": 0, "course_id": "py-4-everybody",
         "targets_skills": "[]", "completed": 1},
        {"id": 2, "position": 1, "course_id": "fastapi-docs",
         "targets_skills": "[]", "completed": 0, "project": "Build an API"},
    ]
    courses = hydrate_courses(index, rows)
    gap = index.skill_gap({"goals": "backend engineer"})
    actions = next_actions(courses, gap)
    assert actions[0]["course_id"] == "fastapi-docs"
    assert any(a["kind"] == "project" for a in actions)


# -- assessments ------------------------------------------------------------

def _mcq(n=5, answer_first=True):
    return {
        "title": "Checkpoint",
        "questions": [
            {
                "question": "Question %d about indexing and transactions" % i,
                "options": ["RIGHT", "wrong a", "wrong b", "wrong c"]
                if answer_first
                else ["wrong a", "RIGHT", "wrong b", "wrong c"],
                "answer_index": 0 if answer_first else 1,
                "explains": "because",
                "skill": "sql",
            }
            for i in range(n)
        ],
    }


def test_assessment_shuffles_away_model_position_bias():
    """Regression: the model puts the correct option first every time.

    Without shuffling, answering 'A' to everything scores 100%.
    """
    built = normalize_assessment(_mcq(8), n=8)
    positions = {q["answer_index"] for q in built["questions"]}
    assert len(positions) > 1, "all correct answers still share one position"


def test_shuffle_keeps_answer_index_pointing_at_the_right_option():
    built = normalize_assessment(_mcq(6), n=6)
    for q in built["questions"]:
        assert q["options"][q["answer_index"]] == "RIGHT"


def test_shuffle_is_deterministic_for_the_same_question():
    first = normalize_assessment(_mcq(5), n=5)
    second = normalize_assessment(_mcq(5), n=5)
    assert [q["answer_index"] for q in first["questions"]] == \
           [q["answer_index"] for q in second["questions"]]


def test_assessment_drops_malformed_questions():
    data = {
        "title": "T",
        "questions": [
            {"question": "good one about sql", "options": ["a", "b", "c", "d"],
             "answer_index": 2},
            {"question": "only three options", "options": ["a", "b", "c"],
             "answer_index": 1},
            {"question": "answer out of range", "options": ["a", "b", "c", "d"],
             "answer_index": 9},
            {"question": "", "options": ["a", "b", "c", "d"], "answer_index": 0},
        ],
    }
    built = normalize_assessment(data, n=5)
    assert len(built["questions"]) == 1


def test_assessment_raises_when_nothing_is_gradeable():
    with pytest.raises(RecommenderError):
        normalize_assessment({"title": "T", "questions": [{"question": "x"}]})


def test_public_questions_never_leak_the_answer_key():
    built = normalize_assessment(_mcq(4), n=4)
    for q in public_questions(built["questions"]):
        assert "answer_index" not in q
        assert "explains" not in q


def test_grading_counts_correct_answers():
    built = normalize_assessment(_mcq(5), n=5)
    keys = [q["answer_index"] for q in built["questions"]]
    score, results = grade(built["questions"], keys)
    assert score == 5
    assert all(r["correct"] for r in results)


def test_grading_handles_missing_and_invalid_answers():
    built = normalize_assessment(_mcq(3), n=3)
    score, results = grade(built["questions"], [None, "banana"])
    assert score == 0
    assert len(results) == 3           # unanswered still reported
    assert results[2]["your_answer"] == -1


def test_always_picking_option_a_does_not_pass():
    built = normalize_assessment(_mcq(8), n=8)
    score, _ = grade(built["questions"], [0] * 8)
    assert score / 8 * 100 < 70


def test_assessment_persists_and_best_attempt_wins(db):
    lid = db.create_learner({"name": "T", "goals": "backend engineer"})
    pid = db.save_path(lid, {"path_name": "p", "milestones": ["A"]},
                       [{"course_id": "fastapi-docs"}])
    built = normalize_assessment(_mcq(5), n=5)
    aid = db.save_assessment(pid, 0, built["title"], built["questions"], ["sql"])

    db.record_attempt(aid, lid, 2, 5, False, [0, 0, 0, 0, 0])
    db.record_attempt(aid, lid, 5, 5, True, [1, 1, 1, 1, 1])
    db.record_attempt(aid, lid, 3, 5, False, [2, 2, 2, 2, 2])

    best = db.best_attempt(aid, lid)
    assert best["percent"] == 100.0 and best["passed"] == 1
    assert db.count_attempts(aid, lid) == 3


def test_one_assessment_per_milestone(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    pid = db.save_path(lid, {"path_name": "p", "milestones": ["A"]},
                       [{"course_id": "fastapi-docs"}])
    built = normalize_assessment(_mcq(3), n=3)
    db.save_assessment(pid, 0, "First", built["questions"], ["sql"])
    db.save_assessment(pid, 0, "Regenerated", built["questions"], ["sql"])
    assert len(db.list_assessments(pid)) == 1
    assert db.get_assessment_for_milestone(pid, 0)["title"] == "Regenerated"


# -- persistence ------------------------------------------------------------

def test_learner_roundtrip(db):
    lid = db.create_learner({"name": "Ada", "goals": "backend engineer"})
    assert db.get_learner(lid)["name"] == "Ada"
    db.update_learner(lid, {"name": "Ada L", "weekly_hours": 12})
    updated = db.get_learner(lid)
    assert updated["name"] == "Ada L" and updated["weekly_hours"] == 12


def test_saving_a_path_deactivates_the_previous_one(db):
    lid = db.create_learner({"name": "T", "goals": "backend"})
    first = db.save_path(lid, {"path_name": "v1"}, [{"course_id": "fastapi-docs"}])
    second = db.save_path(lid, {"path_name": "v2"}, [{"course_id": "sqlalchemy"}])
    assert db.get_active_path(lid)["id"] == second
    assert db.get_path(first)["is_active"] == 0
    assert db.get_path(second)["version"] == 2


def test_completion_is_persisted(db):
    lid = db.create_learner({"name": "T", "goals": "backend"})
    pid = db.save_path(lid, {"path_name": "p"}, [{"course_id": "fastapi-docs"}])
    row = db.get_path_courses(pid)[0]
    db.set_course_completed(row["id"], True)
    after = db.get_path_courses(pid)[0]
    assert after["completed"] == 1 and after["completed_at"]


def test_skills_are_unique_per_learner(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    db.add_skill(lid, "Docker")
    db.add_skill(lid, "docker")
    assert [s["skill"] for s in db.get_skills(lid)] == ["docker"]


def test_chat_history_returns_chronological_order(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    for i in range(5):
        db.add_message(lid, "user", "q%d" % i)
    messages = db.get_messages(lid, limit=3)
    assert [m["content"] for m in messages] == ["q2", "q3", "q4"]


def test_feedback_is_scoped_to_path(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    pid = db.save_path(lid, {"path_name": "p"}, [{"course_id": "fastapi-docs"}])
    db.add_feedback(lid, "too_hard", path_id=pid, course_id="fastapi-docs")
    db.add_feedback(lid, "helpful", path_id=None)
    assert len(db.get_feedback(lid)) == 2
    assert len(db.get_feedback(lid, path_id=pid)) == 1


def test_path_courses_keep_their_order(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    ordered = ["cs50x", "fastapi-docs", "sqlalchemy", "docker-getstarted"]
    pid = db.save_path(lid, {"path_name": "p"},
                       [{"course_id": c} for c in ordered])
    assert [r["course_id"] for r in db.get_path_courses(pid)] == ordered


def test_milestones_and_gap_survive_json_roundtrip(db):
    lid = db.create_learner({"name": "T", "goals": "x"})
    pid = db.save_path(
        lid,
        {"path_name": "p", "milestones": ["A", "B"], "skill_gap": {"role": "X"}},
        [{"course_id": "fastapi-docs"}],
    )
    path = db.get_path(pid)
    assert json.loads(path["milestones"]) == ["A", "B"]
    assert json.loads(path["skill_gap"])["role"] == "X"
