# Automatic weather watch and judge demonstration

## Provider choice

Open-Meteo is the best fit for this educational, non-commercial prototype: no API key or payment card, global coordinate forecasts, current and hourly temperature/rain/weather-code/gust fields, UTC timestamps and batch village coordinates. The adapter was exercised against the real API for all 12 seeded Sehore villages. On the initial live check, no configured risk threshold was crossed; no storm was invented.

WeatherAPI offers current/forecast data but requires account credentials. IMD exposes official district-warning APIs and is a useful future corroboration source. This prototype's risk screen is based on modelled weather, not an official warning or verified crop loss.

Sources: [Open-Meteo forecast documentation](https://open-meteo.com/en/docs), [free API terms](https://open-meteo.com/en/terms), [WeatherAPI pricing](https://www.weatherapi.com/pricing.aspx), [IMD API reference](https://api.imd.gov.in/public/api_reference.html).

## Behavior

The orchestrator polls the weather MCP tool `get_crop_risk` every five minutes, checking each of the 12 configured village coordinates. The browser reads cached status; opening more dashboards does not increase provider requests. Live monitoring is enabled by default. API HTTP requests and forecast-location counts are recorded in the existing usage log. Twelve locations at five-minute intervals are approximately 3,456 location requests per day, within the published non-commercial free limits.

| Signal | Default prototype rule |
| --- | --- |
| Hail | WMO code 96 or 99 |
| Thunderstorm | WMO code 95 or 97 |
| Strong gust | At least 50 km/h |
| Heavy hourly precipitation | At least 20 mm in an hourly forecast interval |
| Heat | At least 40 C |
| Frost risk | At most 2 C |

Current measurements and hourly forecasts through the next six hours are considered. Current precipitation is not treated as an hourly accumulation. Units, array lengths and timestamps are checked. These configurable heuristics screen for potential crop risk; they are not an agronomic damage assessment. Hail codes depend on the forecast model and may be unavailable even when local hail occurs.

A verified hazard calls the existing scenario controller without a manual `Start storm` request. The existing hail scenario, March scenario clock, insured records, farmer replies and claim portal remain synthetic. A live forecast is the trigger for that sandbox exercise; it is never inserted as invented historical evidence or treated as a confirmed loss. Claims still follow the established evidence/consent pipeline.

A running, paused or completed scenario is preserved. The monitor does not erase it. Live automatic starts have a persisted six-hour cooldown in ignored `var/weather-watch.json`, retained across reset and restart. Missing/stale data, provider failures and invalid cooldown records suppress startup. Startup grace is 45 seconds so the Windows launcher's initial reset completes first.

## Configuration

Use `.env` or environment variables: `WEATHER_WATCH_MODE=live|off`, `WEATHER_POLL_SECONDS=300` (minimum 300), `WEATHER_COOLDOWN_SECONDS=21600`, `WEATHER_STARTUP_GRACE_SECONDS=45`, `WEATHER_GUST_KMH=50`, `WEATHER_RAIN_MM_H=20`, `WEATHER_HEAT_C=40`, `WEATHER_FROST_C=2`.

`WEATHER_MODE=replay` remains the historical evidence provider for the synthetic claims. It is independent of the new live watch. No new key is required. Automated test services set the watch to `off`, so ordinary regression tests neither query real weather nor unexpectedly dispatch farmers.

GET `/api/weather/status` exposes source, freshness, observations, risk reasons and trigger count. Local-only POST `/api/weather/demo` arms demo weather; POST `/api/weather/live` restores live polling. Loopback client, Host and Origin are checked. Public phone links can read status but cannot operate these presenter controls.

## Present to the judges

1. Start `setup/7-start-everything.cmd` and wait until the backend services are ready. Open the dashboard on the laptop and the existing HTTPS farmer link on the phone.
2. Run `setup/10-weather-demo.cmd`. It resets only the sandbox and arms simulated weather. Alternatively reset the dashboard, then click **Demo weather** on the local laptop dashboard.
3. Point to **DEMO / SIMULATED**, clear conditions and the 20-second countdown. Say: "For a repeatable demonstration, we are feeding simulated weather through the same detector used for the live API."
4. Keep your hands away from **Start storm**. After 20 seconds the feed reports hail code 99, gusts 75 km/h and hourly rain 25 mm. The monitor detects risk and automatically opens all 340 sandbox cases. The map, ranking, call queue and simulated calls then start.
5. Say: "In live mode this watcher queries Open-Meteo every five minutes. A risk threshold starts our sandbox response automatically; farmer evidence and consent are still required before filing."
6. Press **Call hero** to continue the established live phone call, photo capture and sandbox filing. The weather trigger starts the district; the live hero call remains presenter-controlled.
7. Select **Live weather** afterward. Reset the sandbox when ready for another run. If no real hazard is present, the correct result is to keep watching without starting a storm.

The same terminal demonstration is `.venv/Scripts/python.exe scripts/weather_demo.py --run`. It verifies 340 cases and saves `logs/weather-demo-result.json`; it never calls `/api/scenario/start`. `scripts/weather_demo.py --live` restores real polling. Demo weather never overwrites the persisted live cooldown.

## Validation artifacts

Local, ignored files: `logs/weather-feature-tests.txt`, `logs/weather-unit-tests.txt`, `logs/weather-full-core-tests.txt`, `logs/weather-browser-tests.txt`, `logs/weather-live-check.json`, `logs/weather-live-demo.txt`, `logs/weather-demo-result.json` and `logs/weather-presentation/`.

The first integration run exposed an MCP event-callback mismatch; it was corrected before committing. Browser layout tests cover 1366x768 and 1920x1080, plus the existing mid-call/reload checks. A controlled weather demo proves the automatic trigger; it does not establish that a real dangerous storm occurred. Actual phone microphone/camera rehearsal remains manual.

### Measured demonstration and browser results

- Final weather feature checks: 23 tests passed in 37.908 seconds, including real MCP transport, automatic district startup, local-control restrictions and both projector sizes.
- Existing Chrome regression and filing recovery checks: 14 tests passed in 195.431 seconds.
- The actual GitHub checkout's controlled weather demo automatically opened 340 cases without calling the manual scenario-start endpoint. The district then settled 339 simulated farmers: 311 filed, 11 unreachable, nine no damage, five escalated and three ineligible, with zero failed cases. The remaining live farmer awaited the presenter-controlled hero call.
- The recording is `logs/weather-presentation/automatic-weather-demo.gif`, with clear and automatically started screenshots in the same directory.
- The public farmer URL and read-only weather status returned HTTP 200. Public demo-control POST returned HTTP 403.
- Smoke confirmed all seven services were up, models warmed, the Filer window open and browser agent usable. During the demonstration it reported four readiness issues: an active scenario, a disconnected phone, and missing cloudflared/LiveKit CLI tools. This weather feature uses ngrok and the existing LiveKit SDK, not those two CLI tools. This smoke result does not certify a live phone rehearsal.

### Regression environment corrections

The first full discovery run exposed an older mocked filing-recovery test that still checked installed Playwright. The test now mocks that capability boundary and the real browser class runs only in the browser environment; all three unit recovery cases passed in both environments before the test-only commit. A subsequent full run encountered a single dashboard-class startup error (`sqlite3.OperationalError: database or disk is full`) on C:. The final run uses isolated test scratch under `D:/TravelBuddy/GopalK/GopalK/.runtime/weather-test-tmp`, without deleting existing user files or changing project configuration. The disk-full run is preserved in `logs/weather-core-disk-full-run.txt`.

### Final full-suite result

With test scratch on D:, full discovery passed: 144 tests in 436.283 seconds, OK with seven environment-dependent skips. The separate 14-test Chrome suite covers the six skipped UI checks and both methods in the skipped browser-recovery class. The final 23-test weather suite passed in 37.908 seconds. Python compilation, JavaScript syntax, documentation links, Git whitespace checks and the credential scan passed before the feature commit.

The actual app was returned to live Open-Meteo monitoring with clear conditions, an idle sandbox and zero cases. The completed district outcome is preserved in `logs/weather-demo-district-outcome.json`. The stable public farmer URL remains unchanged.
