# Demo Video Script — Learning Pathfinder

**Target length:** 4:00 (brief allows 3–5 minutes)
**Format:** screen recording with voiceover
**Recommended surface:** Streamlit (`streamlit run streamlit_app.py`) — one
window, no split terminal. Use the React UI instead if you want the richer
visuals; the beats are identical.

---

## Before you record

**Reset to a clean state** so the demo starts from zero:

```bash
rm data/pathfinder.db          # Windows: del data\pathfinder.db
streamlit run streamlit_app.py
```

**Pre-flight checklist**

- [ ] `.env` has a working `GROQ_API_KEY`
- [ ] Generate one throwaway path first, then delete the DB again — this warms
      the connection so the recorded run is not the slow first call
- [ ] Wait ~1 minute before recording: the free tier is 8,000 tokens/minute and
      a rate-limit error mid-take will cost you the whole recording
- [ ] Browser at 100% zoom, 1920×1080, no bookmarks bar
- [ ] Close notifications

**The one risk to plan around:** path generation takes about 3 seconds and
assessment generation slightly longer. Don't fill the silence with "um" — either
narrate what the system is doing (see the script) or cut the dead air in editing.

---

## Scene 1 — The problem (0:00–0:30)

**Show:** the app's landing screen.

> "Course platforms have thousands of courses, and search ranks them fine. What
> they can't tell you is what to do *first*, and what after that.
>
> Relevance is symmetric — prerequisites aren't. And two people with the same
> goal need different starting points depending on what they already know.
>
> Learning Pathfinder closes that gap. Here's the whole thing end to end."

---

## Scene 2 — Conversational intake (0:30–1:05)

**Do:** type (or paste) into the text area:

> *"I'm a final-year CS student. I know basic Python and SQL and want to become
> a backend engineer. I can study about 10 hours a week and I learn best by
> building things."*

**Click** Continue.

> "You describe the goal in plain English — no forms, no dropdowns."

**When the parse appears, point at each field:**

> "It pulls out a structured profile: the goal, what I already know, my level,
> and my weekly capacity — and it shows me so I can correct anything before it
> builds anything.
>
> More importantly, it's already matched me to a target role — Backend Engineer —
> and worked out that I'm at 15% of the skills that role needs. Those amber tags
> are the gap. That's what the path is going to be built to close."

**Click** "Looks right — continue".

---

## Scene 3 — Generation and grounding (1:05–2:00)

**Click** "Generate my learning path".

**While it runs (~3s):**

> "This isn't the model writing a course list from memory. It ranks the local
> catalog with BM25, computes my skill gap, and the model only *selects and
> orders* from real courses — it returns IDs, not course names."

**When the path appears, scroll through it.**

> "Nine stages grouped into milestones, sequenced so prerequisites come first."

**Open one course expander — pick SQLAlchemy or FastAPI.**

> "And every single course explains itself. Not 'people like you took this' —
> this reason references *my* goal and *my* prior knowledge."

**Read the rationale aloud from the screen.** Then point at the URL.

> "That link is real. Because the model can only pick from the catalog, anything
> it invents gets dropped before it reaches me — no dead links, no courses that
> don't exist."

**Point at the "closes gap" tags and the project.**

> "It also tells me which skill gap this closes, and gives me a project to prove
> I can actually do it."

---

## Scene 4 — Progress and evidence (2:00–2:50)

**Tick the first one or two courses complete.**

> "As I finish courses, their skills get credited automatically."

**Switch to the Dashboard tab.**

> "And everything here is *derived*, not self-declared. Progress comes from what
> I actually completed. Watch the skill coverage — it jumped, because finishing
> those courses closed real gaps. Milestones, hours, and the estimated finish
> date all recompute from that one fact."

*(Read the two coverage figures off your own screen — don't quote numbers from
a different run.)*

**Switch to the Checkpoints tab.**

> "But ticking a box is weak evidence. So each stage ends in a checkpoint that
> only unlocks once you've finished the stage."

**Open the unlocked checkpoint. Answer the questions. Submit.**

> "These are application-level questions written from the courses I actually
> took — graded on the server, so the answer key never reaches the browser.
> Passing credits those skills as *demonstrated* rather than self-reported."

---

## Scene 5 — Adaptation (2:50–3:30)

**Go back to My Path. Open a course. Mark one "Too hard" and another "Not
relevant". Record both.**

> "The plan shouldn't be fixed at signup. If something isn't working, I say so."

**Open "Adapt this path" → Rebuild.**

> "Rebuilding re-runs the whole pipeline — but now with my completed courses in
> the 'already known' set and my feedback in the prompt."

**When v2 appears, compare against v1.**

> "Version two dropped both courses I flagged *and* the two I'd already
> finished, and pulled in FastAPI and API Design instead. An
> infrastructure-heavy path became an API-focused one, because I said so.
>
> And the old version is kept — you can see how the plan evolved."

---

## Scene 6 — The assistant, and closing (3:30–4:00)

**Switch to the Assistant tab. Ask:** *"Why is SQLAlchemy in my path?"*

> "The assistant is grounded in my actual roadmap — it knows what I've finished,
> what's next, and it quotes the same stored reason the card shows, so the two
> can never disagree."

**Let the answer render, then close on the dashboard.**

> "So: a goal in one sentence, a sequenced path of real courses that explains
> every step, evidence-based progress, and a plan that changes when you do.
>
> It's a Python and React app over FastAPI and SQLite, with a Streamlit build
> that deploys in one click. Thanks for watching."

---

## Timing summary

| Scene | Content | Runs | Ends |
|---|---|---|---|
| 1 | Problem framing | 0:30 | 0:30 |
| 2 | Conversational intake + skill gap | 0:35 | 1:05 |
| 3 | Generation, explainability, grounding | 0:55 | 2:00 |
| 4 | Progress + checkpoint assessment | 0:50 | 2:50 |
| 5 | Feedback → adaptation | 0:40 | 3:30 |
| 6 | Assistant + close | 0:30 | 4:00 |

---

## What to emphasise if you have to cut

Cut in this order — keep the top items, drop from the bottom:

1. **Grounding** (Scene 3) — the model can't invent courses. This is the
   architectural decision the whole project turns on.
2. **Explainability** (Scene 3) — a per-course reason written for this learner.
3. **Adaptation** (Scene 5) — the visible before/after is the most persuasive
   30 seconds in the demo.
4. **Derived progress** (Scene 4) — coverage moving on its own.
5. Checkpoint assessment.
6. Assistant.

## Things not to claim on camera

Say these accurately or leave them out — an evaluator who spots an overclaim
discounts everything else:

- The catalog is **61 curated courses**, not "thousands" and not crawled.
- There is **no authentication**; don't present it as multi-user.
- On Streamlit Community Cloud storage is **ephemeral** — don't say data
  "persists" without that qualifier. Locally, it does persist.
- Checkpoints are **multiple-choice**; they don't grade the projects.
