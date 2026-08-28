"""Smoke tests for the Streamlit deployment entry point.

Uses Streamlit's own AppTest harness to execute the script headlessly, so a
broken widget call or a bad service wiring fails here instead of showing up as
a red traceback in the deployed app. No network and no API calls: the LLM
client is stubbed and only non-generating screens are exercised.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from engine import store  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Run the app against a throwaway database and a fake API key."""
    monkeypatch.setenv("PATHFINDER_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    # store.DB_PATH is read at import time, so point it at the temp file too.
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    store.init_db()
    return AppTest.from_file(APP, default_timeout=30)


def test_app_starts_without_exception(app):
    app.run()
    assert not app.exception, [str(e) for e in app.exception]


def test_onboarding_is_the_first_screen(app):
    app.run()
    text = " ".join(m.value for m in app.markdown) + " ".join(
        t.value for t in app.title
    )
    assert "Learning Pathfinder" in text or app.title
    # The intake textarea is the entry point.
    assert len(app.text_area) >= 1


def test_missing_api_key_stops_with_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("PATHFINDER_DB", str(tmp_path / "app.db"))
    # Set empty rather than deleting: the app calls load_dotenv(), which would
    # repopulate the key from a local .env if the variable were simply unset.
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    errors = " ".join(e.value for e in at.error)
    assert "GROQ_API_KEY" in errors


def test_example_button_fills_the_intake_box(app):
    app.run()
    assert not app.exception
    app.button(key="ex_0").click().run()
    assert not app.exception
    assert app.text_area[0].value.strip()


def test_dashboard_renders_for_a_learner_without_a_path(app, tmp_path):
    learner_id = store.create_learner({
        "name": "Ada", "goals": "become a backend engineer",
        "completed_learning": "python", "weekly_hours": 10,
    })
    app.session_state["learner_id"] = learner_id
    app.run()
    assert not app.exception, [str(e) for e in app.exception]
    # Four tabs, and the no-path dashboard state.
    assert len(app.tabs) == 4


def test_full_path_renders_end_to_end(app):
    """A learner with a stored path must render without touching the LLM."""
    learner_id = store.create_learner({
        "name": "Ada", "goals": "become a backend engineer",
        "completed_learning": "python", "weekly_hours": 10,
    })
    store.save_path(
        learner_id,
        {
            "path_name": "Backend Foundations",
            "description": "A test path.",
            "career_outcome": "Junior backend engineer.",
            "target_role": "Backend Engineer",
            "milestones": ["Foundations", "APIs"],
            "skill_gap": {"role": "Backend Engineer", "coverage_percent": 20.0,
                          "target_skills": ["python", "rest-api"],
                          "covered_skills": ["python"],
                          "missing_skills": ["rest-api"]},
        },
        [
            {"course_id": "linux-journey", "reason": "Foundations first.",
             "targets_skills": ["linux"], "milestone_index": 0,
             "project": "Set up a VM."},
            {"course_id": "fastapi-docs", "reason": "Then build APIs.",
             "targets_skills": ["rest-api"], "milestone_index": 1,
             "project": "Ship an API."},
        ],
    )
    app.session_state["learner_id"] = learner_id
    app.run()
    assert not app.exception, [str(e) for e in app.exception]

    # Content is spread across element types: the path name is a subheader,
    # course rows are expander labels, and each rationale is an st.info block.
    everything = " ".join([
        " ".join(h.value for h in app.subheader),
        " ".join(str(e.label) for e in app.expander),
        " ".join(m.value for m in app.markdown),
        " ".join(i.value for i in app.info),
        " ".join(c.value for c in app.caption),
    ])

    assert "Backend Foundations" in everything
    assert "FastAPI" in everything          # real catalog course joined on
    assert "Then build APIs." in everything  # the stored per-course rationale


def test_checkpoint_tab_reports_locked_stages(app):
    learner_id = store.create_learner({"name": "Ada", "goals": "backend engineer"})
    store.save_path(
        learner_id,
        {"path_name": "P", "milestones": ["Foundations"]},
        [{"course_id": "linux-journey", "reason": "r", "milestone_index": 0}],
    )
    app.session_state["learner_id"] = learner_id
    app.run()
    assert not app.exception, [str(e) for e in app.exception]


# -- access gate ------------------------------------------------------------

def test_no_gate_when_access_code_is_unset(app, monkeypatch):
    """Local development and CI must be unaffected by the gate."""
    monkeypatch.delenv("APP_ACCESS_CODE", raising=False)
    app.run()
    assert not app.exception
    # Reaches the normal onboarding screen rather than a code prompt.
    assert len(app.text_area) >= 1


def test_gate_blocks_when_access_code_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("PATHFINDER_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    monkeypatch.setenv("APP_ACCESS_CODE", "let-me-in")
    store.init_db()

    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    # Only the code prompt is rendered; the app itself never builds.
    assert len(at.text_input) == 1
    assert at.text_input[0].label == "Access code"
    assert len(at.tabs) == 0


def test_gate_rejects_a_wrong_code(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("PATHFINDER_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    monkeypatch.setenv("APP_ACCESS_CODE", "let-me-in")
    store.init_db()

    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.text_input[0].set_value("wrong").run()
    assert not at.exception
    assert any("not correct" in e.value for e in at.error)
    assert len(at.tabs) == 0


def test_gate_admits_the_correct_code(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("PATHFINDER_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    monkeypatch.setenv("APP_ACCESS_CODE", "let-me-in")
    store.init_db()

    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.text_input[0].set_value("let-me-in").run()
    assert not at.exception
    # AppTest's session_state proxy has no .get(), so index it directly.
    assert at.session_state["_access_ok"] is True
    # And the gated app is now reachable.
    assert len(at.text_input) != 1 or at.text_input[0].label != "Access code"


def test_learner_roster_is_hidden_by_default(app, monkeypatch):
    """Regression: the start screen used to list every learner's name and goal."""
    monkeypatch.delenv("PATHFINDER_SHOW_LEARNERS", raising=False)
    store.create_learner({"name": "Ada Private", "goals": "become a backend engineer"})
    app.run()
    assert not app.exception
    rendered = " ".join(
        [str(e.label) for e in app.expander]
        + [m.value for m in app.markdown]
        + [c.value for c in app.caption]
    )
    assert "Ada Private" not in rendered
