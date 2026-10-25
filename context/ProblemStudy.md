# Problem study

## 1. The problem

Under India's crop insurance scheme (PMFBY), a farmer whose field is hit by a localized calamity, or whose harvested crop is damaged while drying in the field, has to **report the loss within 72 hours**. If the report is not made in that window, the individual claim is not assessed.

Reporting means using an app, a helpline, a bank branch or an agriculture office, and giving policy details, crop details, the cause and the extent of damage. The farmer has to do this in the three days right after a storm, often with low literacy, a basic phone, a damaged field to deal with and a patchy network.

**Problem statement for the pitch**

> After a hailstorm, a farmer has 72 hours to tell the insurer. Today the system waits for the farmer to find it. We reverse that: the system finds the farmer.

## 2. Who it is for

| Persona | Situation | What they need |
|---|---|---|
| **Ramlal, 52, wheat farmer, Sehore (MP)** — the hero of the demo | 1.8 ha insured, keypad or entry-level Android phone, speaks Hindi, reads slowly, has never opened the insurance app | Someone to call him, ask simple questions in Hindi and do the paperwork |
| **District agriculture officer** | Hundreds of loss reports arrive by phone and paper after one storm; many arrive late or incomplete | One screen showing who was affected, who has been reached, who still needs a human |
| **Insurer's claims desk** | Reports arrive with missing fields and no evidence; disputes follow | Complete, consistent reports with photo, location, time and a weather record attached |

The buyer in a real deployment would be a state agriculture department or an insurer. The user is the farmer. The demo speaks to both: the call is for the farmer, the map is for the officer.

## 3. Facts and how far each is verified

Use only "verified" rows on slides without re-checking. Re-check the others first.

