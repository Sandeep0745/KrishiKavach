"""Synthetic Sarvam audio round-trip for four languages. Uses signup credits, never a farmer call.

Run with .venv-voice/Scripts/python.exe scripts/multilingual_live_check.py.
Audio and results stay under ignored logs/multilingual/. Human microphone/phone testing is separate.
"""
from __future__ import annotations
import asyncio
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ghante_shared import config, usage
from apps.voice import languages, speech

SAMPLES = {
    'hi-IN': 'मुझे हिंदी में बात करनी है। ओले गिरने से मेरी गेहूँ की फसल का सत्तर प्रतिशत हिस्सा खराब हो गया है।',
    'en-IN': 'I do not understand Hindi. Please speak English. Hail damaged seventy percent of my wheat crop.',
    'ml-IN': 'എനിക്ക് ഹിന്ദി മനസ്സിലാകുന്നില്ല. മലയാളത്തിൽ സംസാരിക്കൂ. ആലിപ്പഴമഴയിൽ എന്റെ ഗോതമ്പ് വിളയുടെ എഴുപത് ശതമാനം നശിച്ചു.',
    'ta-IN': 'எனக்கு இந்தி புரியவில்லை. தமிழில் பேசுங்கள். ஆலங்கட்டி மழையால் என் கோதுமை பயிரில் எழுபது சதவீதம் சேதமடைந்தது.',
}


async def main():
    import aiohttp
    from livekit import rtc
    from livekit.agents import stt
    from livekit.plugins import sarvam
    destination = config.LOG_DIR / 'multilingual'
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    async with aiohttp.ClientSession() as client:
        tts = sarvam.TTS(model='bulbul:v3', speaker=config.env('TTS_VOICE', 'simran'), http_session=client, target_language_code='hi-IN')
        for language, text in SAMPLES.items():
            try:
                cache = speech.SpeechCache(root=destination / 'synthetic-input', language=language)
                hit = cache.load(text)
                if hit is None:
                    tts.update_options(target_language_code=language)
                    pcm, rate, channels = bytearray(), 0, 1
                    async with tts.synthesize(text) as stream:
                        async for event in stream:
                            pcm.extend(bytes(event.frame.data))
                            rate, channels = event.frame.sample_rate, event.frame.num_channels
                    if not pcm or not rate:
                        raise RuntimeError('TTS returned no audio')
                    cache.save(text, bytes(pcm), rate, channels)
                    usage.add('sarvam', 'tts_chars', len(text))
                else:
                    pcm, rate, channels = hit
                recognizer = sarvam.STT(model='saaras:v4', language='unknown', mode='translate', http_session=client)
                finals = []
                async with recognizer.stream() as stream:
                    async def feed():
                        for chunk in speech.chunks(bytes(pcm), rate, channels):
                            stream.push_frame(rtc.AudioFrame(data=chunk, sample_rate=rate, num_channels=channels, samples_per_channel=len(chunk)//(2*channels)))
                            await asyncio.sleep(.1)
                        # Give VAD an unambiguous end of speech before closing the socket.
                        for _ in range(20):
                            stream.push_frame(rtc.AudioFrame(data=b'\0' * (rate//10*2), sample_rate=rate, num_channels=1, samples_per_channel=rate//10))
                            await asyncio.sleep(.1)
                        stream.end_input()
                    task = asyncio.create_task(feed())
                    try:
                        async with asyncio.timeout(50):
                            async for event in stream:
                                if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                                    finals.extend(event.alternatives)
                                    break  # continuous sockets do not finish just because input ended
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                await recognizer.aclose()
                usage.add('sarvam', 'stt_seconds', round(speech.duration_s(bytes(pcm), rate, channels), 2))
                transcript = ' '.join(item.text for item in finals)
                source = finals[-1].language if finals else ''
                confidence = finals[-1].confidence if finals else 0
                selected = languages.choose(transcript, 'hi-IN', source, confidence)
                ok = bool(transcript) and languages.code(source) == language and selected == language
                results.append({'language': language, 'detected': source, 'confidence': confidence, 'translation': transcript, 'selected': selected,
                                'audio_seconds': round(speech.duration_s(bytes(pcm),rate,channels),2), 'pass': ok})
                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            except Exception as exc:
                results.append({'language': language, 'pass': False, 'error': type(exc).__name__})
                print(json.dumps(results[-1]), flush=True)
        await tts.aclose()
    (destination / 'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    import gc
    await asyncio.sleep(0)
    gc.collect()
    return 0 if len(results) == 4 and all(item['pass'] for item in results) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
