"""SQLite persistence for learners, paths, progress, skills and feedback.

Everything the recommender needs to adapt over time lives here: the profile,
each generated path version, per-course completion, acquired skills, feedback
signals and chat history. Plain sqlite3 so the project stays dependency-light
and the database is a single file that ships with the source.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Overridable so a deployment can point at a writable volume. On Streamlit
# Community Cloud the container filesystem is ephemeral, so the default path
# survives reruns but not a reboot or redeploy.
DB_PATH = Path(
    os.getenv("PATHFINDER_DB")
    or Path(__file__).resolve().parent.parent / "data" / "pathfinder.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    experience_level   TEXT NOT NULL DEFAULT 'beginner',
    learning_style     TEXT NOT NULL DEFAULT 'hands-on',
    goals              TEXT NOT NULL DEFAULT '',
    interests          TEXT NOT NULL DEFAULT '',
    completed_learning TEXT NOT NULL DEFAULT '',
    weekly_hours       INTEGER NOT NULL DEFAULT 8,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paths (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id     INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    version        INTEGER NOT NULL DEFAULT 1,
    path_name      TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    career_outcome TEXT NOT NULL DEFAULT '',
    target_role    TEXT,
    milestones     TEXT NOT NULL DEFAULT '[]',
    skill_gap      TEXT NOT NULL DEFAULT '{}',
    adapted_from   INTEGER REFERENCES paths(id),
    adaptation_note TEXT NOT NULL DEFAULT '',
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS path_courses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path_id         INTEGER NOT NULL REFERENCES paths(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    course_id       TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    targets_skills  TEXT NOT NULL DEFAULT '[]',
    milestone_index INTEGER NOT NULL DEFAULT 0,
    project         TEXT NOT NULL DEFAULT '',
    completed       INTEGER NOT NULL DEFAULT 0,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS learner_skills (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    skill      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    UNIQUE(learner_id, skill)
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    path_id    INTEGER REFERENCES paths(id) ON DELETE CASCADE,
    course_id  TEXT,
    signal     TEXT NOT NULL,
    comment    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path_id         INTEGER NOT NULL REFERENCES paths(id) ON DELETE CASCADE,
    milestone_index INTEGER NOT NULL,
    title           TEXT NOT NULL,
    questions       TEXT NOT NULL DEFAULT '[]',
    targets_skills  TEXT NOT NULL DEFAULT '[]',
    pass_mark       INTEGER NOT NULL DEFAULT 70,
    created_at      TEXT NOT NULL,
    UNIQUE(path_id, milestone_index)
);

CREATE TABLE IF NOT EXISTS assessment_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    learner_id    INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    score         INTEGER NOT NULL,
    total         INTEGER NOT NULL,
    percent       REAL NOT NULL,
    passed        INTEGER NOT NULL DEFAULT 0,
    answers       TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paths_learner  ON paths(learner_id, is_active);
CREATE INDEX IF NOT EXISTS idx_assess_path    ON assessments(path_id, milestone_index);
CREATE INDEX IF NOT EXISTS idx_attempt_lookup ON assessment_attempts(assessment_id, learner_id, id);
CREATE INDEX IF NOT EXISTS idx_pc_path        ON path_courses(path_id, position);
CREATE INDEX IF NOT EXISTS idx_chat_learner   ON chat_messages(learner_id, id);
CREATE INDEX IF NOT EXISTS idx_feedback_learner ON feedback(learner_id, id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row(r):
    return dict(r) if r is not None else None


# -- learners ---------------------------------------------------------------

def create_learner(profile):
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO learners
               (name, experience_level, learning_style, goals, interests,
                completed_learning, weekly_hours, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                profile.get("name", "Learner"),
                profile.get("experience_level", "beginner"),
                profile.get("learning_style", "hands-on"),
                profile.get("goals", ""),
                profile.get("interests", ""),
                profile.get("completed_learning", ""),
                int(profile.get("weekly_hours", 8) or 8),
                ts,
                ts,
            ),
        )
        return cur.lastrowid


def update_learner(learner_id, profile):
    fields = [
        "name", "experience_level", "learning_style", "goals", "interests",
        "completed_learning", "weekly_hours",
    ]
    sets, values = [], []
    for f in fields:
        if f in profile and profile[f] is not None:
            sets.append("%s = ?" % f)
            values.append(profile[f])
    if not sets:
        return get_learner(learner_id)
    sets.append("updated_at = ?")
    values.extend([now(), learner_id])
    with connect() as conn:
        conn.execute("UPDATE learners SET %s WHERE id = ?" % ", ".join(sets), values)
    return get_learner(learner_id)


def get_learner(learner_id):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM learners WHERE id = ?", (learner_id,)
        ).fetchone())


def list_learners():
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM learners ORDER BY updated_at DESC"
        ).fetchall()]


# -- paths ------------------------------------------------------------------

def save_path(learner_id, path_data, courses, adapted_from=None, note=""):
    """Persist a generated path plus its ordered courses. Returns path id."""
    with connect() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM paths WHERE learner_id = ?",
            (learner_id,),
        ).fetchone()["v"]

        # Only one active path per learner; older versions stay for history.
        conn.execute(
            "UPDATE paths SET is_active = 0 WHERE learner_id = ?", (learner_id,)
        )

        cur = conn.execute(
            """INSERT INTO paths
               (learner_id, version, path_name, description, career_outcome,
                target_role, milestones, skill_gap, adapted_from,
                adaptation_note, is_active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""",
            (
                learner_id,
                version,
                path_data.get("path_name", "Learning Path"),
                path_data.get("description", ""),
                path_data.get("career_outcome", ""),
                path_data.get("target_role"),
                json.dumps(path_data.get("milestones", [])),
                json.dumps(path_data.get("skill_gap", {})),
                adapted_from,
                note,
                now(),
            ),
        )
        path_id = cur.lastrowid

        for position, c in enumerate(courses):
            conn.execute(
                """INSERT INTO path_courses
                   (path_id, position, course_id, reason, targets_skills,
                    milestone_index, project)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    path_id,
                    position,
                    c["course_id"],
                    c.get("reason", ""),
                    json.dumps(c.get("targets_skills", [])),
                    int(c.get("milestone_index", 0) or 0),
                    c.get("project", ""),
                ),
            )
        return path_id


