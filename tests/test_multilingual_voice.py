"""LiveKit voice hook checks. Run with the project's voice environment."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock

try:
    from apps.voice.agent import IntakeAgent, build_stt, build_tts
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from apps.voice import speech
from tests.test_multilingual import brain


@unittest.skipUnless(AVAILABLE, 'LiveKit plugins require .venv-voice')
class VoiceHooks(unittest.IsolatedAsyncioTestCase):
    async def test_room_greeting_waits_for_audio_attachment(self):
        b, _ = brain('hi-IN')
        agent = IntakeAgent(b, ctx=SimpleNamespace(is_fake_job=lambda: False))
        session = SimpleNamespace(output=SimpleNamespace(audio=None))
        spoken = []
        with patch.object(IntakeAgent, 'session', new_callable=PropertyMock, return_value=session), patch.object(agent, 'speak', side_effect=spoken.append):
            task = asyncio.create_task(agent.on_enter())
            await asyncio.sleep(.04)
            self.assertFalse(spoken)
            session.output.audio = object()
            await asyncio.wait_for(task, 1)
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0].language, 'hi-IN')
    async def test_audio_attachment_timeout_is_bounded(self):
        from apps.voice.agent import wait_for_audio_output
        with self.assertRaises(TimeoutError):
            await wait_for_audio_output(SimpleNamespace(output=SimpleNamespace(audio=None)), .02)

    async def test_builders_use_multilingual_sarvam(self):
        import aiohttp
        async with aiohttp.ClientSession() as client:
            with patch.dict('os.environ', {'VOICE_MULTILINGUAL': '1'}):
                stt = build_stt()
            self.assertEqual((stt._opts.language, stt._opts.model, stt._opts.mode), ('unknown', 'saaras:v4', 'translate'))
            engine = build_tts(client, language='ta-IN')
            self.assertEqual(engine._opts.target_language_code, 'ta-IN')
            await stt.aclose()
            await engine.aclose()
    async def test_final_transcript_hook_retains_language(self):
        from livekit.agents import stt
        b, _ = brain()
        agent = IntakeAgent(b)
        async def events(*args):
            yield stt.SpeechEvent(type=stt.SpeechEventType.INTERIM_TRANSCRIPT, alternatives=[stt.SpeechData(language='hi-IN',text='old')])
            yield stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[stt.SpeechData(language='ta-IN',text='Please speak Tamil',confidence=.95)])
        async def audio():
            if False: yield None
        with patch('apps.voice.agent.Agent.default.stt_node', events):
            received = [event async for event in agent.stt_node(audio(), None)]
        self.assertEqual(len(received), 2)
        self.assertEqual(agent._source_language('Please speak Tamil'), ('ta-IN', .95))
        self.assertEqual(agent._source_language('old'), (None, 0))
    async def test_unrelated_transcripts_do_not_switch_language(self):
        agent = IntakeAgent(brain()[0])
        agent._transcripts.append(('An interrupted phrase', 'ml-IN', 1))
        self.assertEqual(agent._source_language('Yes'), (None, 0))
    async def test_tts_language_is_captured_before_next_turn(self):
        b, _ = brain('hi-IN')
        agent = IntakeAgent(b)
        agent._speech_languages.append(('नमस्ते।', 'hi-IN'))
        b.call.language = 'ta-IN'
        recorded = []
        async def frames(text, language=None):
            recorded.append((text,language))
            if False: yield None
        async def text(): yield 'नमस्ते।'
        with patch.object(agent, '_frames', frames):
            await anext(agent.tts_node(text(),None),None)
        self.assertEqual(recorded, [('नमस्ते।','hi-IN')])
    async def test_non_english_never_uses_english_piper(self):
        b, _ = brain('ta-IN')
        with tempfile.TemporaryDirectory() as folder:
            cache = speech.SpeechCache(root=Path(folder),language='ta-IN')
            agent = IntakeAgent(b,cache=cache)
            calls=[]
            async def sarvam(text,language='en-IN'):
                calls.append(language)
                yield b'\0' * 480, 24000, 1
            with patch.object(agent,'_sarvam',sarvam), patch('apps.voice.agent.credit_saver',return_value=True), patch('apps.voice.agent.piper_tts.available',side_effect=AssertionError('English Piper queried')):
                frames = [frame async for frame in agent._frames('வணக்கம்.', 'ta-IN')]
            self.assertTrue(frames)
            self.assertEqual(calls,['ta-IN'])
            self.assertTrue(cache.has('வணக்கம்.'))


if __name__ == '__main__': unittest.main()
