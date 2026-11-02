# Laptop setup — 9 October 2026

Project: `D:\TravelBuddy\GopalK\GopalK`

Python 3.12.15 is installed under `.runtime/python`. The existing backend,
voice, browser, and GPU environment configurations now point to that runtime.
The backend, voice, and browser package checks and imports pass.
The Hindi encoder and Laya model are downloaded under `.runtime/huggingface`.
The supplied Piper voices and speech cache are preserved. `.env` is unchanged.

Windows setup launchers load `setup/local-runtime.cmd` for the local tools,
model cache, UTF-8 settings, and a fresh Filer browser profile.

## Run

Double-click `setup/7-start-everything.cmd`. Allow roughly a minute for startup.
Open http://localhost:8000/ for the dashboard. Close the running instance before
starting another. Press Ctrl+C in the launcher window to stop it.

For a phone, run `setup/8-phone-link.cmd` and follow its HTTPS link instructions.
The farmer page downloads its JavaScript libraries and MobileCLIP photo model
on first use. This page and a microphone/camera call were not tested during setup.

## Verification

- 101 automated tests completed: OK, with 6 skipped. See `logs/laptop-tests.txt`.
- All seven local HTTP services responded successfully.
- ROUTE, PERIL, and TRIAGE model warm-up completed.
- Chrome's Filer debugging connection and visible sandbox window work.
- Dashboard loads in Chrome with no JavaScript errors.
- Voice worker registered with LiveKit Cloud.

## Remaining tool downloads

cloudflared and the LiveKit CLI are not installed. Both winget and direct official
release downloads failed with network connection resets. Retry on a network that
can download GitHub release assets. The phone-link script already falls back to
Windows SSH when cloudflared is absent. The current Python voice worker connected
successfully without the LiveKit CLI.

No actual farmer call, phone photo classification, or live filing was performed.
