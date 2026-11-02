"""Multilingual call safety, language selection, and speech isolation. No provider spend."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.voice import languages, lines, speech, prompts
from apps.voice.brain import CallBrain


class FakeServices:
    def __init__(self):
        self.events = []
        self.saved = {}
        self.questions = []
    def emit(self, kind, data): self.events.append((kind, data))
    async def warm(self): pass
    async def save_slots(self, slots): self.saved.update(slots)
    async def set_status(self, *args): pass
    async def route(self, question, expected, utterance):
        self.questions.append(question)
        return {'intent': 'yes' if utterance.lower().startswith('yes') else 'no' if utterance.lower() == 'no' else 'detail', 'confidence': 1}
    async def extract(self, *, step, **kwargs):
        slots = {'CAUSE': {'cause_text': 'Hail fell', 'peril': 'hailstorm'},
                 'TIME': {'loss_time': '15:30'}, 'EXTENT': {'damage_pct': 70}, 'STAGE': {'crop_stage': 'standing'}}.get(step, {})
        return {'data': {'slots': slots, 'answer': ''}}
    async def peril(self, *args): return {'value': 'hailstorm', 'confidence': 1}
    async def run_pipeline(self): return {'status': 'FILED', 'claim_ref': 'FCS-000123'}


def brain(language='hi-IN'):
    call = lines.CallContext(case_id='test', name_en='Ramlal', village_en='Bhaypur', crop_en='wheat', khasra='47',
                             storm_started_at='2026-03-12T15:30:00+05:30', language=language)
    services = FakeServices()
    return CallBrain(call, services), services


class LanguageSelection(unittest.TestCase):
    def test_state_defaults(self):
        for state, district, expected in [('Madhya Pradesh', 'Sehore', 'hi-IN'), ('Kerala', '', 'ml-IN'), ('Tamil Nadu', '', 'ta-IN'), ('Punjab', '', 'en-IN')]:
            self.assertEqual(languages.initial(state, district), expected)
    def test_registry_context_uses_state(self):
        with patch.dict('os.environ', {'VOICE_MULTILINGUAL': '1', 'VOICE_DEFAULT_LANGUAGE': ''}):
            call = lines.CallContext.from_case({'id': 'test', 'village': {'state': 'Madhya Pradesh', 'district': 'Sehore'}})
        self.assertEqual(call.language, 'hi-IN')
    def test_native_scripts(self):
        for text, lang in [('मुझे समझ नहीं आया', 'hi-IN'), ('എനിക്ക് മനസ്സിലായില്ല', 'ml-IN'), ('எனக்கு புரியவில்லை', 'ta-IN')]:
            self.assertEqual(languages.choose(text, 'en-IN'), lang)
    def test_explicit_request_overrides_source(self):
        for text, language in [("I don't understand Hindi, please speak English", 'en-IN'), ('Please talk in Malayalam', 'ml-IN'), ('Speak Tamil please', 'ta-IN'), ('Please speak Hindi', 'hi-IN')]:
            self.assertEqual(languages.choose(text, 'hi-IN', 'hi-IN'), language)
    def test_negative_language_not_selected(self):
        self.assertIsNone(languages.requested("I don't understand Hindi"))
        self.assertEqual(languages.requested("I don't know Tamil, speak Malayalam"), 'ml-IN')
    def test_neutral_and_uncertain_speech_stays(self):
        self.assertEqual(languages.choose('Yes', 'ta-IN', 'en-IN'), 'ta-IN')
        self.assertEqual(languages.choose('Some words', 'hi-IN', 'ta-IN', .2), 'hi-IN')
        self.assertEqual(languages.choose('Some words', 'hi-IN', 'bn-IN'), 'hi-IN')
    def test_every_scripted_line_translated_and_placeholders_match(self):
        from string import Formatter
        fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name}
        for language, translations in languages.TRANSLATIONS.items():
            self.assertEqual(set(translations), set(lines.LINES))
            for key in lines.LINES:
                self.assertEqual(fields(translations[key]), fields(lines.LINES[key]), (language, key))
                self.assertTrue(lines.render(key, brain(language)[0].call))
    def test_language_in_extraction_prompt(self):
        for language, name in languages.SUPPORTED.items():
            self.assertIn('must be in ' + name, prompts.extract_system(brain(language)[0].call))
    def test_cache_language_isolation_and_english_compatibility(self):
        caches = [speech.SpeechCache(language=lang) for lang in languages.SUPPORTED]
        self.assertEqual(len({cache.path('47') for cache in caches}), 4)
        self.assertEqual(speech.SpeechCache().path('47'), speech.SpeechCache(language='en-IN').path('47'))
    def test_hindi_sentence_boundaries(self):
        self.assertEqual(speech.split_segments('नमस्ते। कृपया बोलें।'), ['नमस्ते।', 'कृपया बोलें।'])


class CallSwitching(unittest.IsolatedAsyncioTestCase):
    async def test_preference_repeats_without_identity_or_retry(self):
        b, s = brain()
        await b.open()
        before = dict(b.flow.asked)
        for language in languages.SUPPORTED:
            reply = await b.farmer_turn('Please speak ' + languages.SUPPORTED[language], detected_language='hi-IN')
            self.assertEqual((reply.language, reply.rule, b.flow.step), (language, 'language_repeat', 'GREET'))
            self.assertIsNone(b.flow.slots['identity_confirmed'])
            self.assertEqual(before, b.flow.asked)
        self.assertFalse(s.questions)
    async def test_complete_claim_in_each_language(self):
        for language in languages.SUPPORTED:
            b, s = brain()
            await b.open()
            await b.farmer_turn('Please speak ' + languages.SUPPORTED[language])
            for text in ('Yes', 'Yes', 'Yes', 'Hail fell', 'Half past three in the afternoon', 'Seventy percent', 'The crop was standing'):
                reply = await b.farmer_turn(text, detected_language=language)
                self.assertEqual(reply.language, language)
            self.assertEqual(b.flow.step, 'PHOTO')
            await b.photo_timeout()
            self.assertEqual(b.flow.step, 'CONSENT')
            before = dict(b.flow.slots)
            reply = await b.farmer_turn("I don't understand, please repeat", detected_language=language)
            self.assertEqual(reply.rule, 'language_repeat')
            self.assertEqual(before, b.flow.slots)
            self.assertIsNone(b.flow.slots['consent'])
            reply = await b.farmer_turn('Yes', detected_language=language)
            self.assertTrue(reply.run_pipeline)
            await b.flush()
            self.assertEqual((s.saved['peril'], s.saved['damage_pct'], s.saved['crop_stage'], s.saved['consent']), ('hailstorm', 70, 'standing', True))
            self.assertEqual(s.saved['loss_datetime'], '2026-03-12T15:30:00+05:30')
            self.assertTrue(all(languages.script_language(q) is None for q in s.questions))
    async def test_automatic_switch_keeps_claim_progress(self):
        b, _ = brain()
        await b.open()
        reply = await b.farmer_turn('Yes, I am Ramlal', detected_language='ml-IN')
        self.assertEqual((reply.language, b.flow.step), ('ml-IN', 'EVENT'))
        reply = await b.farmer_turn('Yes, my crop is damaged', detected_language='ta-IN')
        self.assertEqual((reply.language, b.flow.step), ('ta-IN', 'KHASRA'))
    async def test_wrong_language_llm_answer_uses_localized_fallback(self):
        from apps.voice.services import Services
        b, _ = brain('ta-IN')
        services = Services(b.call)
        out = {'data': {'slots': {}, 'answer': 'A colleague will explain.'}, 'failed': [], 'provider': 'test'}
        with patch('apps.voice.services.extract_mod.extract_sync', return_value=out), patch.object(services, 'emit') as emit:
            result = await services.extract(step='CAUSE', question='What caused the loss?', utterance='What happens next?', known={})
        self.assertEqual(result['data']['answer'], languages.ANSWER_FALLBACK['ta-IN'])
        self.assertEqual(emit.call_args.args[0], 'fallback.used')

    async def test_no_consent_never_files(self):
        b, _ = brain('ta-IN')
        await b.open()
        b.flow.step = 'CONSENT'
        reply = await b.farmer_turn('No', detected_language='ta-IN')
        self.assertFalse(reply.run_pipeline)
        self.assertEqual(reply.end, 'escalated')


if __name__ == '__main__':
    unittest.main()