def get_active_path(learner_id):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM paths WHERE learner_id = ? AND is_active = 1 "
            "ORDER BY id DESC LIMIT 1",
            (learner_id,),
        ).fetchone())


def get_path(path_id):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM paths WHERE id = ?", (path_id,)
        ).fetchone())


def get_path_courses(path_id):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM path_courses WHERE path_id = ? ORDER BY position",
            (path_id,),
        ).fetchall()]


def list_paths(learner_id):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, version, path_name, is_active, adaptation_note, created_at "
            "FROM paths WHERE learner_id = ? ORDER BY version DESC",
            (learner_id,),
        ).fetchall()]


def set_course_completed(path_course_id, completed):
    with connect() as conn:
        conn.execute(
            "UPDATE path_courses SET completed = ?, completed_at = ? WHERE id = ?",
            (1 if completed else 0, now() if completed else None, path_course_id),
        )
        return _row(conn.execute(
            "SELECT * FROM path_courses WHERE id = ?", (path_course_id,)
        ).fetchone())


# -- skills -----------------------------------------------------------------

def add_skill(learner_id, skill, source="manual"):
    skill = skill.strip().lower()
    if not skill:
        return None
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO learner_skills (learner_id, skill, source, created_at) "
            "VALUES (?,?,?,?)",
            (learner_id, skill, source, now()),
        )
    return skill


def get_skills(learner_id):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT skill, source, created_at FROM learner_skills "
            "WHERE learner_id = ? ORDER BY created_at",
            (learner_id,),
        ).fetchall()]


def remove_skill(learner_id, skill):
    with connect() as conn:
        conn.execute(
            "DELETE FROM learner_skills WHERE learner_id = ? AND skill = ?",
            (learner_id, skill.strip().lower()),
        )


# -- feedback ---------------------------------------------------------------

def add_feedback(learner_id, signal, path_id=None, course_id=None, comment=""):
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO feedback
               (learner_id, path_id, course_id, signal, comment, created_at)
               VALUES (?,?,?,?,?,?)""",
            (learner_id, path_id, course_id, signal, comment, now()),
        )
        return cur.lastrowid


def get_feedback(learner_id, path_id=None):
    sql = "SELECT * FROM feedback WHERE learner_id = ?"
    args = [learner_id]
    if path_id is not None:
        sql += " AND path_id = ?"
        args.append(path_id)
    sql += " ORDER BY id"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


# -- assessments ------------------------------------------------------------

def save_assessment(path_id, milestone_index, title, questions, targets_skills,
                    pass_mark=70):
    """Store a generated milestone assessment (one per milestone per path)."""
    with connect() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO assessments
               (path_id, milestone_index, title, questions, targets_skills,
                pass_mark, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (path_id, milestone_index, title, json.dumps(questions),
             json.dumps(targets_skills), pass_mark, now()),
        )
        return cur.lastrowid


def get_assessment(assessment_id):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
        ).fetchone())


def get_assessment_for_milestone(path_id, milestone_index):
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM assessments WHERE path_id = ? AND milestone_index = ?",
            (path_id, milestone_index),
        ).fetchone())


def list_assessments(path_id):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM assessments WHERE path_id = ? ORDER BY milestone_index",
            (path_id,),
        ).fetchall()]


def record_attempt(assessment_id, learner_id, score, total, passed, answers):
    percent = round(score / total * 100, 1) if total else 0.0
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO assessment_attempts
               (assessment_id, learner_id, score, total, percent, passed,
                answers, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (assessment_id, learner_id, score, total, percent,
             1 if passed else 0, json.dumps(answers), now()),
        )
        return cur.lastrowid


def best_attempt(assessment_id, learner_id):
    """Highest-scoring attempt, which is what decides skill credit."""
    with connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM assessment_attempts WHERE assessment_id = ? "
            "AND learner_id = ? ORDER BY percent DESC, id DESC LIMIT 1",
            (assessment_id, learner_id),
        ).fetchone())


def count_attempts(assessment_id, learner_id):
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM assessment_attempts "
            "WHERE assessment_id = ? AND learner_id = ?",
            (assessment_id, learner_id),
        ).fetchone()["n"]


# -- chat -------------------------------------------------------------------

def add_message(learner_id, role, content):
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (learner_id, role, content, created_at) "
            "VALUES (?,?,?,?)",
            (learner_id, role, content, now()),
        )


def get_messages(learner_id, limit=20):
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages "
            "WHERE learner_id = ? ORDER BY id DESC LIMIT ?",
            (learner_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
