# Phase 0 results

Measured results from the Phase 0 spikes. This file supplements `TechDecisions.md` §10; copy decisions there when a spike is closed.

## Setup (6-7 Oct 2026)

| Item | Result |
|---|---|
| Git 2.55, Node 24.18, npm 11.16 | Installed |
| Python 3.12.10 | Installed from python.org (winget `Python.Python.3.12`) |
| uv 0.12.23 | Installed with pip into Python 3.12 (`...\Python312\Scripts\uv.exe`) |
| cloudflared, LiveKit CLI | **Not installed.** Downloads from github.com fail on this Wi-Fi. Retry on a hotspot; neither blocks Phase 1 |
| Keys: Deepgram, Groq, Gemini, Sarvam | Accepted by each provider (`scripts/check_keys.py`) |
| LiveKit URL, key, secret | Accepted (`scripts/check_livekit.py`) |
| Jev | Signup is paid. Not used |
| Groq models available | `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `whisper-large-v3`, `whisper-large-v3-turbo` |
| Gemini Flash models available | up to `gemini-3.8-flash`, `gemini-3.8-flash-lite`; free daily limit still to be read in AI Studio |

Environment notes for this laptop:
- Programs started from File Explorer do not see newly installed tools on PATH. Scripts add `%LOCALAPPDATA%\Programs\Python\Python312` and its `Scripts` folder to PATH themselves (see `run/go.cmd`).
- Set `UV_PYTHON_DOWNLOADS=never` so uv uses the installed Python instead of downloading one from GitHub.
- The user name contains a space: always quote paths.
- The laptop has an NVIDIA GPU, but the installed torch is the CPU build.

## T0-2 System One: Laya on this laptop (7 Oct, 00:36-00:45)

Scripts: `scripts/spikes/laya_speed.py`, `scripts/spikes/laya_variants.py`. Raw output: `run/reports/task-001-laya.cmd.txt`, `task-002-laya-variants.cmd.txt`.

**Install and load**
- `uv pip install laya` works: laya 0.3.28, torch 2.14.1+cpu, transformers 5.19.0.
- Usage confirmed: `agent = laya.load("convaiinnovations/laya-multilingual")`, `agent.predict(state_dict, questions)`.
- Result shape: `result["answers"][name]` has `choice` + `probabilities` + `confidence` + `answer_confidence` for a choice question, and `noul` (probability of yes) + `confidence` for a yes/no question. `result["usage"]` reports token counts.
- First load 142 s (includes about 650 MB download); later loads 16 s. Load once and keep the process alive.

**Speed (CPU, 8 threads)**

| Call | Time |
|---|---|
| One choice question, 3 options, short English state | about 175 ms |
| One choice question, 5 options, Hindi sentence | 170-340 ms |
| Choice with 7 options + one yes/no question | 320-650 ms, median about 500 ms |
| 30 triage decisions in sequence | 5.35 s, so 340 farms take about 61 s |

Time grows with the number of options and questions. The 150 ms local target (NFR-02) is missed on CPU.

**Accuracy**

| Decision | Input | Result |
|---|---|---|
| TRIAGE | English sentence report (intensity, distance, crop) | **6/6**, with sensible probabilities (severe 0.71-0.78 high; light 0.85-0.86 low) |
| TRIAGE | Raw field dictionary | 0 discrimination: every farm came out `medium` |
| ROUTE | Hindi reply, 7-way, English criteria | 11/24 |
| ROUTE | Hindi reply, 7-way, Hindi example criteria | 12/24 (14/24 without the agent question in the state) |
| ROUTE | Hindi reply, yes / no / other | 9/24 |
| ROUTE | Hindi reply, four yes/no questions | 3/24 |
| PERIL | Hindi cause, English criteria | 4/9 |
| PERIL | Hindi cause, Hindi keyword criteria | 5/9 |

**Conclusions**
1. Laya works well on **English, sentence-style states**. Use it as planned for TRIAGE and VERIFY, and write the state as a short English report, not a raw dictionary.
2. Laya zero-shot is **not usable on raw Hindi utterances** (ROUTE, PERIL): about half wrong whatever the question design. This matches the warning on its model card.
3. ROUTE and PERIL need one of these (tested in T0-2c below; option b was chosen):
   a. Give Laya an **English gloss** of the utterance (Sarvam STT has a translate mode; test accuracy on hand-translated versions of the same 24 cases first).
   b. A **small trained head**: sentence embeddings of the Hindi utterance plus logistic regression trained on about 30 labelled examples per intent. Still a fast non-generative decision model with probabilities.
   c. The LLM for ROUTE and PERIL only (Groq `openai/gpt-oss-20b` with JSON output), shown in the ticker as "LLM fallback".
4. Speed options: install the CUDA build of torch to use the laptop's NVIDIA GPU (about 2.5 GB download), or use the quantised ONNX build. For the fleet, triage village by village so calling starts before all 340 are ranked.

## T0-2c System One follow-up (7 Oct, 12:15-12:40)

Scripts: `scripts/spikes/intent_head.py` (+ `intent_data.py`), `scripts/spikes/laya_gloss.py`. Raw output: `run/reports/task-003-phase0-batch.cmd.txt`.

**A small trained head for Hindi replies** (sentence encoder + softmax regression trained on our own examples; 152 ROUTE and 56 PERIL training sentences, tested on sentences not used for training)

| Encoder | ROUTE (7 intents) | PERIL (5 perils) | Time per reply (CPU) | Mean top probability, right / wrong |
|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | **29/30** | **11/12** | **19 ms** | 0.70 / 0.33 (ROUTE) |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 28/30 | 11/12 | 21 ms | 0.87 / 0.69 (ROUTE) |

Training takes 0.3 s. The encoder is about 470 MB and loads once.

**Laya on English translations of the same replies**

| Checkpoint | ROUTE English (24) | PERIL English (9) | Time |
|---|---|---|---|
| `laya-multilingual` | 15/24 | 9/9 | 246 ms / 174 ms |
| `laya-typed-decisions` | 18/24 | 9/9 | 677 ms / 486 ms |
| `laya` (English base) | 15/24 | 9/9 | 652 ms / 462 ms |

**Decision (System One design)**

| Decision | Provider | Why |
|---|---|---|
| ROUTE (every farmer reply) | **`head`**: e5-small encoder + our trained softmax head, on the Hindi text | 29/30 at 19 ms; no translation step; gives probabilities |
| PERIL (cause of loss) | **`head`**, same encoder, second head | 11/12 at 18 ms on Hindi. Laya gets 9/9 but only on English, which would need a translation step |
| TRIAGE (rank farms) | **`laya`** (`laya-multilingual`), state written as a short English report | 6/6, about 175 ms |
| VERIFY (evidence consistency) | **`laya`**, state written as a short English report | Same kind of input as TRIAGE; to be measured in Phase 1 |

- Both are small non-generative decision models that return probabilities. The dashboard names the one that answered (`head` or `laya`); neither is called Jev.
- The e5-small head separates right from wrong answers better (0.70 vs 0.33) than MiniLM (0.87 vs 0.69), so use e5-small.
- The head's probabilities are soft. The fast-path threshold of 0.80 in `SystemDesign.md` §10.3 is too high for it: set thresholds from data in Phase 1 (fit a temperature on a held-out set, then pick the threshold that gives no wrong fast-path turn on the test set).
- The training sentences were drafted by Claude. A Hindi speaker must review and extend them (target 40+ per intent, including local dialect and mixed Hindi-English).
- The one ROUTE miss was an unrelated sentence classed as `gives_details` with probability 0.33: low-probability answers must go to the LLM path, which is what the rule table already does.

## T0-3 Browser agent (7 Oct, 12:40-12:50)

Script: `scripts/spikes/browser_form.py`. Raw log: `run/reports/task-003-browser-full.log`.

**What works**
- `browser-use` 0.13.11 installs with `uv pip install browser-use` into its own environment (`.venv-browser`), Python 3.12.
- It drives the **installed Google Chrome** (`Browser(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")`) with its own profile. No Playwright or Chromium download was needed. It downloads three small browser extensions on first start.
- Confirmed calls: `Agent(task=..., llm=..., browser=browser, use_vision=False, max_actions_per_step=10, flash_mode=True, max_failures=3)`, `history = await agent.run(max_steps=15)`, `history.final_result()`, `history.number_of_steps()`, `history.errors()`. LLM wrappers: `ChatGoogle(model=...)` reads `GOOGLE_API_KEY` (not `GEMINI_API_KEY`); `ChatGroq(model=...)` reads `GROQ_API_KEY`.
- The agent typed into text, tel, date (`2026-03-12`) and number fields, chose from a select, clicked Submit and read the reference number.

**Results on the five-field test form** (the local server checked every submitted value)

| LLM (free tier) | Correct submissions | LLM steps | Seconds per run | Notes |
|---|---|---|---|---|
| Groq `openai/gpt-oss-120b` | **3/3** | 3 (all five fields and Submit in **one** step, then "done") | 43, 83, 84 | No rate-limit error seen |
| Gemini `gemini-3.8-flash` | 1/3 | 4-5 | 86-170 | Frequent `503 high demand` errors on the free tier |
| Gemini `gemini-3.8-flash-lite` | 0 | - | - | Not a valid model name for this API (404) |
| Gemini `gemini-2.5-flash` | 0 | - | - | Withdrawn for new users (404) |

**Decision:** `BROWSER_LLM_CHAIN=groq:openai/gpt-oss-120b,gemini:gemini-3.8-flash`.

**Open points for Phase 3**
- Run time (43-84 s for one page) is longer than the three LLM calls explain. Measure where it goes (browser start and stop, extension downloads, silent retries, Groq's 8,000 tokens-per-minute limit) before the three-page form is built. Keeping one browser open between runs should remove the start-up cost.
- The real form has three pages: expect about 6-8 LLM calls. Groq limits are per model, so `openai/gpt-oss-20b` can be a second link if the 120b model is throttled.
- Only headless mode was tested. The demo needs a visible window (`headless=False`, fixed size and position).

## GPU (7 Oct, 12:50)

- The laptop has an **NVIDIA GeForce RTX 3050 Laptop GPU, 4 GB**, driver 591.84.
- Installing the CUDA build of torch (`--index-url https://download.pytorch.org/whl/cu130`, about 2.5 GB) **failed with a connection reset** on this network. Script: `scripts/spikes/gpu_setup.py` (it creates `.venv-gpu`; safe to re-run).
- Not needed for the plan: the head is 19 ms on CPU and Laya triage is 175 ms on CPU. A GPU would only shorten fleet ranking (61 s for 340 farms). Retry on a stable connection if time allows; otherwise rank village by village.

## Still to run

| Spike | Needs |
|---|---|
| T0-1 Hindi voice loop | A person speaking into the microphone |
| T0-4 Photo classifier on the phone | A tunnel (cloudflared or a substitute), the phone, sample photos |
| GPU build of torch (optional) | A stable connection for a 2.5 GB download |
