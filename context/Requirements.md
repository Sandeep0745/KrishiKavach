# Requirements

## 1. Goal and success

**Goal:** a working system that, on stage, detects a storm, calls a farmer in their selected supported language, collects the loss details and a photo, files the report in a browser by itself, and reads back a reference number, while a map shows the same thing happening across a district.

**The build succeeds if**
1. The demo in `DemoScript.md` runs end to end five times in a row without a manual fix.
2. Each of the six expected components is doing a job that would break the demo if removed.
3. A judge can see at any moment what is live and what is simulated.

## 2. Priorities

| Tag | Meaning | Rule |
|---|---|---|
| **P0** | The demo fails without it | Must pass its gate before the next phase starts |
| **P1** | Makes the demo clearly better | Built only after all P0 of the same phase pass |
| **P2** | Stretch | Built only after Gate 4 passes |

## 3. Scope

**In scope:** one district (Sehore, Madhya Pradesh), four speech languages (Hindi, English, Malayalam and Tamil; Sehore starts in Hindi), one event type (hailstorm on standing wheat), one hero farmer live, about 340 simulated farmers, one sandbox claim portal.

**Out of scope:** anything that costs money (including real telephony), other languages (P2), payout calculation, surveyor workflow, enrolment, real government systems, real farmer data, user accounts and login, production deployment.

## 4. Actors

| Actor | Who | Interface |
|---|---|---|
| Farmer (hero) | A team member playing Ramlal on stage | Phone: farmer web app (rings, talks, takes photo) |
| Farmer (simulated) | Scripted persona | None; driven by the simulator |
| Presenter | Team member at the laptop | Dashboard with presenter controls |
| Judges | Audience | Projector showing dashboard and browser window |

## 5. Functional requirements

Each requirement has an ID used in `PhasewiseRoadmap.md` and `Testing.md`.

### A. Storm detection and dispatch

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-01 | P0 | The Sentinel agent gets storm events from the weather MCP server and finds the villages inside the affected area | Starting the scenario produces one `storm.detected` event listing the affected villages from the scenario file |
| FR-02 | P0 | For each affected village, insured farmers are fetched from the registry MCP server and a case is opened per farmer with a deadline of event time + 72 h | 340 cases exist after detection, each with the correct deadline |
| FR-03 | P0 | The Dispatcher ranks cases with the System One TRIAGE decision; every decision is logged with its latency | 340 `s1.decision` events of type TRIAGE; the call queue is ordered by the resulting priority |
| FR-04 | P0 | The Dispatcher places calls up to a concurrency limit, retries unanswered calls up to 3 times, and only calls between 08:00 and 20:00 scenario time | No more than the limit are in `CALLING`/`IN_CALL` at once; an unanswered case ends `UNREACHABLE` after 3 attempts |
| FR-05 | P1 | Live mode: the weather MCP server returns real data from Open-Meteo for a location and time | A tool call for a real coordinate and date returns non-fixture values |

### B. Voice call (hero farmer)

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-10 | P0 | The farmer app shows an incoming call with a ringtone; accepting connects a two-way multilingual voice conversation | Phone rings within 2 s of dispatch; audio flows both ways |
| FR-11 | P0 | The agent opens by confirming identity, saying who is calling, naming the recorded event in the farmer's village, and asking whether the crop was damaged | Heard in the first two agent turns |
| FR-12 | P0 | The agent collects: damage confirmed, field (khasra) confirmed, cause of loss, time of loss, share of area damaged, crop stage, and consent to file | All slots filled in the case record at the end of a normal call |
| FR-13 | P0 | Every farmer utterance is routed by the System One ROUTE decision. Clear yes/no answers take the fast path (no LLM call); other turns go to the LLM | Dashboard shows the route, confidence and latency per turn; fast-path turns have no LLM call in the log |
| FR-14 | P0 | The farmer can interrupt the agent; the agent stops speaking and listens | Speaking over the agent cuts its audio within about half a second |
| FR-15 | P0 | If the farmer asks for a person, or the model detects distress or repeated confusion, the agent says a human will call back and the case becomes `ESCALATED` | Saying "मुझे किसी आदमी से बात करनी है" ends the flow with status `ESCALATED` |
| FR-16 | P0 | Before filing, the agent reads back the details and asks for consent; without a yes, nothing is filed | A "no" at consent leaves the case unfiled and `ESCALATED` |
| FR-17 | P0 | After filing, the agent reads the reference number digit by digit on the same call. If filing takes longer than 90 s the agent ends the call politely and the number arrives as a message | Reference heard on the call in the normal case; message arrives in both cases |
| FR-18 | P1 | The farmer can ask a side question (for example when the surveyor will come) and get a short correct answer, then the agent returns to the next missing slot | One side question handled without losing collected slots |
| FR-19 | — | *Removed: a real telephone call needs a paid provider* | — |
| FR-20 | P2 | A second language (Marathi) | Same flow passes in Marathi |
| FR-21 | P0 | Scripted agent lines are played from a pre-built audio cache; live speech synthesis is used only for sentences the LLM writes and for the reference number | A normal hero call makes no speech-synthesis request for scripted lines (checked in the usage log) |