| # | Fact | Status | Source |
|---|---|---|---|
| F1 | Loss must be intimated within 72 hours of the event for localized calamities and post-harvest losses | **Verified** (insurer's own claim page) | [SBI General — PMFBY claim process](https://www.sbigeneral.in/claimprocess) |
| F2 | Channels: Krishi Rakshak helpline 14447, bank branch, agriculture department, district official, the government crop app | **Verified** | same |
| F3 | Localized calamities named by an insurer: landslide, flood/inundation, cloud burst, hailstorm. Post-harvest cover: up to 14 days after harvest for cut-and-spread crops, against cyclone, unseasonal rain, hailstorm | **Verified from one insurer's blog**; check the peril list against the official operational guidelines before quoting | [SBI General blog](https://www.sbigeneral.in/blog/general-insurance/general-gi-simplified/pmfby-claim-process) |
| F4 | Kisan e-Mitra, the government's voice chatbot, answers questions and grievances for the PM-Kisan scheme in 11 languages; it informs, it does not file anything | **Verified** | [Wadhwani AI — Kisan e-Mitra](https://www.wadhwaniai.org/impact/agriculture-solutions/kisan-e-mitra/) |
| F5 | ₹947.72 crore of claims pending in Rajasthan (July 2025); delays of up to 14 months reported in a 2025 IIM study | **Secondary source only** — find the primary report before using | [IAS Gyan summary](https://www.iasgyan.in/daily-current-affairs/pradhan-mantri-fasal-bima-yojana-systemic-failures) |
| F6 | 78.41 crore farmer applications insured since 2016 | **Headline only** — the article could not be opened; verify | [DD News](https://ddnews.gov.in/en/pmfby-a-safety-net-for-farmers-78-41-crore-applications-insured-since-2016/) |
| F7 | How many farmers miss the 72-hour window | **Not found.** This is the number the pitch most needs | Open research item R1 below |

### Open research items (a person should do these, not Claude)

| # | Item | Why it matters | Where to look |
|---|---|---|---|
| R1 | A credible figure, or even a documented case, of claims lost because the 72-hour intimation was missed | It is the first slide | Parliamentary answers (Lok Sabha/Rajya Sabha questions on PMFBY), CAG audit reports, state agriculture department press notes, regional news after specific hailstorms |
| R2 | The official peril list and the exact intimation data fields | Makes the sandbox form and the eligibility rules defensible | PMFBY Revamped Operational Guidelines on pmfby.gov.in |
| R3 | One real hailstorm event in Madhya Pradesh with date and affected districts | Lets the replayed storm be modelled on a real event | IMD bulletins, news reports |
| R4 | Typical insured farmers per district | Makes "340 farmers" on the map defensible, or tells us to change it | PMFBY dashboard, state-level PIB releases |

If R1 finds nothing solid, the fallback framing is qualitative and still true: *the rule exists, the burden is on the farmer, and no current tool carries that burden for them.*

## 4. What exists and where the gap is

| Existing thing | What it does | What it does not do |
|---|---|---|
| Helpline 14447 / Krishi Rakshak | A farmer can call and report | Reactive; the farmer has to know the number and the deadline, and wait in a queue after a mass event |
| Crop Insurance app | Self-service loss reporting | Needs a smartphone, data, literacy and familiarity with the app |
| Kisan e-Mitra | Answers scheme questions by voice in 11 languages | Information only, for PM-Kisan; takes no action |
| Private agri-advisory voice bots | Crop advice, weather, prices | Advice only |

**The gap:** nothing is proactive, and nothing completes the task. Every existing tool waits for the farmer and stops at information.

**Our novelty, in one sentence each**
1. **Proactive:** triggered by the weather event, not by the farmer.
2. **Action, not advice:** the output is a filed report with a reference number.
3. **Evidence by default:** every report carries a photo classified on the phone, GPS, time and the weather record for that spot.
4. **Fleet-scale:** one storm means hundreds of calls; fast decision models choose who to call first.

## 5. Why now

- Voice models for Indian languages are now fast and cheap enough for a natural phone conversation.
- Browser agents can operate web forms that have no API, which is how most public portals work.
- System One decision models (Jev and open equivalents) make thousands of small routing decisions affordable in real time.
- Small vision models run in a phone browser with no server.

## 6. How this maps to the judging criteria

| Criterion | Our answer | Evidence in the demo |
|---|---|---|
| Problem relevance and clarity | One rule, one deadline, one sentence | Opening slide: the 72-hour rule and the countdown clock |
| Novelty | Proactive + completes the task, where existing tools are reactive + informational | The phone rings on stage; the form fills itself |
| Solution and feasibility | Working end-to-end system; honest boundary between real and simulated; a real deployment path (insurer or state as the caller) | Live call, live browser agent, labelled simulation |
| Potential impact | Every insured farmer in a storm's path, reached within hours | The map going green with a counter |
| Clarity and completeness | All six expected components, each with a necessary job | Dashboard panels name each one as it acts |
| Eye-catching demo | Countdown, ringing phone, live voice conversation, self-filling form, map turning green | `DemoScript.md` |

## 7. Questions judges are likely to ask

| Question | Answer |
|---|---|
| "Is that the real government portal?" | No. It is our sandbox with the same kind of fields. Filing into a real system needs the farmer's own login and an agreement with the insurer; we show that the agent can operate a form like it. |
| "Why would a farmer trust a robot call?" | The call comes from the insurer or the agriculture department they already enrolled with, names their village, crop and field, asks consent before filing, and offers a human at any point. |
| "What stops false claims?" | Each report carries a photo, GPS and time that are checked against the weather record for that location; mismatches go to a human. The surveyor's assessment still happens afterwards. We file the intimation, we do not decide the payout. |
| "What if there is no network?" | The photo is classified and stored on the phone and syncs later. A voice call needs only a basic phone connection. |
| "Why a System One model and not just an LLM?" | Ranking hundreds of farmers and routing every utterance are small, bounded decisions made thousands of times. They need to be fast, cheap and return a confidence, which is what these models are for. The LLM is kept for conversation. |
| "Why English, if farmers speak Hindi?" | The demo call is in English (team decision, 9 Oct 2026). The first build was Hindi and was tested in Hindi; the speech models cover the major Indian languages, so switching back is the scripted lines, the prompts, the decision model's examples and the speech language codes. |
| "How is this different from Kisan e-Mitra?" | That answers questions about PM-Kisan. This acts: it calls first and files the report. |

## 8. Ethics and safety position

- The agent states who it is calling for and that it is an automated assistant.
- It asks explicit consent before filing and reads the details back first.
- It never promises a payout or an amount.
- It hands over to a human when the farmer asks, is distressed, or the model is unsure.
- Calls only between 08:00 and 20:00 local time.
- The demo uses synthetic people and a sandbox portal only.
