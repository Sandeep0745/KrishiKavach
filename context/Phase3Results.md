# Phase 3 results

Built and measured on 7 Oct 2026 (evening). Everything below was run on the team laptop unless it says otherwise. Raw output: `run/reports/task-014` to `task-018`.

## What exists now

| Item | State |
|---|---|
| 3.1 Pipeline graph, four agents, `agent.*` events | Built. Runs on LangGraph 1.2.14 on the laptop; the same graph also runs on a built-in runner where LangGraph is missing |
| 3.2 Evidence agent | Built: weather at the spot through the weather MCP server, distance from the plot, the photo's hash, an illustrative loss value from the mandi price |
| 3.3 Eligibility agent | Built: nine rule checks, then VERIFY as a second opinion |
| 3.4 Filer, browser-agent mode | Built: browser-use 0.13.11 on Groq `openai/gpt-oss-120b`, one small agent per page |
| 3.5 Filer, scripted mode and automatic fall-through, `filing.step` | Built |
| 3.6 Follow-up agent | Built: reference, time to file, message card to the phone |
| 3.7 `pipeline/run`; the call ends with the reference | Built; proved as text, not yet by voice |
| 3.8 Dashboard: agents, tool calls, filing progress | Built |
| 3.9 Reviewer approval (P1) | Built: key A on the dashboard |
| 3.10 Mandi estimate and evidence pack page (P1) | Built. The browser mirror is not built (the real window is on screen) |

## Gate G3, test by test

| ID | Result |
|---|---|
| T3-01 Evidence pack | Pass (automated) |
| T3-02 Eligibility personas E1 to E8 | Pass (automated) |
| T3-03 Deadline rule | Pass (automated) |
| T3-04 Browser agent | **Pass on the numbers: 5 of 5 correct**, plus 1 of 1 inside the pipeline (41 s for the whole pipeline). Median 32 s, slowest 32 s (limit 75 s); 3 LLM calls each (limit 12). Measured on 8 Oct, 00:02-00:12, in the final setting. Run with no window; a person has not yet watched the visible window do it |
| T3-05 Scripted fill | Pass: 5 of 5 in the tests, 0.7 s each on the laptop (limit 15 s), every field equal |
| T3-06 Automatic fallback | Pass on the mechanics: with a 5-second limit the agent is cut off, the scripted fill finishes the same form in the same window (11 s), `fallback.used` is emitted. The dashboard line was checked in the headless browser test, not by eye on the laptop |
| T3-07 Portal failure | Pass (automated): `FAILED` with a reason, orchestrator alive, a second run files it |
| T3-08 Full hero flow by voice and phone | **Not run.** Its text version passes: the call logic, the pipeline, the Filer (scripted) and the phone's message card together; the agent reads out the reference the portal gave |
| T3-09 Slow filing | Only the logic is tested: a run longer than the wait answers `pending` and still finishes; the agent then says the slow line. Not run by voice |
| T3-10 MCP used by two clients | Pass: `intake` and `pipeline` |
| T3-11 Pipeline events in order | Pass (automated) |
| T3-12 Reviewer approval | Pass (automated, and in the dashboard browser test) |

**The gate is not passed yet**: T3-08 and T3-09 need a person, and T3-04/T3-06 should be watched once in the visible window (`setup\9-watch-filing.cmd`).

