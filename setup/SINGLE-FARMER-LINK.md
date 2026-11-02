# One reusable farmer link for judging

Use one ngrok **free development domain** for the existing live farmer, Ramlal (F0001). The URL remains the same across tunnel restarts while using the same account/domain. No domain purchase or paid plan is needed. The laptop must be awake, connected to the internet, with both the app and tunnel running; this is not always-on hosting.

## One-time setup

1. Create a **free** account at https://dashboard.ngrok.com/signup. Stay on the free plan; do not add a payment method.
2. Get the **authtoken** at https://dashboard.ngrok.com/get-started/your-authtoken.
3. Double-click `setup/4-open-env.cmd`. At the bottom of `.env`, add the following line with your own token, save, and close Notepad:

   ```text
   NGROK_AUTHTOKEN=your-own-token
   ```

   Keep this token in `.env` only. Do not send it in chat or put it in a screenshot. The launcher passes it to ngrok through the process environment, without copying it to a command line or another configuration file.
4. The official, signature-verified ngrok Windows client has been installed for this laptop in `.setup-tools/bin/ngrok.exe`. On a different laptop, install ngrok from https://ngrok.com/download/windows (the Microsoft Store option is recommended there), or put the official executable in `.setup-tools/bin/`.

The account assigns your domain. The launcher discovers it automatically, so no domain setting is needed in `.env`.

## Every presentation

1. Start `setup/7-start-everything.cmd` and wait for the services to load. Close old service windows before starting a fresh demo, especially after Python environment changes.
2. Double-click `setup/9-stable-farmer-link.cmd`.
3. Copy the **FARMER DEMO LINK** it prints. The exact same URL is saved in `var/farmer-link.txt` and as the clickable `var/Farmer Demo.url` shortcut.
4. Open that URL in Chrome on the phone. On ngrok's free-plan notice, choose **Visit Site**. Tap **फोन चालू करें** and allow microphone, camera and location access.
5. On the laptop dashboard, start the storm (**S**), let the district begin, then call the farmer (**H**). Answer on the phone. For the synthetic demo, confirm Ramlal's identity: **हाँ, मैं रामलाल बोल रहा हूँ।** Follow the agent's questions, provide the crop photo, and consent only after the read-back is correct.
6. After the call, resume the district with **P**. For another judge, reset with **R twice**, then repeat S/H/P. Reuse the same phone bookmark; do not create another tunnel.

Keep both command windows open. Closing the tunnel or shutting down the laptop makes the link unavailable until you start them again. Only one person should answer the live farmer call at a time. Multiple phones opening this URL share Ramlal's identity, not independent cases.

## Troubleshooting

- **Token missing:** add `NGROK_AUTHTOKEN` to `.env`; never put the token in the launcher.
- **Farmer app not ready:** start step 1 first. The local page must be at `http://127.0.0.1:8000/farmer`.
- **Port 4048 already in use:** the stable-link launcher may already be running. Use its window, or close that launcher before starting another.
- **No endpoint / free limits reached:** check the token and account dashboard. Do not upgrade to a paid plan for this project. `setup/8-phone-link.cmd` remains a temporary-link fallback, whose address changes.
- **Old app behavior after an edit:** close the old service window and restart step 1, then refresh the farmer page.
- **Phone rings but agent does not speak:** check the voice-worker log; a reachable farmer page verifies the tunnel, not the voice-provider connection.

This laptop's setup still requires your account token before a real reusable public URL can be verified.

## Verification on 10 October 2026

- Launcher tests: 7 passed, including missing credentials, unrelated endpoints, an existing launcher, failed public verification, early agent exit, and saving a verified URL without leaking the token.
- Installed client: ngrok 3.39.11; Windows reported a valid `ngrok, Inc.` signature. The actual client accepted the generated v3 configuration.
- Python compilation and the project secret scan passed.
- Live readiness: decision models warmed, Filer browser open, browser agent available. The current scenario needs resetting and a phone must reconnect before the next demonstration. The older smoke checklist also reports the absent cloudflared and LiveKit CLI tools; ngrok replaces cloudflared for this launcher, and the existing Python voice-worker command is unchanged.
- Real ngrok endpoint verification remains pending your account token. No reusable public URL has been claimed yet.

Official references: https://ngrok.com/docs/pricing-limits/free-plan-limits and https://ngrok.com/download/windows. Free plans include an assigned domain and display an initial browser notice; usage limits apply.
