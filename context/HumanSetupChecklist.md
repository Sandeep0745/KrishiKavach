# Human setup checklist

Things only a person can do. Claude cannot create accounts, hold a phone or speak into a microphone. Do section 1 tonight; it unblocks Phase 0.

## 1. Tonight (about 60–90 minutes)

### Accounts and keys

**Rule: everything here is free. Do not enter a card, UPI mandate or any payment detail on any of these sites.** If a signup insists on one, stop, skip that service and note it; the plan has a fallback for each. With no payment method attached, an account cannot be charged.

| # | Service | What to do | What you get free | Goes into `.env` as | Needed for |
|---|---|---|---|---|---|
| 1 | **LiveKit Cloud** | Sign up, create a project, copy URL, API key, API secret | 1,000 agent minutes a month, plus a small monthly inference credit | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Voice calls |
| 2 | **Deepgram** | Sign up, create an API key | $200 signup credit | `DEEPGRAM_API_KEY` | Indian-English speech-to-text |
| 3 | **Sarvam AI** | Sign up, create an API key | ₹100 signup credit | `SARVAM_API_KEY` | Indian-English voice (cache build and live replies) |
| 4 | **Groq** | Sign up, create an API key | Free tier with daily limits | `GROQ_API_KEY` | Conversation LLM, backup speech-to-text |
| 5 | **Google AI Studio** | Sign in, create a Gemini API key, and note the free limits it shows for the Flash models | Free tier with daily limits | `GEMINI_API_KEY` | Browser agent LLM, backup conversation LLM |
| 6 | **TypeSafe (Jev)** — try, do not pay | Go to `console.typesafe.ai` and try to sign up. If you get a key and free credit **without** entering a payment method, keep it. If it asks for a card or puts you on a waitlist, close it | Reported $5 credit; unconfirmed | `JEV_API_KEY` | Optional: lets us use the model named in the problem statement |
| 7 | data.gov.in (optional) | Register for an API key | Free | `DATA_GOV_API_KEY` | Live mandi prices (P1) |

Each team member can do this with their own account, which gives each person their own keys for testing. Do not create extra accounts to get around a limit.

Write down what happened with Jev. If there is no free key, the build uses the open Laya model on the laptop, which is the default plan anyway.

### Installs on the Windows laptop

| # | Tool | Check |
|---|---|---|
| 1 | Git | `git --version` |
| 2 | uv (Python manager) and Python 3.12 | `uv --version`, `uv python install 3.12` |
| 3 | Node.js 20 or newer | `node --version` |
| 4 | Google Chrome | — |
| 5 | cloudflared | `cloudflared --version` |
| 6 | LiveKit CLI (`lk`) | `lk --version` |
| 7 | Claude Code (you already have it) | — |

Items 1–6 are free downloads. Piper (the local English voice) and the Laya model are downloaded by the project scripts.

Free disk space: about 5 GB (browser binaries, the local Laya model, node modules).

### Hardware

