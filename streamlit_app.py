"""Learning Pathfinder — Streamlit deployment entry point.

Single-process version of the app for Streamlit Community Cloud. It calls
`engine.service` directly instead of over HTTP, so there is no FastAPI process
and no second copy of the business logic: this file is presentation only.

Run locally:   streamlit run streamlit_app.py
"""

import os

import streamlit as st
from dotenv import load_dotenv

from engine import service, store
from engine.recommender import extract_profile
from engine.retrieval import CourseIndex
from engine.service import ServiceError

load_dotenv()

st.set_page_config(
    page_title="Learning Pathfinder",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -- bootstrap --------------------------------------------------------------

def get_api_key():
    """Streamlit Cloud supplies secrets; local dev uses .env."""
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:
        # No secrets.toml present at all — fall through to the environment.
        pass
    return os.getenv("GROQ_API_KEY")


@st.cache_resource(show_spinner=False)
def get_index():
    """The BM25 index is built once per container, not per rerun."""
    return CourseIndex()


@st.cache_resource(show_spinner=False)
def get_client(api_key):
    return service.build_client(api_key)


@st.cache_resource(show_spinner=False)
def ensure_db():
    store.init_db()
    return True


API_KEY = get_api_key()
if not API_KEY:
    st.error("**GROQ_API_KEY is not configured.**")
    st.markdown(
        "- **Local:** copy `.env.example` to `.env` and add your key\n"
        "- **Streamlit Cloud:** add it under *App settings → Secrets* as "
        "`GROQ_API_KEY = \"gsk_...\"`\n\n"
        "Get a free key at [console.groq.com/keys](https://console.groq.com/keys)."
    )
    st.stop()

ensure_db()
index = get_index()
client = get_client(API_KEY)

SIGNALS = {
    "helpful": "Helpful",
    "too_hard": "Too hard",
    "too_easy": "Too easy",
    "not_relevant": "Not relevant",
}


def flash(message, kind="success"):
    """Queue a message to show after the rerun that follows an action."""
    st.session_state["_flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("_flash", None)
    if not item:
        return
    kind, message = item
    {"success": st.success, "info": st.info,
     "warning": st.warning, "error": st.error}[kind](message)


# -- onboarding -------------------------------------------------------------

EXAMPLES = [
    "I'm a final-year CS student. I know basic Python and SQL and want to become "
    "a backend engineer. I can study about 10 hours a week and learn best by "
    "building things.",
    "I work in marketing and want to move into data analysis. I'm comfortable "
    "with Excel but have never coded. Maybe 5 hours a week.",
    "I've been writing React for a year and want to go full stack with Node. "
    "I have about 12 hours a week.",
]


def render_onboarding():
    st.title("🧭 Learning Pathfinder")
    st.caption(
        "Describe where you want to get to. You'll get a sequenced roadmap of "
        "real courses that explains every step."
    )

    # Listing every learner leaks names and goals to anyone who opens a public
    # deployment. There is no authentication, so the roster is opt-in and off
    # by default; set PATHFINDER_SHOW_LEARNERS=1 for local or single-user use.
    existing = (store.list_learners()
                if os.getenv("PATHFINDER_SHOW_LEARNERS") == "1" else [])
    if existing:
        with st.expander("Continue as an existing learner"):
            for learner in existing[:10]:
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"**{learner['name']}** — {learner['goals'] or 'no goal set'}")
                if col_b.button("Open", key=f"open_{learner['id']}"):
                    st.session_state["learner_id"] = learner["id"]
                    st.rerun()

    st.subheader("What do you want to learn?")

    draft = st.session_state.get("intake_text", "")
    text = st.text_area(
        "Tell me where you are now, where you want to get to, and how much time "
        "you have.",
        value=draft,
        height=130,
        placeholder="I'm a CS student who knows some Python. I want to become a "
                    "backend engineer...",
    )

    st.caption("Or start from an example:")
    cols = st.columns(3)
    for i, example in enumerate(EXAMPLES):
        if cols[i].button(f"Example {i + 1}", key=f"ex_{i}", width="stretch"):
            st.session_state["intake_text"] = example
            st.rerun()

    if st.button("Continue", type="primary", disabled=len(text.strip()) < 10):
        with st.spinner("Understanding your goal..."):
            try:
                profile = extract_profile(client, service.get_model(), text)
            except Exception as exc:
                st.error(f"Could not read that: {exc}")
                return
        st.session_state["draft_profile"] = profile
        st.session_state["intake_text"] = text
        st.rerun()


def render_profile_review():
    profile = st.session_state["draft_profile"]
    st.title("Here's what I understood")
    st.caption("Correct anything I got wrong before we build your roadmap.")

    col_a, col_b = st.columns(2)
    name = col_a.text_input("Name", profile.get("name") or "Learner")
    goals = col_b.text_input("Goal", profile.get("goals", ""))
    interests = col_a.text_input("Interests", profile.get("interests", ""))
    known = col_b.text_input("Already know", profile.get("completed_learning", ""))

    levels = ["beginner", "intermediate", "advanced"]
    level = col_a.selectbox(
        "Experience level", levels,
        index=levels.index(profile.get("experience_level", "beginner")),
    )
    hours = col_b.number_input(
        "Hours per week", min_value=1, max_value=80,
        value=int(profile.get("weekly_hours", 8)),
    )

    preview = index.skill_gap({"goals": goals, "completed_learning": known})
    if preview["role"]:
        st.info(
            f"**Matched to: {preview['role']}** — "
            f"{preview['coverage_percent']}% of the required skills already covered. "
            f"Your path will close these gaps: "
            f"{', '.join(preview['missing_skills'][:8])}"
        )
    else:
        st.warning(
            "I couldn't match that goal to a role I know. You'll still get a path, "
            "but try naming a role (e.g. 'backend engineer', 'data analyst')."
        )

    if profile.get("followup"):
        st.caption(f"💬 {profile['followup']}")

    col_go, col_back = st.columns([2, 1])
    if col_go.button("Looks right — continue", type="primary", width="stretch"):
        learner_id = store.create_learner({
            "name": name, "goals": goals, "interests": interests,
            "completed_learning": known, "experience_level": level,
            "weekly_hours": int(hours),
        })
        st.session_state["learner_id"] = learner_id
        st.session_state.pop("draft_profile", None)
        st.session_state.pop("intake_text", None)
        st.rerun()

    if col_back.button("Start over", width="stretch"):
        st.session_state.pop("draft_profile", None)
        st.rerun()


# -- path -------------------------------------------------------------------

def render_path(learner, path):
    if path is None:
        st.subheader("Ready to build your roadmap")
        st.write(
            f"We'll match {learner['name']} against the {len(index.courses)}-course "
            "catalog, work out the skill gaps for your goal, and sequence a path "
            "that closes them."
        )
        if st.button("Generate my learning path", type="primary"):
            with st.spinner("Retrieving courses and building your path..."):
                try:
                    service.generate_and_store(client, index, learner)
                except ServiceError as exc:
                    st.error(str(exc))
                    return
            flash("Your personalised path is ready.")
            st.rerun()
        return

    st.subheader(path["path_name"])
    meta = [f"v{path['version']}"]
    if path["target_role"]:
        meta.append(f"Target role: {path['target_role']}")
    st.caption(" · ".join(meta))
    if path["description"]:
        st.write(path["description"])

    st.progress(
        path["progress_percent"] / 100,
        text=f"{path['completed_count']}/{path['course_count']} courses · "
             f"{path['completed_hours']}h of {path['total_hours']}h · "
             f"{path['progress_percent']}%",
    )

    if path["adaptation_note"]:
        st.caption(f"_{path['adaptation_note']}_")
    if path["career_outcome"]:
        st.success(f"**Outcome:** {path['career_outcome']}")

    with st.expander("Adapt this path"):
        st.caption(
            "Your recorded feedback and completed courses are taken into account. "
            "Add anything else you want changed."
        )
        note = st.text_input(
            "Extra instruction (optional)",
            placeholder="e.g. keep it practical, less theory, focus on APIs",
            key="adapt_note",
        )
        if st.button("Rebuild path"):
            with st.spinner("Rebuilding around your feedback..."):
                try:
                    updated = service.adapt(client, index, learner, note)
                except ServiceError as exc:
                    st.error(str(exc))
                    return
            flash(f"Path rebuilt as version {updated['version']}.")
            st.rerun()

    st.divider()

    milestones = path["milestones"]
    for m_index, milestone in enumerate(milestones):
        group = [c for c in path["courses"] if c["milestone_index"] == m_index]
        if not group:
            continue
        done = sum(1 for c in group if c["completed"])
        st.markdown(f"##### 🚩 {milestone}  ·  {done}/{len(group)}")
        for course in group:
            render_course(learner, course)
        st.write("")

    orphans = [c for c in path["courses"]
               if c["milestone_index"] >= len(milestones)]
    if orphans:
        st.markdown("##### Further work")
        for course in orphans:
            render_course(learner, course)


def render_course(learner, course):
    mark = "✅" if course["completed"] else "⬜"
    header = (f"{mark}  {course['position'] + 1}. {course['title']}  ·  "
              f"{course['provider']} · {course['hours']}h · {course['level']}")

    with st.expander(header, expanded=False):
        if course["reason"]:
            st.info(f"**Why this, for you:** {course['reason']}")

        if course["targets_skills"]:
            st.caption("Closes gap: " + ", ".join(course["targets_skills"]))

        st.write(course["description"])
        st.markdown(f"[Open the course]({course['url']})")

        if course["prerequisites"]:
            st.caption("Builds on: " + ", ".join(course["prerequisites"]))

        if course["project"]:
            st.markdown(f"🔨 **Project to prove it:** {course['project']}")

        col_done, col_fb = st.columns([1, 2])
        label = "Mark as not done" if course["completed"] else "Mark complete"
        if col_done.button(label, key=f"done_{course['path_course_id']}"):
            service.complete_course(
                index, course["path_course_id"], not course["completed"]
            )
            st.rerun()

        signal = col_fb.selectbox(
            "How is it working out?",
            ["", *SIGNALS.keys()],
            format_func=lambda k: "Give feedback..." if k == "" else SIGNALS[k],
            key=f"sig_{course['path_course_id']}",
        )
        if signal:
            if col_fb.button("Record feedback", key=f"fb_{course['path_course_id']}"):
                active = store.get_active_path(learner["id"])
                store.add_feedback(
                    learner["id"], signal,
                    path_id=active["id"] if active else None,
                    course_id=course["course_id"],
                )
                flash("Feedback recorded — use *Adapt this path* to rebuild around it.",
                      "info")
                st.rerun()


# -- checkpoints ------------------------------------------------------------

def render_checkpoints(learner):
    statuses = service.assessment_status(index, learner["id"])
    if not statuses:
        st.info("Generate a learning path first — checkpoints follow its milestones.")
        return

    st.caption(
        "Each stage ends in a checkpoint. Finish every course in a stage to "
        "unlock it. Passing credits that stage's skills as evidence rather than "
        "self-report."
    )

    for status in statuses:
        title = f"{'✅' if status['passed'] else '🔒' if not status['unlocked'] else '📝'}  {status['milestone']}"
        with st.expander(title, expanded=status["unlocked"] and not status["passed"]):
            if not status["unlocked"]:
                st.write(
                    f"Locked — {status['courses_completed']}/{status['courses_total']} "
                    "courses in this stage complete."
                )
                continue

            if status["best_percent"] is not None:
                st.caption(
                    f"Best score {status['best_percent']}% over "
                    f"{status['attempts']} attempt(s)"
                )

            render_quiz(learner, status)


def render_quiz(learner, status):
    key = f"quiz_{status['milestone_index']}"
    result_key = f"result_{status['milestone_index']}"

    if st.session_state.get(result_key):
        render_quiz_result(st.session_state[result_key], key, result_key)
        return

    if key not in st.session_state:
        label = "Retake checkpoint" if status["attempts"] else "Take checkpoint"
        if st.button(label, key=f"start_{status['milestone_index']}", type="primary"):
            with st.spinner("Writing questions from the courses you completed..."):
                try:
                    st.session_state[key] = service.get_or_create_assessment(
                        client, index, learner, status["milestone_index"]
                    )
                except ServiceError as exc:
                    st.error(str(exc))
                    return
            st.rerun()
        return

    quiz = st.session_state[key]
    st.markdown(f"**{quiz['title']}**")
    st.caption(
        f"{quiz['required_correct']} of {len(quiz['questions'])} correct to pass."
    )

    answers = []
    for q_index, question in enumerate(quiz["questions"]):
        choice = st.radio(
            f"{q_index + 1}. {question['question']}",
            options=list(range(len(question["options"]))),
            format_func=lambda i, opts=question["options"]: opts[i],
            index=None,
            key=f"{key}_q{q_index}",
        )
        answers.append(-1 if choice is None else choice)

    unanswered = sum(1 for a in answers if a < 0)
    col_submit, col_cancel = st.columns([2, 1])
    if col_submit.button(
        f"Submit checkpoint ({len(answers) - unanswered}/{len(answers)} answered)",
        key=f"submit_{status['milestone_index']}",
        type="primary",
        disabled=unanswered > 0,
    ):
        st.session_state[result_key] = service.submit_assessment(
            quiz["assessment_id"], answers
        )
        st.rerun()

    if col_cancel.button("Cancel", key=f"cancel_{status['milestone_index']}"):
        st.session_state.pop(key, None)
        st.rerun()


def render_quiz_result(result, key, result_key):
    if result["passed"]:
        st.success(
            f"**Passed — {result['score']}/{result['total']} ({result['percent']}%)**. "
            "Skills credited to your profile."
        )
        if result["skills_credited"]:
            st.caption("Credited: " + ", ".join(result["skills_credited"]))
    else:
        st.warning(
            f"**{result['score']}/{result['total']} ({result['percent']}%)** — "
            f"needs {result['required_correct']} of {result['total']} correct. "
            "Review and try again."
        )

    for item in result["results"]:
        icon = "✅" if item["correct"] else "❌"
        st.markdown(f"{icon} {item['question']}")
        if not item["correct"] and item["explains"]:
            st.caption(f"↳ {item['explains']}")

    if st.button("Done", key=f"clear_{result_key}"):
        st.session_state.pop(key, None)
        st.session_state.pop(result_key, None)
        st.rerun()


# -- dashboard --------------------------------------------------------------

def render_dashboard(learner):
    data = service.dashboard(index, learner["id"])
    gap = data["skill_gap"]

    if not data["has_path"]:
        st.info("No path yet — head to **My path** to build one.")
        render_skill_log(learner, data)
        return

    summary = data["path_summary"]

    st.metric("Overall progress", f"{summary['progress_percent']}%",
              help="Derived from courses actually completed.")
    st.progress(summary["progress_percent"] / 100)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Courses done",
                f"{summary['completed_count']}/{summary['course_count']}")
    col2.metric("Hours done", f"{summary['completed_hours']}h",
                help=f"of {summary['total_hours']}h total")
    col3.metric("Weeks left", data["estimated_weeks_remaining"] or "—",
                help=f"at {learner['weekly_hours']}h/week")
    col4.metric("Skill coverage", f"{gap['coverage_percent']}%",
                help=f"{len(gap['covered_skills'])}/{len(gap['target_skills'])} skills")

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("##### Milestones")
        for milestone in data["milestones"]:
            icon = "✅" if milestone["reached"] else "○"
            st.progress(
                milestone["percent"] / 100,
                text=f"{icon} {milestone['name']} — "
                     f"{milestone['completed']}/{milestone['total']}",
            )
        with st.expander("Table view"):
            st.dataframe(
                [
                    {"Milestone": m["name"], "Done": m["completed"],
                     "Total": m["total"], "%": m["percent"]}
                    for m in data["milestones"]
                ],
                hide_index=True,
                width="stretch",
            )

    with col_right:
        st.markdown("##### Skill development")
        label = f"Readiness for {gap['role']}" if gap["role"] else "Goal readiness"
        st.progress(
            gap["coverage_percent"] / 100,
            text=f"{label} — {len(gap['covered_skills'])} of "
                 f"{len(gap['target_skills'])}",
        )
        if gap["covered_skills"]:
            st.markdown("**Covered**")
            st.caption(" · ".join(gap["covered_skills"]))
        if gap["missing_skills"]:
            st.markdown("**Still missing**")
            st.caption(" · ".join(gap["missing_skills"]))

    st.divider()
    st.markdown("##### Next recommended actions")
    for action in data["next_actions"]:
        icon = {"course": "📘", "project": "🔨", "skill": "🎯"}.get(action["kind"], "▶")
        st.markdown(f"{icon} **{action['title']}**")
        st.caption(action["detail"])
        if action.get("url"):
            st.markdown(f"[Open course]({action['url']})")

    st.divider()
    render_skill_log(learner, data)


