r"""Intake agent: the English call with the farmer (SystemDesign §10). Written against LiveKit Agents 1.8.5.

This file is the thin LiveKit layer. What to say and what to store is decided in brain.py and flow.py, which have no audio in
them and are tested as text. Here: join the room, turn each finished farmer turn into a Reply, speak it through the audio
cache, report every turn to the dashboard, react to the photo message from the phone, and hang up at the end.

Run from the project root with the voice environment:
    .venv-voice\Scripts\python.exe -m apps.voice.agent console     talk to it with this computer's microphone and speakers
    .venv-voice\Scripts\python.exe -m apps.voice.agent dev         wait for calls placed from the dashboard
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable

from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, stt
# LiveKit plugins must be imported here, on the main thread: importing one inside a call (a worker thread) fails with
# "Plugins must be registered on the main thread".
from livekit.plugins import deepgram, groq, sarvam

from ghante_shared import config, http, mcp_client, usage

from . import lines, piper_tts, prompts, speech, languages
from .brain import CallBrain, Reply
from .services import Services

log = logging.getLogger("intake")
for _noisy in ("httpcore", "httpcore2", "httpx", "httpx2", "asyncio", "mcp"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def call_log_file() -> None:
    """Write what was heard and said to var/logs/voice-calls.log, so a spoken test can be read afterwards."""
    if any(getattr(h, "_ghante", False) for h in log.handlers):
        return
    with contextlib.suppress(Exception):
        folder = config.ROOT / "var" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(folder / "voice-calls.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        handler._ghante = True
        log.addHandler(handler)
        log.setLevel(logging.INFO)
AGENT_NAME = "intake"
HERO_FARMER_ID = config.env("HERO_FARMER_ID", "F0001")
PHOTO_TIMEOUT_S = config.env_float("PHOTO_TIMEOUT_S", 60.0)
TTS_MODEL = "bulbul:v3"


# ---------- the case ----------
def job_metadata(ctx: JobContext) -> dict:
    """The orchestrator dispatches the agent with {"case_id", "call_id"} as job metadata (set in the farmer's room token)."""
    try:
        meta = json.loads(ctx.job.metadata or "{}")
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001 - a console job has no metadata
        return {}


async def load_call(case_id: str | None) -> lines.CallContext:
    """Read the case through the registry MCP server (shown in the dashboard's tool-call log). With no case id, use the hero's case."""
    if not case_id:
        try:
            opened = await asyncio.to_thread(http.post_json, f"{config.ORCH_URL}/api/cases", {"farmer_id": HERO_FARMER_ID}, 5.0)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"the orchestrator is not reachable at {config.ORCH_URL} ({type(e).__name__}); start it with scripts/dev.py") from None
        case_id = opened["id"]
    case = await mcp_client.call_tool(config.MCP_REGISTRY_URL, "get_case", {"case_id": case_id}, server="registry", client="intake", case_id=case_id)
    if not case or case.get("error") or "id" not in case:
        raise RuntimeError(f"registry MCP could not return case {case_id}: {case.get('error') if case else 'empty answer'}")
    call = lines.CallContext.from_case(case)
    if call.plot_lat is not None and call.storm_started_at:
        # Confirm the recorded event at the farmer's plot before saying it on the phone. A failure here does not stop the call.
        with contextlib.suppress(Exception):
            await mcp_client.call_tool(config.MCP_WEATHER_URL, "get_weather_at", {"lat": call.plot_lat, "lon": call.plot_lon, "at": call.storm_started_at},
                                       server="weather", client="intake", case_id=case_id)
    return call


async def place_console_call() -> dict:
    """Console mode has no dashboard and no phone, so ring and answer the hero's call here. The case then moves through its
    statuses exactly as in a real call."""
    try:
        ring = await asyncio.to_thread(http.post_json, f"{config.ORCH_URL}/api/hero/call", {}, 5.0)
        await asyncio.to_thread(http.post_json, f"{config.ORCH_URL}/api/calls/{ring['call_id']}/accept", {}, 5.0)
        return {"case_id": ring["case_id"], "call_id": ring["call_id"]}
    except Exception as e:  # noqa: BLE001
        log.warning("could not place the console call through the orchestrator (%s); talking without a call record", type(e).__name__)
        return {}


