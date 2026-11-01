"""Print what the installed LiveKit packages actually offer, so the voice agent is written against the real API and not from memory.

    .venv-voice\\Scripts\\python.exe scripts\\spikes\\voice_introspect.py
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import inspect


def version(name: str) -> str:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return "NOT INSTALLED"


def sig(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError) as e:
        return f"(no signature: {e})"


def show(path: str, members: bool = False) -> None:
    module_name, _, attr = path.partition(":")
    try:
        obj = importlib.import_module(module_name)
        for part in attr.split(".") if attr else []:
            obj = getattr(obj, part)
    except Exception as e:  # noqa: BLE001 - we want to see every kind of failure
        print(f"MISSING {path}: {type(e).__name__}: {str(e)[:160]}")
        return
    if inspect.isclass(obj):
        print(f"class {path}{sig(obj.__init__)}")
        if members:
            for name, member in inspect.getmembers(obj):
                if name.startswith("_"):
                    continue
                if inspect.isfunction(member) or inspect.iscoroutinefunction(member):
                    print(f"    def {name}{sig(member)}")
                elif isinstance(member, property):
                    print(f"    property {name}")
    elif callable(obj):
        print(f"def {path}{sig(obj)}")
    elif inspect.ismodule(obj):
        names = [n for n in dir(obj) if not n.startswith("_")]
        print(f"module {path}: {', '.join(names)[:1500]}")
    else:
        print(f"{path} = {str(obj)[:200]}")


print("== versions ==")
for pkg in ("livekit-agents", "livekit", "livekit-api", "livekit-protocol", "livekit-plugins-deepgram", "livekit-plugins-sarvam",
            "livekit-plugins-silero", "livekit-plugins-groq", "livekit-plugins-openai", "livekit-plugins-google", "mcp", "onnxruntime", "numpy"):
    print(f"{pkg:28s} {version(pkg)}")

print("\n== agent framework ==")
show("livekit.agents")
for path in ("livekit.agents:AgentSession", "livekit.agents:Agent", "livekit.agents:JobContext", "livekit.agents:RoomInputOptions",
             "livekit.agents:RoomOutputOptions", "livekit.agents:WorkerOptions", "livekit.agents:AgentServer"):
    show(path, members=path.endswith(("AgentSession", "Agent", "JobContext", "AgentServer")))
for path in ("livekit.agents:cli.run_app", "livekit.agents:function_tool", "livekit.agents:llm.function_tool", "livekit.agents:RunContext",
             "livekit.agents:room_io", "livekit.agents:mcp", "livekit.agents:llm.mcp", "livekit.agents:inference"):
    show(path)

print("\n== speech interfaces (for the audio cache and the Piper adapter) ==")
for path in ("livekit.agents:tts.TTS", "livekit.agents:tts.ChunkedStream", "livekit.agents:tts.AudioEmitter", "livekit.agents:stt.STT",
             "livekit.agents:tts.FallbackAdapter", "livekit.agents:stt.FallbackAdapter", "livekit.agents:llm.FallbackAdapter",
             "livekit.agents:tts.StreamAdapter", "livekit.agents:stt.StreamAdapter"):
    show(path, members=path.endswith(("tts.TTS", "ChunkedStream", "AudioEmitter")))

print("\n== plugins ==")
for path in ("livekit.plugins.deepgram:STT", "livekit.plugins.deepgram:TTS", "livekit.plugins.sarvam:TTS", "livekit.plugins.sarvam:STT",
             "livekit.plugins.silero:VAD.load", "livekit.plugins.groq:LLM", "livekit.plugins.groq:STT", "livekit.plugins.openai:LLM",
             "livekit.plugins.openai:LLM.with_groq", "livekit.plugins.google:LLM"):
    show(path)

print("\n== rooms, tokens, dispatch ==")
for path in ("livekit.api:AccessToken", "livekit.api:VideoGrants", "livekit.api:RoomConfiguration", "livekit.api:RoomAgentDispatch",
             "livekit.api:CreateAgentDispatchRequest", "livekit.api:LiveKitAPI"):
    show(path, members=path.endswith("AccessToken"))

print("\n== session.say and friends ==")
for path in ("livekit.agents:AgentSession.say", "livekit.agents:AgentSession.generate_reply", "livekit.agents:AgentSession.start",
             "livekit.agents:AgentSession.interrupt", "livekit.agents:AgentSession.on", "livekit.agents:Agent.on_user_turn_completed",
             "livekit.agents:Agent.on_enter", "livekit.agents:Agent.llm_node", "livekit.agents:Agent.stt_node", "livekit.agents:Agent.tts_node",
             "livekit.agents:StopResponse", "livekit.agents:metrics", "livekit.agents:UserInputTranscribedEvent", "livekit.agents:MetricsCollectedEvent"):
    show(path)

try:
    from livekit.agents import AgentSession
    src = inspect.getsource(AgentSession.__init__)
    doc = inspect.getdoc(AgentSession.__init__) or ""
    print("\n== AgentSession.__init__ doc (first 60 lines) ==")
    print("\n".join(doc.splitlines()[:60]))
    print(f"(source {len(src.splitlines())} lines)")
except Exception as e:  # noqa: BLE001
    print(f"no AgentSession doc: {type(e).__name__}: {e}")
