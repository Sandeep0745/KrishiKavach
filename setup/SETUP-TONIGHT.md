# Setup tonight

Do the parts in order. Tick each box. Nothing here costs money: **never enter a card or any payment detail.**

## Part A - Install the tools (about 10 minutes)

- [ ] 1. Open the `setup` folder and double-click **`1-install-tools.cmd`**. Click **Yes** whenever Windows asks for permission.
- [ ] 2. When it says "Finished", **close that window**.
- [ ] 3. Double-click **`2-check-tools.cmd`**. It installs Python 3.12 and then prints a report.
- [ ] 4. Every line must say `OK`, and Node must be 20 or higher. If a line says `MISSING`, tell Claude which one.
- [ ] 5. Double-click **`2c-install-packages.cmd`**. It creates the project's three Python environments with the package versions tested on the team laptop and downloads the local English voice (10 to 20 minutes, about 3 GB). The team laptop already has them; there this step only checks.

## Part B - Create the free accounts (about 30-40 minutes)

First: in the project folder, copy **`.env.example`** and name the copy **`.env`**. Open `.env` in Notepad. Paste each key after the `=` sign with no spaces and no quotes.

Use "Continue with Google" where offered; it is the quickest. If any site insists on a card, close it and skip that service.

| Done | Service | Open | What to do | Paste into `.env` |
|---|---|---|---|---|
| [ ] | LiveKit Cloud | https://cloud.livekit.io | Sign up. Create a project named `ghante72`. Go to Settings, then API Keys, then create a key | `LIVEKIT_URL` (starts with `wss://`), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` |
| [ ] | Deepgram | https://console.deepgram.com/signup | Sign up. Create an API key (the console offers one on first login). Check the balance shows the free credit | `DEEPGRAM_API_KEY` |
| [ ] | Sarvam AI | https://dashboard.sarvam.ai | Sign up. Open API Keys and copy or create a key. Check the free credit shows | `SARVAM_API_KEY` |
| [ ] | Groq | https://console.groq.com/keys | Sign up. Create API Key | `GROQ_API_KEY` |
| [ ] | Google AI Studio | https://aistudio.google.com/apikey | Sign in with Google. Create API key. Open the rate-limit page and write down the free requests per minute and per day shown for the Flash models | `GEMINI_API_KEY` |
| [ ] | Jev (try only) | https://console.typesafe.ai | Try to sign up. Keep the key **only** if you get one with free credit and no payment method. Waitlist or card request: close it | `JEV_API_KEY` |

A key is shown only once on most sites. Paste it into `.env` straight away.

- [ ] Save `.env`. Do not send it to anyone and do not paste keys into a chat.

## Part C - Connect the LiveKit CLI (2 minutes)

- [ ] Open a new Command Prompt, type `lk cloud auth`, press Enter, and approve in the browser page that opens.

## Part D - Phones

**Farmer phone (Android)**
- [ ] Chrome is installed and updated (Play Store).
- [ ] Open the camera app and a voice recorder once to confirm camera and microphone work.
- [ ] Settings, Location: on.
- [ ] Settings, Display, Screen timeout: longest available.
- [ ] Media volume up. Find where "Do not disturb" is so you can switch it on before the demo.
- [ ] At least 500 MB free storage and battery above 50 percent.

**Hotspot phone**
- [ ] Mobile data working with a few GB available.
- [ ] Hotspot switched on once; laptop and farmer phone both joined it and opened a website.
- [ ] Hotspot name and password written down.

## Part E - Tell Claude

Send Claude:
1. The contents of `setup/check-report.txt` (it contains no secrets).
2. Which services you got keys for, as a list of names only. **Not the keys.**
3. What happened with Jev (key, waitlist, or card request).
4. The Gemini free limits you wrote down.