# ---------- speech and language models ----------
def voice_name() -> str:
    return (config.env("TTS_VOICE", "simran") or "simran").lower()


def build_llm():
    """LiveKit needs an LLM object for the reply pipeline to run. Our turns are answered in IntakeAgent.llm_node; this model
    only speaks if that path cannot be used."""
    first = (config.env("LLM_CHAIN", "") or "groq:openai/gpt-oss-20b").split(",")[0].strip()
    provider, _, model = first.partition(":")
    return groq.LLM(model=(model if provider == "groq" and model else "openai/gpt-oss-20b"), temperature=0.3)


def build_stt():
    provider = config.env("STT_PROVIDER", "deepgram") or "deepgram"
    if config.env("VOICE_MULTILINGUAL", "1") != "0" or provider == "sarvam":
        return sarvam.STT(language="unknown", model="saaras:v4", mode="translate")
    return deepgram.STT(model="nova-3", language="en-IN")


def build_tts(http_session=None, *, language: str = "en-IN"):
    return sarvam.TTS(target_language_code=language, model=TTS_MODEL, speaker=voice_name(), http_session=http_session)


def build_cache(language: str = "en-IN") -> speech.SpeechCache:
    return speech.SpeechCache(provider="sarvam", model=TTS_MODEL, voice=voice_name(), language=language)


def piper_cache() -> speech.SpeechCache:
    return speech.SpeechCache(provider="piper", model="piper", voice=piper_tts.VOICE)


def credit_saver() -> bool:
    return config.env("CREDIT_SAVER", "1") != "0"


