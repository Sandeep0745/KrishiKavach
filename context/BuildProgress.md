# Build Progress — KrishiKavach

## Completion rule / source of truth
- User instructed: **Follow the standing completion rule in the guide throughout all 150 prompts.**
- **BLOCKED FOR VERIFICATION:** Guide and its exact standing completion rule have **not been supplied in this conversation**. Do not invent or claim adherence to unseen instructions. Record the verbatim rule here once provided, and check it at each future prompt.
- Requested now: **Begin with repository skeleton, NOT the entire implementation.**
- Progress: **Prompt 1 scaffold complete** (do not infer numbering from an unseen guide; this is a local milestone designation).

## Non-negotiable choices
- Destination: new `KrishiKavach/KrishiKavach/` hierarchy; never alter an original folder if one is later supplied.
- Runtime: Python 3.12 on Windows 11; Android-compatible browser UI.
- Server: Starlette; DB: SQLite; client: plain HTML/CSS/JavaScript.
- Live updates: Server-Sent Events (SSE).
- Planned components: MCP servers, decision service, LiveKit voice agent, browser filing automation, sandbox portal.
- Participation: exactly 1 **real** browser voice participant and 339 **simulated** farmers, with clearly distinct provenance.
- All claims and browser filing in the demo must be sandbox/test-only unless later explicitly authorized.

## Scaffold completed
- [x] Repository folders and Python package markers
- [x] Minimal Starlette homepage and health endpoint
- [x] Plain browser shell and static assets
- [x] Empty domain/service/integration boundaries
- [x] Config sample, SQLite schema placeholder, tests placeholder, project docs
- [x] `context/BuildProgress.md`

## Not yet implemented (intentionally)
- [ ] Crop-loss reporting workflow and validations
- [ ] SQLite persistence and migrations
- [ ] Decision rules and explainability
- [ ] Real voice participant via LiveKit credentials/agent
- [ ] 339 simulated farmer identities/events with test-only tagging
- [ ] SSE stream and reconnection logic
- [ ] MCP tools/servers and permissions
- [ ] Browser filing against local sandbox portal
- [ ] Android network/HTTPS/audio testing
- [ ] End-to-end demo and observability

## Future phase sequence (provisional; guide may override)
1. Domain models, SQLite schema and seeded fixtures.
2. Case creation API, validation, basic portal UI.
3. Decision service and auditable outcomes.
4. SSE dashboard + simulated farmer orchestrator (339).
5. LiveKit browser voice participant (1) + backend event bridge.
6. MCP servers and bounded tool permissions.
7. Mock sandbox claim portal + browser filing adapter.
8. E2E tests, Android/Windows runbook, demo rehearsal.

## Session log
- 2026-10-10: New isolated scaffold created. No original project supplied or modified. Dependencies/integrations beyond Starlette/Uvicorn not provisioned. Unseen completion-rule guide remains pending.

## Next prompt handoff
Confirm guide's standing completion rule and implement one bounded phase at a time; update this file with decisions, files changed, tests run, known gaps, and next action after each phase.

## Requirements baseline — 2026-10-10
- [x] Added `context/Requirements.md`: R-01–R-13 with testable acceptance conditions, O-01–O-06 optional enhancements, and explicit exclusions.
- [x] Scope fixed to synthetic wheat farmers in Sehore, Madhya Pradesh, one replayed hailstorm, FasalClaim Sandbox, one real browser participant plus 339 simulated farmers.
- [x] Safety boundary: explicit consent before sandbox-only browser filing; demo readiness is not official insurer eligibility.
- [ ] Requirements not yet implemented or acceptance-tested; future milestones must capture test evidence per requirement ID.
- [ ] Reconcile with the unavailable 150-prompt guide and its standing completion rule if supplied.