Automated suite: 88 tests. On the laptop 85 pass and 3 are skipped (the three dashboard and farmer-page browser tests need Playwright in `.venv`; they pass in Claude's workspace). Voice text check: 27 of 27.

## Measurements

### Browser agent: where the time went

| Design | LLM calls | Tokens | Time | Result |
|---|---|---|---|---|
| One agent for the whole form (first build) | 7 | not measured | 182 s (three runs cut off at 75 s) | Correct when given the time |
| One small agent per page, pages 1 and 3 on Groq and page 2 on Gemini (an intermediate version) | 3 to 4 | not measured | 28 to 62 s, median 31 s | 6 of 6 correct; the 62 s run was Gemini failing and Groq taking over |
| **One small agent per page, every page on Groq `openai/gpt-oss-120b` (final)** | 3 | about 8,400 | 30 to 32 s | 7 of 7 correct (one alone, one inside the pipeline, five in a row a minute apart) |

A single request to Groq answers in about 4 seconds. The first design was slow because the free tier allows 8,000 tokens a minute for this model: after two requests it had to wait. Smaller requests, fewer of them and no closing "done" request fixed it. One filing still uses about a minute's allowance, so **two agent filings need about a minute between them**; a second one straight after will be slow and may fall back to the scripted fill.

Models tried on the form (all free tier): Groq `openai/gpt-oss-120b` correct; Groq `qwen/qwen3.8-27b` could not upload the photo; Groq `openai/gpt-oss-20b` cannot produce the action format; Gemini `gemini-3.8-flash` answered 503 "high demand" (as in Phase 0).

### VERIFY (Laya): the wording matters more than the model

The first pipeline run on the laptop sent the hero's own, fully consistent case to review: Laya said "inconsistent" with 90 % confidence. `scripts/spikes/verify_wording.py` measured six wordings on the 15 evaluation examples, on 120 consistent cases with realistic figures, and on 12 grey cases (a weakly "healthy" photo).

| Wording of the report | Evaluation set | Consistent cases passed | Hero | Grey cases caught |
|---|---|---|---|---|
| Phase 1 wording, exact figures | 12 of 15 | 26 of 120 | 0 of 3 | 12 of 12 |
| Figures rounded | 12 of 15 | 50 of 120 | 3 of 3 | 12 of 12 |
| Plain words, rounded rain figure | 8 of 15 | 120 of 120 | 3 of 3 | 0 of 12 |
| **No figures (chosen)** | 10 of 15 in the experiment, 9 of 15 with `eval_s1.py` | **120 of 120** | 3 of 3 | 0 of 12 |
| No figures, question turned round ("does anything contradict?") | 13 of 15 | 74 of 120 | 3 of 3 | 12 of 12 |

What this means, plainly:
- No wording is both safe for true cases and good at catching false ones. The chosen one never blocked a consistent case, which is what a second opinion must not do.
- With it the model catches only 2 or 3 of the 8 inconsistent evaluation cases by itself. **The rules catch all 8** (a healthy photo, no hail on record, a photo far from the plot, not a crop). So in this build the rules decide and VERIFY is a recorded second opinion that rarely changes the outcome. Say that if asked; do not present VERIFY as the thing that detects fraud.
- VERIFY takes about 200 ms on the laptop.

### Other numbers

| What | Measured |
|---|---|
| Pipeline for the hero, scripted filing | about 2 s (evidence 0.8 s, eligibility 0.25 s, filing 0.8 s) |
| Pipeline for the hero, browser agent | 44 s |
| Scripted fill, 27 steps, no pauses | 0.7 s (the demo adds a 250 ms pause per field: about 8 s) |
| Voice call as text, LLM path | median 659 ms, slowest 1.1 s |
| Local service call on Windows by the name `localhost` | 2.06 s each, every time; 20 to 50 ms after switching to `127.0.0.1` |

## Found and fixed on the way

- **First spoken test (Phase 2 follow-up).** (1) LiveKit plugins imported inside the call crashed it ("Plugins must be registered on the main thread"). (2) A remark made while waiting for the photo ("हां बोलो") arrived as the photo timer ran out and was taken as consent to a question not yet asked: the call's changes are now made one at a time, and the read-back cannot be interrupted. (3) Replies started on half-heard sentences and were redone: early replies are off. (4) The microphone test never ended: it now stops when the call ends. (5) Every reply was 2 seconds late because of `localhost`. After these, the whole spoken call worked on the laptop with speakers.
- A farmer who says "around three" for a storm at 15:30 was sent to review, because the weather was looked up at exactly 15:00. The Evidence agent now looks up the recorded storm time when the stated time is within the 180 minutes rule 7b allows.
- A blank `BROWSER_LLM_CHAIN=` line in the laptop's `.env` switched the agent off. A blank value now means the default.
- The model was given the photo's Windows path with backslashes; it now gets forward slashes, which it can repeat exactly.

A correction to the first version of this page: the "5 of 5" first reported on 7 Oct was measured with the intermediate version in the table above, because the final `agent_mode.py` had not reached the laptop when that run started (the file was sent in the same step as the edit that produced it). All files on the laptop were compared with the source afterwards and the measurement was repeated in the final setting.

## Still open

- T3-08 by voice with a phone, T3-09 by voice, and one look at the visible window.
- The photo used in every automated run is a stand-in file, not a real crop photo; the on-phone photo check has still not been tried on real photos (Phase 2, T2-10 to T2-12).
- Gemini as the agent's fallback model is configured but answered 503 whenever it was tried; the scripted fill is the fallback that works.
- The laptop's `.env` still has `FILING_MODE=scripted` from the template. `setup\7-start-everything.cmd` sets `auto` for its own run; for any other way of starting, set `FILING_MODE=auto` in `.env` for the demo.
- The covered-peril list (rule 3) still needs checking against the official guidelines (research item R2).