# ---------- the agent ----------
async def wait_for_audio_output(session, timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while session.output.audio is None:
            await asyncio.sleep(0.02)


class IntakeAgent(Agent):
    def __init__(self, brain: CallBrain, *, cache: speech.SpeechCache | None = None, call_id: str | None = None, ctx: JobContext | None = None,
                 synth: Callable[[str], AsyncIterator[tuple[bytes, int, int]]] | None = None) -> None:
        super().__init__(instructions=prompts.instructions(brain.call))
        self.brain = brain
        self.call = brain.call
        self.cache = cache or build_cache(brain.call.language)          # the demo voice (Sarvam); built ahead by scripts/build_tts_cache.py
        self.local_cache = piper_cache()             # sentences spoken by the local voice
        self.call_id = call_id
        self.ctx = ctx
        self._synth = synth                      # tests inject a fake; otherwise the session's speech engine is used
        self._transcripts: list[tuple[str, str, float]] = []
        self._speech_languages: list[tuple[str, str]] = []
        self._pending: list[Reply] = []          # replies handed to speech and not yet reported as call.turn
        self._turn: dict = {}                    # timing of the farmer turn being answered
        self._photo_timer: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self.finished: str | None = None
        self.stats = {"cache_hits": 0, "live_segments": 0, "live_chars": 0}

    # ----- helpers -----
    def _task(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _after(self, reply: Reply) -> None:
        """What follows from a reply besides speaking it."""
        if reply.run_pipeline:
            self._task(self._file())
        if self.brain.waiting_for_photo:
            if self._photo_timer is None or self._photo_timer.done():
                self._photo_timer = self._task(self._photo_wait())
        elif self._photo_timer is not None:
            self._photo_timer.cancel()
            self._photo_timer = None
        if reply.end:
            self._task(self._finish_after_speech(reply))

    def speak(self, reply: Reply) -> None:
        """Say something that is not the answer to a farmer turn (the greeting, the reaction to the photo, the reference)."""
        log.info("SAY   [%s -> step %s] %s", reply.rule, self.brain.flow.step, reply.text)
        if reply.text:
            self._pending.append(reply)
            self._speech_languages.append((reply.text, reply.language))
            # The read-back before consent is played to the end: the farmer must hear every detail before saying yes, and
            # nothing said while it plays is taken as the answer.
            whole = self.brain.flow.step == "CONSENT"
            self.session.say(reply.text, allow_interruptions=False) if whole else self.session.say(reply.text)
        self._after(reply)

    # ----- LiveKit hooks -----
    async def on_enter(self) -> None:
        # RoomIO attaches audio asynchronously during session.start. A greeting sent before attachment is treated
        # as text-only by LiveKit and never reaches tts_node. Wait for the public output, not a fixed delay.
        if self.ctx is not None and not self.ctx.is_fake_job():
            try:
                await wait_for_audio_output(self.session)
            except TimeoutError:
                self.brain.services.fallback("audio", "room startup", "human follow-up", "audio output did not attach")
                await self.finish("dropped")
                return
        self.speak(await self.brain.open())

    async def stt_node(self, audio, model_settings):
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
                value = event.alternatives[0]
                self._transcripts.append((value.text.strip(), value.language, value.confidence))
                self._transcripts = self._transcripts[-16:]
            yield event

    def _source_language(self, utterance: str) -> tuple[str | None, float]:
        # Match only transcripts belonging to this turn; discarded/interrupted audio must not change another turn.
        matches = [(lang, confidence) for text, lang, confidence in self._transcripts if text and text in utterance]
        self._transcripts.clear()
        return matches[-1] if matches else (None, 0.0)

    async def llm_node(self, chat_ctx, tools, model_settings) -> AsyncIterator[str]:
        """One farmer turn has ended. The brain decides the reply; a scripted reply costs no LLM call."""
        utterance = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                utterance = (getattr(item, "text_content", None) or "").strip()
                break
        self._turn = {"t0": time.perf_counter(), "first_audio": None}
        step = self.brain.flow.step
        log.info("HEARD [step %s] %s", step, utterance or "(nothing)")
        source, confidence = self._source_language(utterance)
        reply = await self.brain.farmer_turn(utterance, detected_language=source, language_confidence=confidence)
        log.info("REPLY [%s, %s -> step %s, %s] %s", reply.rule, reply.path, self.brain.flow.step, reply.latency_ms, reply.text or "(silent)")
        self._pending.append(reply)
        self._speech_languages.append((reply.text, reply.language))
        self._after(reply)
        if reply.text:
            yield reply.text

    async def tts_node(self, text: AsyncIterable[str], model_settings) -> AsyncIterator[rtc.AudioFrame]:
        """Every word the agent says goes through here: sentence by sentence, from the cache when it is there."""
        buffer = ""
        language = None
        async for chunk in text:
            if language is None:
                for index, (message, candidate) in enumerate(self._speech_languages):
                    if message.startswith(chunk[:12]) or chunk.startswith(message[:12]):
                        language = candidate
                        del self._speech_languages[:index + 1]
                        break
                language = language or self.brain.call.language
            buffer += chunk
            done, buffer = speech.take_complete(buffer)
            for segment in done:
                async for frame in self._frames(segment, language):
                    yield frame
        for segment in speech.split_segments(buffer):
            async for frame in self._frames(segment, language):
                yield frame

    async def _frames(self, segment: str, language: str | None = None) -> AsyncIterator[rtc.AudioFrame]:
        language = language or self.brain.call.language
        cache = self.cache if self.cache.language == language else build_cache(language)
        hit = cache.load(segment) or (self.local_cache.load(segment) if self._synth is None and language == "en-IN" else None)
        if hit is not None:
            pcm, rate, channels = hit
            self.stats["cache_hits"] += 1
            usage.add("tts_cache", "segments_played")
            for piece in speech.chunks(pcm, rate, channels):
                self._mark_audio()
                yield rtc.AudioFrame(data=piece, sample_rate=rate, num_channels=channels, samples_per_channel=len(piece) // (2 * channels))
            return
        # Not cached: prefer local English with CREDIT_SAVER=1; other languages use Sarvam signup credits.
        if self._synth is not None:
            engines = [("test", cache, self._synth)]
        else:
            engines = [] if credit_saver() and language == "en-IN" else [("sarvam", cache, lambda segment: self._sarvam(segment, language))]
            if language == "en-IN" and piper_tts.available()[0]:
                engines.append(("piper", self.local_cache, self._piper))
            if not engines:  # no local voice installed: better to spend a little credit than to stay silent
                engines = [("sarvam", cache, lambda segment: self._sarvam(segment, language))]
        for position, (name, cache, engine) in enumerate(engines):
            collected, rate, channels, complete, started = bytearray(), 0, 1, False, False
            try:
                async for pcm, rate, channels in engine(segment):
                    collected.extend(pcm)
                    started = True
                    self._mark_audio()
                    yield rtc.AudioFrame(data=bytes(pcm), sample_rate=rate, num_channels=channels, samples_per_channel=len(pcm) // (2 * channels))
                complete = True
            except Exception as e:  # noqa: BLE001 - try the next voice unless part of the sentence was already heard
                if started or position == len(engines) - 1:
                    log.warning("speech failed on %s: %s", name, type(e).__name__)
                    self.brain.services.fallback("tts", name, "human follow-up", type(e).__name__)
                    if self.brain.flow.step != "END":
                        self._task(self.brain.services.set_status("ESCALATED", "speech unavailable in the selected language"))
                    self._task(self.finish("escalated"))
                    return
                self.brain.services.fallback("tts", name, engines[position + 1][0], f"{type(e).__name__}: {str(e)[:80]}")
                continue
            finally:
                if started:
                    self.stats["live_segments"] += 1
                    self.stats["live_chars"] += len(segment)
                    usage.add(name, "tts_chars", len(segment))
                if complete and collected and rate:  # an interrupted sentence is not kept: it would be cut short forever
                    cache.save(segment, bytes(collected), rate, channels)
            return

    async def _sarvam(self, segment: str, language: str = "en-IN") -> AsyncIterator[tuple[bytes, int, int]]:
        engine = self.session.tts
        if engine is None:
            raise RuntimeError("no speech engine in the session")
        engine.update_options(target_language_code=language)
        async with engine.synthesize(segment) as stream:
            async for ev in stream:
                frame = ev.frame
                yield bytes(frame.data), frame.sample_rate, frame.num_channels

    async def _piper(self, segment: str) -> AsyncIterator[tuple[bytes, int, int]]:
        pcm, rate = await asyncio.to_thread(piper_tts.synth, segment)
        for piece in speech.chunks(pcm, rate, 1):
            yield piece, rate, 1

    def _mark_audio(self) -> None:
        if self._turn and self._turn.get("first_audio") is None:
            self._turn["first_audio"] = time.perf_counter()

    # ----- things that happen besides farmer turns -----
    async def on_evidence(self, payload: dict) -> None:
        """The phone uploaded a photo and told us on the room's data channel (SystemDesign §10.5)."""
        label = payload.get("edge_label")
        confidence = payload.get("edge_confidence")
        self.speak(await self.brain.evidence(label, confidence if isinstance(confidence, (int, float)) else None, payload.get("evidence_id")))

    async def _photo_wait(self) -> None:
        await asyncio.sleep(PHOTO_TIMEOUT_S)
        if self.brain.waiting_for_photo:
            self._photo_timer = None
            log.info("no photo after %.0f s: going on without it", PHOTO_TIMEOUT_S)
            self.speak(await self.brain.photo_timeout())

    async def _file(self) -> None:
        self.speak(await self.brain.pipeline())

    def on_item(self, ev) -> None:
        """A finished turn has been added to the conversation: report the agent's turns to the dashboard as call.turn."""
        item = getattr(ev, "item", None)
        if getattr(item, "role", None) != "assistant":
            return  # the farmer's turns are reported by the brain, with the path that handled them
        text = (getattr(item, "text_content", None) or "").strip()
        if not text:
            return
        reply = None
        for i, candidate in enumerate(self._pending):
            if candidate.text.startswith(text[:12]) or text.startswith(candidate.text[:12]):
                reply = candidate
                del self._pending[:i + 1]
                break
        if reply is None and self._pending:
            reply = self._pending.pop(0)
        latency = dict(reply.latency_ms) if reply else {}
        turn = self._turn
        if reply is not None and reply.path != "scripted":
            # LiveKit 1.8 attaches the turn's timings to the message (seconds): time to first text, to first audio, and end to end.
            measured = getattr(item, "metrics", None) or {}
            for ours, theirs in (("llm_ttft", "llm_node_ttft"), ("tts_ttfb", "tts_node_ttfb"), ("total", "e2e_latency")):
                value = measured.get(theirs)
                if isinstance(value, (int, float)):
                    latency[ours] = round(value * 1000)
            if "total" not in latency:
                if turn and turn.get("first_audio") is not None:
                    latency["total"] = round((turn["first_audio"] - turn["t0"]) * 1000)
                else:
                    latency["total"] = latency.get("brain", 0)  # text mode: thinking time only, no audio
            self._turn = {}
        self.brain.services.emit("call.turn", {"speaker": "agent", "text": text,
                                               "path": reply.path if reply else "llm", "rule": reply.rule if reply else "", "latency_ms": latency,
                                               "language": reply.language if reply else self.brain.call.language})
        if reply is not None:
            reply.spoken = True

    async def _finish_after_speech(self, reply: Reply) -> None:
        """Hang up once the closing line has been spoken (or after a generous wait if speech was cut off)."""
        deadline = time.perf_counter() + 6.0 + len(reply.text) / 9.0
        while time.perf_counter() < deadline and not reply.spoken:
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.4)
        await self.finish(reply.end or "completed")

    async def finish(self, outcome: str) -> None:
        if self.finished:
            return
        self.finished = outcome
        if self._photo_timer is not None:
            self._photo_timer.cancel()
        await self.brain.flush()
        await self.brain.services.end_call(self.call_id, outcome)
        log.info("call %s ended: %s; speech from cache %s, live %s (%s characters)", self.call_id, outcome, self.stats["cache_hits"],
                 self.stats["live_segments"], self.stats["live_chars"])
        ctx = self.ctx
        if ctx is None:
            return
        with contextlib.suppress(Exception):
            if not ctx.is_fake_job():
                await ctx.delete_room()  # disconnects the phone, which returns the app to its idle screen
        with contextlib.suppress(Exception):
            ctx.shutdown("call ended")
        with contextlib.suppress(Exception):
            if ctx.is_fake_job():  # the microphone test: there is no phone to hang up, so stop the program instead of listening on
                print("\n\n  THE CALL HAS ENDED (%s).\n" % outcome, flush=True)
                await asyncio.sleep(1.0)
                logging.shutdown()
                os._exit(0)


def attach(session: AgentSession, agent: IntakeAgent) -> None:
    session.on("conversation_item_added", agent.on_item)

    def on_close(_ev=None) -> None:
        if not agent.finished:  # the farmer hung up, or the connection was lost
            agent._task(agent.finish("dropped"))

    session.on("close", on_close)


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    call_log_file()
    meta = job_metadata(ctx)
    if not meta.get("case_id") and not os.environ.get("VOICE_CASE_ID"):
        meta = await place_console_call()
    call = await load_call(meta.get("case_id") or os.environ.get("VOICE_CASE_ID") or None)
    log.info("call for case %s, farmer %s, village %s", call.case_id, call.name_en, call.village_en)
    brain = CallBrain(call, Services(call), short=config.env("HERO_FLOW", "full") == "short", fast_min=config.env_float("FAST_PATH_MIN", 0.5))
    session: AgentSession = AgentSession(
        stt=build_stt(), llm=build_llm(), tts=build_tts(language=call.language),
        # No early replies on half-heard sentences: every reply here changes the call record, so it must be made once, from
        # the finished sentence. (LiveKit's default starts the reply on a preliminary transcript and redoes it.)
        turn_handling={"preemptive_generation": {"enabled": False}})
    agent = IntakeAgent(brain, call_id=meta.get("call_id"), ctx=ctx)
    attach(session, agent)

    def on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != "evidence":
            return
        try:
            payload = json.loads(bytes(packet.data).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(payload, dict):
            agent._task(agent.on_evidence(payload))

    ctx.room.on("data_received", on_data)
    await session.start(agent=agent, room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
