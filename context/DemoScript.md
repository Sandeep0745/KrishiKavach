# Demo script

The stage demo, beat by beat. Total about 4 min 45 s in the full version; a 3-minute version is in §5. Rehearse with a timer.

**Roles:** *Presenter* at the laptop (talks, presses keys). *Farmer* holds the phone and plays Ramlal (speaks English, using the script in `Testing.md` §9.2). A third person, if available, watches the logs and is ready to switch a fallback.

## 1. One change from the first outline

The first outline had the farmer take the photo with the phone in airplane mode during the call. Airplane mode would drop the call. So in the main flow the phone stays online, and the screen shows that the photo was classified **on the phone** (label, milliseconds, "no internet needed for this step"). The airplane-mode proof is a separate 20-second beat after the main flow (§4), or in answer to a judge's question.

## 2. Before going on stage

| When | Check |
|---|---|
| 30 min before | Laptop on power. Phone charged, on the same hotspot, volume up, "do not disturb" on, screen timeout off |
| | `setup\7-start-everything.cmd` running; `.venv\Scripts\python.exe scripts\smoke.py` shows every line under "On-stage readiness" OK |
| | Tunnel running; phone has the farmer app open on the idle screen showing "मॉडल तैयार" (model loaded) |
| | The Filer's Chrome window ("FasalClaim Sandbox") open and placed beside the dashboard |
| | Dashboard in full screen on the projector; zoom checked from the back of the room |
| | One full run done in the last 30 minutes, then **reset** |
| | The damaged-crop photo target is ready (a printed A4 photo, or a second screen) for the farmer to photograph |
| | Backup video open in a paused player on a second desktop |
| 2 min before | Reset once more. Clock shows 72:00:00. Phone on idle screen. Laptop audio routed to the room speakers so the audience hears the agent |

**Audio:** the audience must hear both sides. Simplest: the phone on speaker held near a microphone. Test this in the room.

## 3. Main flow

| # | Time | Presenter does / says | On screen | If it goes wrong |
|---|---|---|---|---|
| 1 | 0:00 | "After a hailstorm, a farmer has 72 hours to tell the insurer, or the claim is not assessed. Today the system waits for the farmer. Ours goes to the farmer." | Dashboard: district map, 340 grey dots, clock at 72:00:00 | — |
| 2 | 0:15 | Presses **[S]**. "It is 3:30 in the afternoon in Sehore. Hail." | Storm footprint sweeps across; "Sentinel" glows; MCP log shows `weather.list_storm_events`; affected dots turn red; the countdown starts | If nothing happens in 3 s, press [S] again; then reset and restart |
| 3 | 0:25 | "340 insured farmers are in its path. A small System One model ranks who to call first: each distinct situation in about 180 milliseconds, and farms in the same situation share the answer." | "Dispatcher" glows; the decision ticker fills with TRIAGE rows and their latencies; first dots turn amber as calls go out | If the ticker shows a fallback marker, name the provider that answered and continue |
| 4 | 0:40 | "Calls are going out in parallel. These farmers are simulated. This one is real." Presses **[H]**. | Fleet freezes ("Simulated farmers paused for the live call"); the live-call panel opens; stopwatch starts | — |
| 5 | 0:45 | (silent) | **The phone rings.** Farmer shows it to the audience and accepts | If no ring in 5 s: press [H] again. If still nothing: farmer taps "call now" on the app |
| 6 | 0:50 | (lets the call play) | Agent greets Ramlal by name in English, says it is an automated assistant, names today's hail in his village, asks about damage. Transcript scrolls | If the agent does not speak in 5 s: farmer says "Hello?" |
| 7 | 1:00–1:50 | Quietly, over the call: "Watch the right-hand column: simple yes and no answers never touch the big model." | Farmer answers per `Testing.md` §9.2. Each turn row shows `fast` or `llm` and milliseconds. Slot checklist ticks. ROUTE and PERIL rows appear in the ticker | If the agent misunderstands, the farmer just repeats; do not restart |
| 8 | 1:50 | "Now the evidence." | Agent asks for a photo. Farmer presses "फोटो लें" and photographs the damaged-crop print. Phone shows "ओले से नुकसान · 0.8 · 41 ms · on the phone". Evidence card appears on the dashboard with GPS and time | If the label is wrong: farmer taps retake once. If wrong again: continue. Eligibility sends the case to human review; the presenter says "the photo and the statement disagree, so it stops for a person — I am the reviewer" and presses **[A]** to approve, and filing continues |
| 9 | 2:05 | (silent) | Agent reads the details back and asks consent. Farmer: "हाँ, कर दीजिए।" | — |
| 10 | 2:15 | "Five agents now work on this one claim." | Agent strip: Evidence → Eligibility → Filing. MCP log: `weather.get_weather_at`. The evidence card shows the weather record at the spot (hail) and how far from the insured plot the photo was taken. VERIFY row in the ticker | — |
| 11 | 2:25–3:15 | "And this is the part nobody does for the farmer today. No API. The agent uses the website, like a person would." | **The browser fills the three-page form by itself,** uploads the photo, ticks the declaration, submits. Confirmation page shows the reference | If it stalls, the scripted fallback takes over automatically and the label shows it. Say: "the agent timed out, so the deterministic fallback finished the job — the farmer still gets filed." |
| 12 | 3:15 | (silent) | Agent reads the reference number aloud. The message card arrives on the phone. Live-call panel: **"Filed in … Reference FCS-…"**. Hero dot turns green | If the call has already ended (slow filing), show the message card on the phone instead |
| 13 | 3:25 | "That was one farmer. Here is the district." Presses **[P]** to resume. | Overlay closes. Fleet resumes at speed: dots go amber, blue, green. Counters climb. Ticker streams | — |
| 14 | 4:30 | "312 of 340 filed, with 68 hours to spare. The other 28 are not hidden: unreachable, no damage, not covered, or handed to a person." | Final banner. Legend shows the five outcome counts | — |
| 15 | 4:40 | "Everything you saw decide, speak, see and click was running live. The other farmers' answers were simulated, and it says so on screen." | "Simulated farmers: 339. Live: 1." | — |

