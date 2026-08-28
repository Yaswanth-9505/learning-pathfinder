# Learning Pathfinder

**AI-powered personalised learning path recommender.** Describe your goal in
plain English; get a sequenced roadmap of real courses, with an explanation for
every recommendation, progress tracking, and a path that adapts to your feedback.

---

## Two ways to run it

| Surface | Entry point | Use for |
|---|---|---|
| **Streamlit** | `streamlit_app.py` | One-command local run, and one-click cloud deployment |
| **React + FastAPI** | `npm run dev` | The full-fidelity UI, and a REST API for other clients |

Both call the same `engine/service.py`, so behaviour is identical — there is no
second implementation of the rules.

---

## Quick start

**Prerequisites:** Python 3.9+ and a free
[Groq API key](https://console.groq.com/keys). Node.js 18+ only for Option B.

### Option A — Streamlit (simplest)

```bash
pip install -r requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
#   then edit .env and set GROQ_API_KEY

streamlit run streamlit_app.py
```

Open **http://localhost:8501**. No Node, no second process.

### Option B — React + FastAPI

```bash
npm install
pip install -r requirements-api.txt   # includes requirements.txt
cp .env.example .env                  # then set GROQ_API_KEY

npm run dev
```

| Service  | URL                     |
|----------|-------------------------|
| Frontend | http://localhost:5173   |
| API      | http://localhost:8000   |
| API docs | http://localhost:8000/docs |

Prerequisites for Option A are Python only. Run the tests with
`npm test` or `pytest -q` (55 tests, no API key or network required).

---

## What it does

1. **Describe your goal in natural language.** "I'm a CS student who knows some
   Python and wants to become a backend engineer, ~10 hours a week."
2. The system **extracts a structured profile** and shows it to you to correct.
3. It **matches your goal to a target role** and computes your **skill gap**.
4. It **retrieves relevant courses** from a curated catalog and asks the LLM to
   **select, sequence and justify** them.
5. You get a **roadmap grouped into milestones**, each course carrying a reason
   written for *you*, its prerequisites, and a project to prove the skill.
6. As you **complete courses**, their skills are credited and your gap closes.
7. Finish every course in a stage to unlock its **checkpoint assessment** — five
   application-level questions, graded server-side. Passing credits that stage's
   skills as *evidence* rather than self-report.
8. **Rate courses** (too hard / too easy / not relevant / helpful) and hit
   **Adapt path** to have it rebuilt around that feedback.
9. Ask the **assistant** anything — it answers grounded in your actual path.

---

## Architecture

```
                    React + Vite + Tailwind  (port 5173)
                     |  Onboarding · PathView · Assessment · Dashboard · Assistant
                     |
                     v  REST/JSON
                   FastAPI  (port 8000)
                     |
     +---------------+----------------+------------------+
     |               |                |                  |
  BM25 retrieval  Skill-gap        Groq LLM           SQLite
  over catalog    analysis         (curation +        (learners, paths,
  (pure Python)   (role model)      explanation)       progress, feedback)
```

**The key design decision:** the LLM never supplies course facts. Retrieval
selects real courses from `data/courses.json`; the model only curates, orders
and explains. Any course id it invents is dropped before it reaches the UI, so
every title, provider and URL you see is genuine.

### Pipeline

| Stage | Technique | Where |
|---|---|---|
| Profile extraction | LLM structured extraction (JSON mode) | `engine/recommender.py` |
| Role matching | Alias-token overlap against 14 role profiles | `engine/retrieval.py` |
| Skill gap | Set difference: role skills − learner skills | `engine/retrieval.py` |
| Candidate retrieval | **Okapi BM25**, weighted fields, level- and style-biased | `engine/retrieval.py` |
| Curation & ordering | LLM over the retrieved shortlist (RAG) | `engine/recommender.py` |
| Validation | Catalog id check, dedupe, clamp, backfill | `engine/recommender.py` |
| Prerequisites | Derived from ordering ∩ skill overlap | `engine/recommender.py` |
| Assessments | LLM-generated MCQs + server-side grading, options shuffled | `engine/recommender.py` |
| Adaptation | Feedback + completions re-injected into the prompt | `backend.py` |

BM25 is implemented in pure Python — no embedding model, no gigabyte download,
and the ranking is inspectable.

---

## Project layout

```
streamlit_app.py        Streamlit entry point (deployment target)
backend.py              FastAPI app: 28 routes (thin transport)
api.js                  Frontend API client
frontend.jsx            App shell, tab routing, session restore
main.jsx / App.jsx      React entry points
components/
  Onboarding.jsx        Conversational intake + profile review
  PathView.jsx          Roadmap, milestones, completion, feedback
  Assessment.jsx        Milestone checkpoint quiz and results
  Dashboard.jsx         Progress, skill gap, milestones, next actions
  ChatAssistant.jsx     Grounded Q&A
engine/
  service.py            Shared business logic — both surfaces call this
  retrieval.py          BM25 index, role matching, skill-gap analysis
  recommender.py        RAG pipeline, validation, derived structure
  store.py              SQLite schema and persistence
data/
  courses.json          61-course catalog (real courses and URLs)
  roles.json            14 target-role skill profiles
  pathfinder.db         created on first run
eval/
  goldens.json          12 labelled goals, 87 relevance judgements
  evaluate.py           IR metrics vs 3 baselines, offline
tests/test_engine.py         39 engine tests
tests/test_streamlit_app.py   7 Streamlit render tests (AppTest)
tests/test_evaluation.py      9 recommendation-quality guards
docs/
  solution-documentation.html/.pdf   Solution documentation
  demo-script.md                     Demo video script and shot list
scripts/build_zip.py    Submission packaging
```

---

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Service, model and catalog status |
| GET | `/api/catalog?q=` | Browse or search the course corpus |
| POST | `/api/profile/extract` | Natural language → structured profile |
| POST | `/api/learners` | Create a learner |
| GET/PATCH | `/api/learners/{id}` | Read / update profile |
| POST | `/api/learners/{id}/generate-path` | Build the roadmap |
| POST | `/api/learners/{id}/adapt-path` | Rebuild from feedback |
| GET | `/api/learners/{id}/path` | Active path with courses |
| GET | `/api/learners/{id}/paths` | Version history |
| POST | `/api/path-courses/{id}/complete` | Mark done, credit skills |
| GET | `/api/learners/{id}/dashboard` | All progress metrics |
| GET | `/api/learners/{id}/assessments` | Checkpoint status per milestone |
| POST | `/api/learners/{id}/assessments/{i}` | Generate a stage checkpoint |
| POST | `/api/assessments/{id}/submit` | Grade an attempt, credit skills |
| GET | `/api/learners/{id}/explain/{course_id}` | Why this course |
| GET/POST | `/api/learners/{id}/skills` | Skill log |
| GET/POST | `/api/learners/{id}/feedback` | Feedback signals |
| GET/POST | `/api/learners/{id}/chat` | Assistant + history |

Interactive docs at http://localhost:8000/docs.

---

## Configuration

Set in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Your Groq key |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Any Groq text model |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allowlist (FastAPI only) |
| `PATHFINDER_DB` | `data/pathfinder.db` | SQLite location; point at a volume in production |
| `PATHFINDER_SHOW_LEARNERS` | unset | Set to `1` to list existing learners on the start screen. Off by default: with no authentication, a public deployment would otherwise expose every learner's name and goal. |

The frontend reads `VITE_API_URL` (default `http://localhost:8000`).

---

## Extending the catalog

Add an entry to `data/courses.json` — it is indexed on next start, no retraining:

```json
{
  "id": "unique-slug",
  "title": "Course Title",
  "provider": "Provider",
  "url": "https://...",
  "level": "beginner|intermediate|advanced",
  "hours": 20,
  "domains": ["backend"],
  "skills": ["rest-api", "python"],
  "format": ["video", "hands-on"],
  "description": "One or two sentences."
}
```

`tests/test_engine.py::test_every_role_skill_is_teachable` guards that every
skill a role requires is taught by at least one course.

---

## Evaluation

Retrieval quality is measured, not asserted. `eval/goldens.json` holds 12
labelled goals with 87 relevance judgements; `eval/evaluate.py` scores the
ranker against three baselines and runs offline with no API key:

```bash
python eval/evaluate.py --detail
```

| Method | R@5 | R@10 | **R@16** | P@10 | nDCG@10 | MRR | SkillCov@16 |
|---|---|---|---|---|---|---|---|
| **BM25 (ours)** | 0.626 | 0.831 | **0.921** | 0.558 | 0.869 | 1.000 | 0.985 |
| title-match | 0.220 | 0.301 | 0.375 | 0.208 | 0.355 | 0.696 | 0.516 |
| catalog order | 0.041 | 0.146 | 0.221 | 0.117 | 0.126 | 0.217 | 0.321 |
| random (5 seeds) | 0.083 | 0.174 | 0.270 | 0.127 | 0.155 | 0.282 | 0.469 |

**Recall@16 is the number that matters** — 16 is the shortlist size the LLM
receives, so it caps what any generated path can possibly contain. At 0.921 it
is 3.4x the random floor. **MRR 1.000** means the top-ranked course is relevant
for every labelled goal. **SkillCov@16 0.985** is the product metric: the
shortlist covers 98.5% of the skills the target role requires, so the gap the
path is built to close is nearly always coverable.

These thresholds are pinned by `tests/test_evaluation.py`, so a change that
degrades ranking fails CI rather than surfacing in a demo.

---

## Deploying to Streamlit Community Cloud

The Streamlit surface is the deployable one — it is a single Python process, so
it fits Streamlit Cloud's model without a separate API service.

**1. Push to GitHub.** The repo must contain `streamlit_app.py`,
`requirements.txt` and `runtime.txt` at the root (they are).

**2. Create the app.** Streamlit Cloud installs `requirements.txt`, which
deliberately contains only the three packages the Streamlit surface needs — the
FastAPI stack sits in `requirements-api.txt` and is not installed there.

 At [share.streamlit.io](https://share.streamlit.io),
click *New app*, pick the repo and branch, and set the main file path to:

```
streamlit_app.py
```

**3. Add your key.** Open *Advanced settings → Secrets* (or *App settings →
Secrets* after creation) and paste:

```toml
GROQ_API_KEY = "gsk_your_key_here"
GROQ_MODEL = "openai/gpt-oss-120b"
```

See `.streamlit/secrets.toml.example`. Never commit the real key — `.env` and
`.streamlit/secrets.toml` are both git-ignored.

**4. Deploy.** First build takes a few minutes while dependencies install.

### What ships in the deployment

| File | Role |
|---|---|
| `streamlit_app.py` | App entry point (Streamlit Cloud looks for this name) |
| `requirements.txt` | Streamlit dependencies only (3 packages) |
| `runtime.txt` | Pins Python 3.12 |
| `.streamlit/config.toml` | Dark theme matching the app |
| `.streamlit/secrets.toml.example` | Template — the real file is git-ignored |

### Deployment caveats — read these

**Data does not survive a restart.** Streamlit Community Cloud gives the
container an ephemeral filesystem, so `data/pathfinder.db` is wiped on reboot,
redeploy, or when the app sleeps after inactivity. Learners, paths and progress
go with it. This is fine for a demo or an evaluation, and wrong for real users.
To fix it properly, point `PATHFINDER_DB` at a mounted volume or migrate
`engine/store.py` to a hosted Postgres — the schema is plain SQL and the store
module is the only file that would change.

**There is still no authentication.** Every visitor to the deployed URL sees the
same learner list and can open any profile. Do not put real personal data in a
public deployment.

**The free Groq tier caps at 8,000 tokens/minute account-wide.** A public URL
means strangers share that budget, so two people generating paths at once will
see rate-limit errors. Use a paid tier for anything beyond a demo.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `GROQ_API_KEY not set` | Create `.env` from `.env.example` and add your key |
| `model has been decommissioned` | Set a current `GROQ_MODEL`; see [Groq models](https://console.groq.com/docs/models) |
| `413 Request too large` | Free tier is 8,000 tokens/min — wait a minute between generations |
| `Client.__init__() got an unexpected keyword argument 'proxies'` | Old `groq` SDK: `pip install --upgrade groq` |
| Blank page, `process is not defined` | Vite uses `import.meta.env`, not `process.env` |
| Unstyled page | `postcss.config.js` must exist for Tailwind to compile |
| CORS error | Add your origin to `ALLOWED_ORIGINS` |
| `Router.__init__() got an unexpected keyword argument` | FastAPI/Starlette mismatch: `pip install --upgrade fastapi` |
| Streamlit app loses all data | Expected on Community Cloud — see deployment caveats |

### Known limits

- The Groq **free tier caps at 8,000 tokens/minute**, and one path generation
  uses roughly 4,000. That is about one generation per minute for one user;
  a paid tier is required for concurrent or public use.
- There is **no authentication**. The learner id is held in `localStorage`, so
  anyone with the id can read that learner. Do not deploy publicly as-is.
- The catalog is **curated, not crawled** — 61 courses, not thousands.
- Checkpoints are **multiple-choice only**. They test recognition of the right
  approach, not the ability to build the thing; the per-course projects cover
  that, but nothing verifies a project was actually done.

---

## Tech stack

**Shared core:** Python 3.12 · SQLite · Groq (`openai/gpt-oss-120b`) · pytest
**Streamlit surface:** Streamlit 1.62
**React surface:** React 18 · Vite 5 · Tailwind CSS 3 · lucide-react · FastAPI · Pydantic v2