- An Android phone with Chrome (the farmer's phone). Check that camera and microphone permissions work in Chrome.
- A second phone that can act as a hotspot.
- A way for the room to hear the call: a small speaker, or the phone on speaker next to a microphone.
- A printed A4 colour photo of a hail-damaged wheat field (or a tablet showing it) for the farmer to photograph on stage.

## 2. Day 1 morning (during Phase 0)

### Sample photos for the edge model

Collect 6–10 photos for each label into `data/eval/edge/<label>/`: `hail_damage`, `waterlogged`, `lodged`, `healthy`, `not_a_crop`.

- Use photos you took yourselves or ones with a licence that allows reuse. Note the source of each in `data/eval/edge/SOURCES.md`.
- Prefer wheat. Include a few hard ones (dusk light, far away, partial damage).
- If Phase 0 shows the model is weak (below 80 %), raise this to about 30 per label for the linear probe.

### English review

Someone on the team:

1. Reads every scripted line in `SystemDesign.md` §10.2 aloud and fixes anything that sounds stiff or bookish. Keep the English plain and the sentences short.
2. Writes or checks the English examples in `data/eval/s1_eval.jsonl` and `route_train.jsonl` (at least 40 for ROUTE), using the phrasing farmers would really use. Claude can draft them; a person must correct them.
3. Does the voice tests in `Testing.md`.

### Decide roles

| Role | Person |
|---|---|
| Track A · Voice (and the farmer on stage) | |
| Track B · Backend | |
| Track C · Web | |
| Presenter | |
| Research items R1–R4 and slides | |

## 3. During the build

- **Research items R1–R4** in `ProblemStudy.md` §3. R1 (a figure or documented case for missed 72-hour intimations) matters most for the first slide.
- Each evening run `python scripts/usage.py` and look at each provider's console. Speech credit is the scarce one: keep `CREDIT_SAVER=1` while building and save real-voice runs for tests and rehearsals.
- After each gate: commit, and fill in the results log in `Testing.md`.
- Day 2 evening: check the venue's rules, the time slot length and the projector resolution. If the slot is under four minutes, use the three-minute flow in `DemoScript.md` §5.

### Checks that need a person now (after Phase 2)

Do them in this order. Each one is a double-click plus talking; tell Claude what happened in a sentence or two.

| # | What to do | What you should see | Tests |
|---|---|---|---|
| 1 | **Voice only. Done on 7 Oct (worked with speakers after five fixes, `Phase3Results.md`).** Double-click `setup\6-voice-console.cmd`, wear a headset, and answer the questions with the eight lines the window shows (they are the script of `Testing.md` §9.2) | The assistant greets Ramlal ji, asks about damage, plot, cause, time, extent and crop stage, asks for a photo, waits 15 seconds, reads everything back, and after "हाँ, कर दीजिए" says the form is being filled and ends. Tell Claude: how the voice sounds, whether it understood each answer, whether any question was repeated, and roughly how long it takes to answer | T1-12, T0-1, T2-02, T2-03 |
| 2 | **Whole call on the laptop.** Double-click `setup\7-start-everything.cmd`. On the farmer page press the big button and allow microphone and camera. On the dashboard press "Call hero" | The farmer page rings within 2 seconds; after you answer, the dashboard's live-call panel shows the transcript, `fast path` or `language model` on each turn, and the checklist ticking. When asked for the photo, press "फोटो लें", point the webcam at a printed crop photo, press the shutter, then "भेजें": the evidence card appears on the dashboard and the assistant reads the details back | T2-01, T2-02, T2-03, T2-10, T1-10, T1-11 |
| 3 | **Other endings**, each on a new call (press Reset twice on the dashboard between calls): say "मुझे किसी आदमी से बात करनी है"; answer the damage question with "नहीं, फसल ठीक है"; answer the greeting with "नहीं, गलत नंबर है"; say "नहीं" at the final question; talk over the assistant while it speaks | Escalation line and `Needs a person`; no-damage line; wrong-number line; nothing filed; the assistant stops talking within about half a second | T2-05 to T2-08, T2-13 |
| 4 | **On a real phone.** With step 2 running, double-click `setup\8-phone-link.cmd`, and open the printed `https://…` address followed by `/farmer` on the phone | Same as step 2, with the phone ringing and the phone's camera | T2-01, T2-10 on the phone |
| 5 | **Photo check on the phone.** Take 6 to 10 photos per label (hail damage, flattened crop, flooded field, healthy crop, something that is not a crop), name them `hail_damage_01.jpg` and so on, and open `https://…/static/edge-test.html` on the phone | The page shows how many were recognised and the time per photo. Then switch on airplane mode and run the speed test: it must still work | T0-4, T2-11, T2-12 |
| 6 | Someone reads `apps/voice/lines.py` aloud (the lines and the twelve village names) and fixes anything unnatural. If a line changes, tell Claude so the audio cache is rebuilt | Lines sound natural when spoken | English review |

### Checks that need a person after Phase 3

| # | What to do | What you should see | Tests |
|---|---|---|---|
| 7 | **Watch the form being filed.** Double-click `setup\9-watch-filing.cmd` and watch the browser window that opens on the right | The "FasalClaim Sandbox" form is filled page by page and submitted four times: twice by the browser agent (each page fills in one burst, about 30 seconds in all), once by the scripted fill (field by field), and once where the agent is cut off after 5 seconds and the scripted fill takes over. The black window ends with `FILING CHECK PASSED` | T3-04, T3-05, T3-06 |
| 8 | **The whole story.** Double-click `setup\7-start-everything.cmd` and do the call of step 2 (laptop) or step 4 (phone), taking the photo and saying "हाँ, कर दीजिए" at the end | The dashboard's Filing box shows the checks passing and then each step of the form; the browser window fills the form; the assistant reads out a reference number starting "एफ़, सी, एस"; a message card with the same number appears on the farmer page; the dashboard ends with "Filed in … Reference FCS-…", ideally under 3 min 30 s from the ring | T3-08 |
| 9 | **A person approves.** On a new call (Reset twice first), do not take a photo: wait until the assistant goes on without it and say yes | The assistant says the report could not be filed now; the dashboard shows "Sent to a person" and a new button "Approve as reviewer". Press it (or the A key): the report is filed and the message card arrives | T3-12 by eye |
| 10 | **Slow filing** (optional). Open a Command Prompt in the project folder, run `setup\7-start-everything.cmd slow` (it makes the Filer wait 100 seconds), then do the call of step 8 | The assistant says it is taking longer and ends the call; the message card arrives when filing completes | T3-09 |

### Checks that need a person after Phase 4

| # | What to do | What you should see | Tests |
|---|---|---|---|
| 11 | **The district alone.** Double-click `setup\7-start-everything.cmd`. On the dashboard press "Start storm" (S). Do not call the hero | 340 grey dots; the storm circle sweeps in; dots turn red, then amber, blue and green; "Ranking farmers: n of 340" counts up; the ticker and the tool-call list stream; after about 75 seconds the counters stop at 311 filed, 11 not reachable, 9 no damage, 5 need a person, 3 not eligible, and one farm (the hero's, labelled LIVE) is still red. The status line says the live case is still open | T4-08, T4-09, T4-10 |
| 12 | **Pause.** Reset (R twice), Start (S), and after about 20 seconds press P; wait; press P again | Everything stops, including the clock; nothing changes while paused; it carries on after the second P | T4-07 |
| 13 | **The full demo**, as in `DemoScript.md`: Reset, S, then H after about 15 seconds, do the whole hero call with the photo, and when the reference has been read out press P | The fleet freezes during the call ("Simulated farmers paused for the live call"), the hero is filed in the browser window, and after P the banner ends on "312 of 340 claims filed. 68 hours left. 16 need follow-up." | T4-12 |
| 14 | **Numbers for the slides.** After step 13, open a Command Prompt in the project folder and run `.venv\Scripts\python.exe scripts\report.py` | Voice response times, decision times, filing time, ring-to-reference time and the closing line, all measured from that run | T5-07 |
| 15 | **Projector.** Put the dashboard in full screen (F11) at 1920 × 1080 and at 1366 × 768 | Nothing clipped, nothing scrolls, readable from the back of the room | T4-13 |

Leave about a minute between two calls that end in filing: the free tier's token allowance for the browser agent refills by the minute. If a second filing follows straight away it will be slow or use the scripted fill, and the dashboard will say so.

### Checks that need a person for Gate G5 (Phase 5)

The machine has already rehearsed what it can: `scripts/demo_check.py` runs the whole demo five times without the phone, and `scripts/drills.py` runs drills D1, D2, D4, D6 and D7 (results in `Phase5Results.md`). These are the parts only people can do. Do 16 first; the rest in any order.

| # | What to do | What you should see | Tests |
|---|---|---|---|
| 16 | **Cold start.** Restart the laptop. With a timer running, follow only "Run it, each time" in the root `README.md` (start everything, phone link, readiness check) | Ready, with every "On-stage readiness" line OK, in under 10 minutes | T5-03 |
| 17 | **Five in a row, with the phone.** Run `DemoScript.md` §3 from the top five times, pressing Reset twice between runs and leaving about a minute between runs. Any manual fix (a restart, a second press of H, a retyped answer) sets the count back to zero. In one of the runs, after taking the photo press "दोबारा लें" and take it again: the camera must open again (the machine could not check this; `Phase5Results.md`) | Every run ends on "312 of 340 claims filed. 68 hours left. 16 need follow-up." with the hero filed and the reference read out | T5-01 |
| 18 | **Numbers for the slides.** Straight after the fifth run: `.venv\Scripts\python.exe scripts\report.py`. Copy its lines into `Testing.md` "Measured numbers" and into the slides | Voice response times (fast path and language model), decision times, filing time, ring-to-reference time, the closing line | T5-07, roadmap 5.5 |
| 19 | **Hotspot only.** Laptop and phone both on the spare phone's mobile hotspot, nothing else. One full run, then `report.py` | One clean run; note the ring-to-reference time next to the Wi-Fi one | T5-02 |
| 20 | **The drills a machine cannot do.** D3: in `.env` change one letter of `DEEPGRAM_API_KEY`, start everything: the voice window shows a clear error and `smoke.py` shows Deepgram red; put the letter back. D5: during a call switch the phone's Wi-Fi off: the dashboard shows the call `dropped`; switch it on and press H: the agent continues with what it already had. D8: switch the laptop's Wi-Fi off: `smoke.py` is red; practise switching to the backup video. D9: with `CREDIT_SAVER=1` in `.env` the call still completes; the read-back and the reference are spoken in the local voice | Each behaves as described in `Testing.md` §8 | T5-04 |
| 21 | **Backup video.** Record one clean run: Windows Snipping Tool, Record, the whole screen, with the microphone on so it picks up both sides of the call from the phone's speaker. Keep it under 3 minutes (the three-minute version in `DemoScript.md` §5, or trim the waiting). Play it back on the demo laptop with sound | A complete clean run that plays | T5-05 |
| 22 | **Timed rehearsal.** Slides plus live demo, three times, with a timer | Inside the allotted time each time | T5-06 |
| 23 | **Honesty and language.** Read every slide and every dashboard label against `ArchitectureDesign.md` §7. Farmer-facing text and speech and the dashboard are English | Nothing claims more than was measured or built; simulated is always called simulated | T5-08 |
| 24 | **Zero spend.** Open the billing or usage page of LiveKit Cloud, Deepgram, Sarvam, Groq and Google AI Studio, and run `.venv\Scripts\python.exe scripts\usage.py` | Nothing charged, no payment method on any account, enough left on each for at least 10 more full runs | T5-10 |

Decide before step 17: **which voice reads out the details and the reference number.** With `CREDIT_SAVER=1` (the laptop's setting now) the fixed lines play in the Sarvam voice from the audio cache, but the sentences that change every call (the read-back and the reference number) are spoken by the local Piper voice, so the voice changes at the most important moment. With `CREDIT_SAVER=0` Sarvam speaks those too, at a few hundred characters of the free credit per call (`usage.py` shows how much is left), with Piper as the fallback. `TechDecisions.md` planned `CREDIT_SAVER=0` for rehearsals and the demo. Whichever you choose, use the same in all five runs and on stage.

## 4. Day 4

- Record the backup video: screen capture of the dashboard and browser, the phone visible in a corner or filmed separately, with clear audio of both sides of the call.
- Test in the real room if possible: network, audio, projector.
- Print the damaged-crop photo twice.
- Charge everything. Bring the laptop charger and a phone cable.

## 5. Things not to do

- Do not put real names, real phone numbers or real policy numbers into the seed data.
- Do not point the browser agent at any real government or insurer website.
- Do not paste API keys into chat, code or slides.
- Do not add a payment method to any account, and do not accept a "start free trial" that asks for one.
- Do not add features on Day 4.
