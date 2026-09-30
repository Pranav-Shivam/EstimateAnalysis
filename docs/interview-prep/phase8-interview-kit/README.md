# Phase 8: Interview Kit

This kit lets me retell this project as my own story in an applied AI engineering interview, out loud, without reading from the repo. Each file is written in first person, in short spoken sentences. Every technical claim was checked against the code, an ADR, a phase doc, the git log, or a command I ran. Where I could not check something, it is marked as a gap.

The per-phase docs (`../phase1-interview.md` to `../phase7-interview.md`) are the deep reference. This kit is the layer on top: how to frame the project, how to tell it, and where it is weak.

## Files

| File | What it is for |
|---|---|
| [01-pitch-and-framing.md](01-pitch-and-framing.md) | The 90-second and 5-minute pitch, the four-step framing script, and the boundary rule |
| [02-system-design-walkthrough.md](02-system-design-walkthrough.md) | The pipeline as a worked LLM system-design answer, a data-flow diagram, and a reusable one-page template |
| [03-star-stories.md](03-star-stories.md) | Six real stories from this repo, each with what I would do differently |
| [04-honest-limits-and-hard-questions.md](04-honest-limits-and-hard-questions.md) | Limits I state up front, and the 12 hardest questions with spoken answers |
| [05-demo-path.md](05-demo-path.md) | A 5-minute click path through the running app, with real screenshots |
| [06-gaps-and-next-builds.md](06-gaps-and-next-builds.md) | Capability areas marked Shown, Partly, or Not shown, and the smallest build to close each gap |

## How to use it

1. Read the framing in file 01 until I can say it without notes. It is the first thing an interviewer hears.
2. Use file 02 as the spine of any "design an LLM system" question. The template at the end works for other problems too.
3. Rehearse file 03 out loud. Each story should take about two minutes.
4. Read file 04 last, and say the limits before an interviewer finds them. Volunteering a limit reads as senior. Being caught on one does not.
5. Rehearse file 05 with the app open at least twice. Then the demo needs no script.
6. Skim file 06 for honest answers to "what is not covered here".

## Suggested 3-day study order

**Day 1: the story and the design (about 2 hours)**
- File 01, then say both pitches aloud three times each.
- File 02, then draw the data-flow diagram from memory on paper.
- Skim `../phase3-interview.md` and `../phase4-interview.md` for the guardrail and graph details.

**Day 2: the evidence and the stories (about 2 hours)**
- File 03. Tell each story aloud, timing it.
- `../phase5-interview.md`, especially the calibration addendum. The judge is the part interviewers probe most.
- `../phase6-interview.md` for the correction loop and what the tests hid.

**Day 3: the hard part (about 2 hours)**
- File 04, Part A then Part B. Answer each question aloud before reading my answer.
- File 05 with the app running. Do the full click path twice.
- File 06, and pick which one gap I would say I am closing next.

## Source facts and how they were checked

- Backend tests: 747 collected. On the dev database that already holds the seeded demo, 745 pass and 2 fail (`test_phase2_acceptance` and `test_phase7_acceptance`, which count absolute rows). Both are documented in `docs/new-machine-setup.md`. Run on 2026-09-30.
- Frontend tests: 81 pass (Vitest). Run on 2026-09-30.
- Live run: `backend/scripts/run_live_estimates.py` ran the real GPT-4o intake over all 60 emails and the real agent over 40, once, on 2026-09-30, for $1.04 by its own meter. Results are in `backend/data/live_run_report.json`. Dollar figures use third-party prices (`docs/research/openai-pricing-for-live-run.md`).
- Screenshots in `images/` were taken from the running app on 2026-09-30 with headless Chrome against the seeded demo data.
- Calibration numbers come from `backend/data/judge_calibration.json` and `../phase5-interview.md`.