## 4. Optional beat: no network (20 s)

Use if there is time, or when a judge asks "what if there is no signal?"

1. Farmer turns on airplane mode and shows it.
2. On the idle screen, presses "फोटो लें" and photographs the print.
3. Phone shows the label and "saved on phone, will send when network returns".
4. Airplane mode off. Within a few seconds the dashboard's evidence card shows a second photo marked "captured offline".

## 5. Three-minute version

Set `HERO_FLOW=short` (the agent asks only: identity and damage, cause, extent, photo, consent; time, field and crop stage are taken from the storm record and the policy and read back for correction) and raise `SIM_SPEED` so the fleet finishes in about 40 s.

| Segment | Time |
|---|---|
| Problem line + storm + triage | 0:00–0:30 |
| Hero call, short flow | 0:30–1:25 |
| Pipeline and browser filing | 1:25–2:15 |
| Fleet finish and closing line | 2:15–3:00 |

## 6. If the live demo cannot run

Decide within 20 seconds; do not debug on stage.

| Situation | Action |
|---|---|
| Voice is down, everything else works | Play the backup video for the call segment, then return to the live dashboard for the fleet |
| Internet is down | Switch to the hotspot of the spare phone (30 s). If that fails, play the backup video and narrate |
| Laptop problem | Backup video from a second device |

Say plainly that it is a recording. Judges forgive a network failure; they do not forgive a pretence.

## 7. Presenter keys

| Key | Action |
|---|---|
| S | Start scenario |
| H | Trigger hero call (pauses the fleet) |
| P | Pause / resume |
| R | Reset (press twice within 3 seconds) |
| L | Put the live-call panel away to show the whole map, or bring it back |
| A | Approve the hero case as reviewer (only when it was sent to review) |
| F | Try filing the hero case again (only when filing failed) |

## 8. Lines worth memorising

- Opening: "After a hailstorm, a farmer has 72 hours to tell the insurer. Today the system waits for the farmer. Ours goes to the farmer."
- On the fast path: "Simple answers never touch the big model. That is why it feels like talking to a person."
- On the browser: "No API. The agent uses the website like a person would."
- Closing: "312 of 340, with 68 hours to spare."

Replace the measured numbers in these lines with the ones from `scripts/report.py` after the last rehearsal.

## Optional automatic-weather opening

Use the laptop dashboard and run `setup/10-weather-demo.cmd` after services are ready. It resets the sandbox and switches the monitor to DEMO / SIMULATED. Show clear conditions, then wait 20 seconds without touching Start storm. Explain the hail code and gust threshold as the monitor automatically starts the storm and opens 340 synthetic cases. Continue with Call hero and the established phone flow. Select Live weather after the demonstration. Real data uses Open-Meteo; the controlled demonstration and insurance scenario are synthetic.