### C. Evidence on the phone (edge)

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-30 | P0 | The farmer app takes a photo and classifies it on the phone into: hail damage, waterlogged, lodged (flattened), healthy, not a crop. It shows label, confidence and inference time | Works with the phone in airplane mode after the model was loaded once |
| FR-31 | P0 | The app attaches GPS coordinates and capture time and uploads the photo with the on-device result | Evidence record has label, confidence, lat, lon, captured_at, file hash |
| FR-32 | P0 | If there is no network, the capture is stored on the phone and uploaded automatically when the network returns | Capture offline, reconnect, record appears on the server without user action |
| FR-33 | P1 | If the label is "not a crop" or confidence is low, the app asks for a retake | Photo of a wall triggers the retake prompt |

### D. Claim pipeline

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-40 | P0 | The Evidence agent assembles an evidence pack: photo, on-device label, GPS, capture time, the weather record at that place and time from the weather MCP server, and distance from the insured plot | Pack stored with a SHA-256 of the photo; weather record present |
| FR-41 | P0 | The Eligibility agent decides eligible / ineligible / human review from: policy active, crop insured, peril covered (System One PERIL), inside 72 h, and evidence consistency (System One VERIFY). It records the reasons | Each of the four test personas in `Testing.md` gets the expected verdict |
| FR-42 | P0 | The Filing agent opens the sandbox portal in a visible browser, fills all three pages, uploads the photo, submits, and returns the reference number | Reference returned and the claim is visible in the portal's admin list |
| FR-43 | P0 | If the browser agent fails or exceeds its time limit, a scripted fill completes the same form; the dashboard shows that the fallback ran | Killing the agent mid-run still ends with a filed claim and a visible "scripted fallback" label |
| FR-44 | P0 | The Follow-up agent gives the reference number to the voice agent and sends a message card to the farmer app; the case becomes `FILED` with time-to-file recorded | Message visible on the phone; case shows time-to-file |
| FR-45 | P1 | Estimated loss value from mandi price × expected yield × damaged area, using the mandi MCP server | A rupee estimate appears in the evidence pack, labelled as an estimate |
| FR-46 | P1 | The evidence pack opens as a one-page printable summary | Link on the hero panel opens it |
| FR-47 | P2 | Before/after satellite vegetation index for the plot | Image pair in the pack |

### E. Fleet simulation and dashboard

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-50 | P0 | Non-hero farmers are played by scripted personas. Their cases go through the same triage, eligibility and filing-by-API path; only voice and browser are skipped | Portal admin list shows a real record for every simulated `FILED` case |
| FR-51 | P0 | A district map shows every case as a dot coloured by status, with the storm passing over it | Dots change colour as statuses change |
| FR-52 | P0 | A 72-hour countdown and counters (affected, reached, filed, needs human, unreachable) | Final state matches the scenario totals in `SystemDesign.md` §12 |
| FR-53 | P0 | A System One ticker lists each decision: type, answer, confidence, latency, provider | Rows appear live |
| FR-54 | P0 | An agent strip lights up the agent that is working; an MCP log lists tool calls with server name | Visible during hero pipeline |
| FR-55 | P0 | A hero panel shows the live transcript, slots filling in, the evidence pack and filing progress | Visible during the hero call |
| FR-56 | P0 | Presenter controls: start scenario, trigger hero call, pause/resume, reset | Keyboard shortcuts and buttons both work; reset returns to a clean state in under 10 s |
| FR-57 | P1 | The browser agent's window is mirrored inside the dashboard as a live screenshot stream | Visible in the hero panel |
| FR-58 | P0 | Simulated and live are always labelled | "LIVE" on the hero, "Simulated" count on the fleet, at all times |
| FR-59 | P1 | A reviewer can approve a case that Eligibility sent to human review; the pipeline then continues to filing and the approval is logged | Approving the "far away photo" test persona files its claim and the log shows a human approval |

### F. Sandbox claim portal

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-60 | P0 | A three-page web form (farmer and policy, loss details, evidence and declaration) ending in a confirmation page with a reference number | A person can complete it by hand |
| FR-61 | P0 | A JSON API to create and read claims, and an admin page listing all claims | Used by the simulator and by tests |
| FR-62 | P0 | Every page carries a banner: "Demo sandbox — not a government website". No government names, logos or emblems | Visible on all pages |