def render_skill_log(learner, data):
    st.markdown("##### Your skills")
    sources = data["skills_by_source"]

    if sources["from_assessments"]:
        st.markdown("**Proven by checkpoint**")
        st.caption(" · ".join(sorted(set(sources["from_assessments"]))))
    if sources["from_courses"]:
        st.markdown("**Credited from completed courses**")
        st.caption(" · ".join(sorted(set(sources["from_courses"]))))

    st.markdown("**Self-reported**")
    if sources["self_reported"]:
        st.caption(" · ".join(sources["self_reported"]))
    else:
        st.caption("None logged yet.")

    col_in, col_btn = st.columns([3, 1])
    new_skill = col_in.text_input(
        "Log a skill you already have", key="skill_input",
        placeholder="e.g. docker", label_visibility="collapsed",
    )
    if col_btn.button("Add", width="stretch") and new_skill.strip():
        store.add_skill(learner["id"], new_skill)
        st.rerun()


# -- assistant --------------------------------------------------------------

SUGGESTIONS = [
    "Why was this course recommended to me?",
    "What should I do this week?",
    "Which skill am I furthest behind on?",
]


def render_assistant(learner):
    st.caption("Grounded in your actual path, progress and skill gaps.")

    history = store.get_messages(learner["id"], limit=30)
    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if not history:
        st.caption("Try asking:")
        cols = st.columns(len(SUGGESTIONS))
        for i, suggestion in enumerate(SUGGESTIONS):
            if cols[i].button(suggestion, key=f"sug_{i}", width="stretch"):
                st.session_state["pending_question"] = suggestion
                st.rerun()

    question = st.chat_input("Ask about your learning path...")
    pending = st.session_state.pop("pending_question", None)
    question = question or pending

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    answer = service.chat(client, index, learner, question)
                except ServiceError as exc:
                    st.error(str(exc))
                    return
            st.markdown(answer)
        st.rerun()


