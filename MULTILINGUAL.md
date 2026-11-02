# Multilingual farmer calls

Sehore/Madhya Pradesh starts in Hindi; Kerala starts in Malayalam; Tamil Nadu starts in Tamil. Other states use English for this four-language prototype. A per-call farmer language is selected from the registry village, never shared between farmers.

Sarvam Saaras v4 auto-detects each spoken turn and translates it to English for the existing decision and form extraction rules. The source language selects replies in Hindi, English, Malayalam or Tamil. Language requests and misunderstanding complaints repeat the current question without recording identity, damage, refusal or consent. Short English acknowledgements do not override an Indian-language conversation. Unsupported or low-confidence language metadata keeps the current speech language.

Bulbul v3 speaks the selected language. Each language has its own cache identity; repeated cached sentences use no new synthesis request. CREDIT_SAVER=1 can use English Piper only for English. Hindi, Malayalam and Tamil require uncached Sarvam synthesis from existing signup credits. Speech failures are visible and stop the call for human follow-up.

## Configuration

Keep VOICE_MULTILINGUAL=1 (enabled in your local .env). STT_PROVIDER=sarvam is set. VOICE_DEFAULT_LANGUAGE may be hi-IN, en-IN, ml-IN or ta-IN; leave it blank to use the state. VOICE_MULTILINGUAL=0 with STT_PROVIDER=deepgram restores the original English path. Restart the voice worker after changing configuration.

Run the existing setup/7-start-everything.cmd and setup/9-farmer-link.cmd launchers. The stable farmer link requires the laptop services and ngrok to keep running.

## Judge demonstration

1. Open the dashboard on the laptop and the stable /farmer URL on the phone.
2. Reset the synthetic sandbox and ring the farmer (or use the automatic weather demonstration).
3. Answer the call. The greeting is Hindi.
4. Say “I do not understand Hindi. Please speak English.” The agent repeats the same question in English; the form has not advanced.
5. Continue in English, or say “എനിക്ക് ഹിന്ദി മനസ്സിലാകുന്നില്ല. മലയാളത്തിൽ സംസാരിക്കൂ.” for Malayalam, or “எனக்கு இந்தி புரியவில்லை. தமிழில் பேசுங்கள்.” for Tamil. The agent repeats in that language.
6. Give actual demo answers, take the crop photo, listen to the read-back and give explicit consent. Check the sandbox claim reference.
7. Show the dashboard language labels. Farmer text marked “English translation” is a translation of microphone speech, not an English-only farmer conversation.

## Checks

- .venv-voice/Scripts/python.exe -m unittest tests.test_multilingual tests.test_multilingual_voice -v
- .venv-voice/Scripts/python.exe scripts/multilingual_live_check.py — synthetic TTS-to-streaming-STT round trip using signup credits; repeated runs reuse generated input audio. This does not replace a human microphone test.
- .venv-voice/Scripts/python.exe scripts/build_tts_cache.py --language hi-IN --dry-run — estimate uncached characters before preparing a language cache. Repeat with en-IN, ml-IN or ta-IN. Remove --dry-run to synthesise within --max-chars.

Verified on 11 October 2026: the farmer heard the Hindi greeting on a real phone, said “Sorry, I do not understand Hindi”, heard the English reply, and continued answering claim questions. The language request repeated GREET without advancing identity or claim slots. The initial silent greeting was corrected by waiting for the room audio output before speaking.

Automated results: 158 regression tests passed (7 optional voice tests skipped in the core environment); 22 focused multilingual/voice tests passed in the voice environment. Real Sarvam synthetic speech recognition and language detection passed for all four languages; real LLM extraction retained the claim fields in all four languages. Synthetic speech is not a native-speaker microphone test.

The real phone rehearsal continued in English through damage details, photo upload and explicit consent. Case case_0001 was correctly escalated for review: the phone photo location was 1,474.9 km from the insured Sehore plot, and its weather record did not support hail. No claim reference was issued. Do not bypass these evidence checks for a demonstration. For a successful filing rehearsal use the existing synthetic test fixture with Sehore coordinates, clearly labelled as synthetic, or collect evidence at the insured plot.

Human checks still required: native-speaker wording/pronunciation review, Malayalam and Tamil speech on the phone, and a successful complete phone-to-sandbox-claim rehearsal with consistent evidence. Do not treat synthetic audio or a text-only test as proof these manual checks passed. The user authorized committing the technically verified multilingual feature after the automated browser rehearsal. These remaining manual checks still apply before claiming complete demonstration readiness.

Commit message: feat(voice): add adaptive multilingual farmer calls


## Actual farmer browser / LiveKit check — 11 October 2026

Automated Chrome farmer-page rehearsal passed: Hindi greeting, synthetic Malayalam microphone request, Malayalam reply audio received by the browser, synthetic Tamil microphone request, Tamil reply audio received by the browser. Saaras reported ml-IN and ta-IN; call.language_changed recorded hi-IN → ml-IN → ta-IN. Identity and consent remained unanswered throughout, so the request did not falsely grant either. Audio monitoring recorded 712 buffers, 106 non-silent. Results are in ignored logs/multilingual/browser-call-results.json. This uses the actual farmer app and real LiveKit/Sarvam connections, but a generated microphone and desktop Chrome; it is not a physical-phone/native-speaker check or a complete filing test.

Repeat with .venv-browser/Scripts/python.exe scripts/multilingual_browser_check.py while the services and voice worker are running. Prepare the cached synthetic inputs first with scripts/multilingual_live_check.py in the voice environment if missing. The browser test resets the synthetic scenario and rings the hero, so do not run during another demonstration.

Final pre-commit checks on 11 October 2026: 22 focused tests passed; syntax compilation and secrets scan passed; git diff --check passed. Filer /health subsequently returned ok with both scripted and agent filing usable; its visible browser window was closed. The earlier smoke check still reported optional CLI/PATH and demo-setting differences, so this commit is not a claim that every on-stage readiness check passed.