### G. MCP

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-70 | P0 | Weather MCP server: storm events for a district; weather at a point and time | Tools listed and callable from an MCP client |
| FR-71 | P0 | Registry MCP server: farmers by village, farmer, policy, case read/update | Same |
| FR-72 | P1 | Mandi MCP server: price for a crop in a district | Same |
| FR-73 | P0 | At least two different clients use the servers: the voice agent and the pipeline | Tool calls from both appear in the MCP log |

### H. System One decision service

| ID | P | Requirement | Acceptance |
|---|---|---|---|
| FR-80 | P0 | One endpoint for all decisions, with the provider order set by configuration: Laya (local), Jev (only if free), LLM fallback | Changing the order changes the provider shown in the ticker |
| FR-81 | P0 | Every decision records answer, confidence, latency and provider, and emits an event | Present in the event log |
| FR-82 | P0 | An evaluation script reports accuracy and latency of the configured provider on our labelled set | Report printed and saved |

## 6. Non-functional requirements

| ID | P | Requirement | Target | How measured |
|---|---|---|---|---|
| NFR-01 | P0 | Voice response time, end of farmer speech to first agent audio | Fast path: median ≤ 0.8 s. LLM path: median ≤ 1.5 s, 95th percentile ≤ 2.5 s | Timestamps in the voice worker log over 20 turns |
| NFR-02 | P0 | System One decision time | Median ≤ 250 ms (remote) or ≤ 150 ms (local) | Decision service log |
| NFR-03 | P0 | On-phone classification time after the model is loaded | ≤ 1.5 s on the demo phone | Shown in the app |
| NFR-04 | P0 | Filing time | Browser agent ≤ 75 s; scripted fallback ≤ 15 s | Filer log |
| NFR-05 | P0 | Hero end to end, ring to reference number | ≤ 3 min 30 s | Stopwatch on dashboard |
| NFR-06 | P0 | Demo reliability | 5 consecutive clean runs | Gate 5 |
| NFR-07 | P0 | Every external dependency has a fallback selectable by environment variable | See `TechDecisions.md` §8 | Fallback drills in `Testing.md` |
| NFR-08 | P0 | One command starts everything; one command resets | `python scripts/dev.py`, `python scripts/reset.py` | Run them |
| NFR-09 | P0 | Runs on a Windows 11 laptop with no GPU | — | It does |
| NFR-10 | P0 | Synthetic data only; secrets only in `.env`, never committed | — | Review |
| NFR-11 | P0 | Every event is appended to a log file so a run can be inspected afterwards | `logs/events.jsonl` | File exists and is complete |
| NFR-12 | P0 | Total spend for the whole build | ₹0. No payment method on any account | Provider dashboards show nothing charged and no card |
| NFR-14 | P0 | Use of every limited free allowance is counted, and development defaults do not consume credits | `logs/usage.json` and `scripts/usage.py`; `CREDIT_SAVER=1` by default | Run `usage.py` |
| NFR-13 | P0 | Farmer page controls and dashboard in English; speech in Hindi, English, Malayalam or Tamil, with automatic switching | — | Review |

The latency targets are what we commit to measuring and reporting. If a measured value misses a target, we report the real number on stage and do not hide it.

## 7. Constraints

- Four days, small team.
- Zero budget: open-source software, free tiers and no-card signup credits only.
- Development machine: Windows 11, x64.
- The farmer app must be served over HTTPS for microphone and camera access on a phone.
- Venue network is not trusted: a phone hotspot must be enough to run the demo.
- Python 3.12 (required by the browser agent library).

## 8. Traceability

| Hackathon component | Requirements that prove it |
|---|---|
| Agentic browser use | FR-42, FR-43, FR-57 |
| Ultra-low-latency voice | FR-10 to FR-17, FR-21, NFR-01 |
| System One decision models | FR-03, FR-13, FR-41, FR-80 to FR-82, NFR-02 |
| Edge models | FR-30 to FR-33, NFR-03 |
| Multi-agent orchestration | FR-01 to FR-04, FR-40 to FR-44, FR-54, FR-59 |
| MCP | FR-70 to FR-73 |

## Automatic crop-risk monitoring extension

- Watch the 12 seeded Sehore village coordinates without clicking Start storm. Trigger the sandbox scenario when current weather or the next six forecast hours contain a configured crop-risk signal: hail/thunderstorm codes, gusts at least 50 km/h, hourly precipitation at least 20 mm, temperature at least 40 C or at most 2 C. These are configurable prototype screening thresholds, not agronomic damage findings.
- Show provider, freshness, measured risk reasons and whether data is LIVE or DEMO. Failures must remain visible and must not trigger.
- Do not reset an active scenario or trigger duplicates. Persist cooldown across restarts.
- Provide a deterministic clear-to-danger demonstration using the same parser, risk rules and automatic starter. Continue to label the farmers, scenario and claims synthetic.