# -- sidebar / shell --------------------------------------------------------

def render_sidebar(learner):
    with st.sidebar:
        st.markdown(f"### {learner['name']}")
        st.caption(learner["goals"] or "No goal set")

        gap = index.skill_gap(
            dict(learner), acquired_skills=service.acquired_skills(learner["id"])
        )
        if gap["role"]:
            st.metric("Readiness", f"{gap['coverage_percent']}%", label_visibility="visible")
            st.caption(f"toward {gap['role']}")

        st.divider()
        with st.expander("Edit profile"):
            goals = st.text_input("Goal", learner["goals"])
            hours = st.number_input(
                "Hours per week", 1, 80, int(learner["weekly_hours"])
            )
            if st.button("Save"):
                store.update_learner(
                    learner["id"], {"goals": goals, "weekly_hours": int(hours)}
                )
                flash("Profile updated. Adapt your path to apply it.", "info")
                st.rerun()

        versions = store.list_paths(learner["id"])
        if versions:
            st.caption("**Path history**")
            for v in versions[:5]:
                marker = "●" if v["is_active"] else "○"
                st.caption(f"{marker} v{v['version']} — {v['path_name']}")

        st.divider()
        if st.button("Switch learner", width="stretch"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.caption(f"Model: `{service.get_model()}`")
        st.caption(f"Catalog: {len(index.courses)} courses · {len(index.roles)} roles")


def main():
    show_flash()

    if "learner_id" not in st.session_state:
        if "draft_profile" in st.session_state:
            render_profile_review()
        else:
            render_onboarding()
        return

    learner = store.get_learner(st.session_state["learner_id"])
    if learner is None:
        # The database was reset underneath us (ephemeral filesystem).
        st.session_state.clear()
        st.rerun()

    render_sidebar(learner)
    st.title("🧭 Learning Pathfinder")

    tab_dash, tab_path, tab_check, tab_chat = st.tabs(
        ["Dashboard", "My path", "Checkpoints", "Assistant"]
    )

    with tab_dash:
        render_dashboard(learner)
    with tab_path:
        render_path(learner, service.active_path(index, learner["id"]))
    with tab_check:
        render_checkpoints(learner)
    with tab_chat:
        render_assistant(learner)


if __name__ == "__main__":
    main()
