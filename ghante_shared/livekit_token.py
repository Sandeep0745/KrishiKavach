"""A LiveKit room token made with the standard library (HS256 JWT), so the orchestrator needs no LiveKit package.

The claims follow livekit-api's AccessToken.to_jwt: sub, iss, nbf, exp, name, video grants, and roomConfig.agents, which makes
LiveKit dispatch the named agent into the room when the participant joins. scripts/voice_text_check.py verifies a token made
here with livekit-api's own TokenVerifier.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(api_key: str, api_secret: str, *, identity: str, room: str, name: str = "", agent_name: str | None = None,
               agent_metadata: dict | None = None, ttl_s: int = 3600, now: float | None = None) -> str:
    if not api_key or not api_secret:
        raise ValueError("LiveKit API key and secret are required")
    if not identity or not room:
        raise ValueError("identity and room are required")
    now = int(now if now is not None else time.time())
    claims: dict = {
        "video": {"roomJoin": True, "room": room, "canPublish": True, "canSubscribe": True, "canPublishData": True},
        "sub": identity, "iss": api_key, "nbf": now - 10, "exp": now + int(ttl_s),
    }
    if name:
        claims["name"] = name
    if agent_name:
        claims["roomConfig"] = {"agents": [{"agentName": agent_name, "metadata": json.dumps(agent_metadata or {}, ensure_ascii=False)}]}
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))}"
    signature = hmac.new(api_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def decode_unverified(token: str) -> dict:
    """The claims of a token, without checking the signature. For tests and logs only."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def verify(token: str, api_secret: str) -> bool:
    signing_input, _, signature = token.rpartition(".")
    expected = _b64(hmac.new(api_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest())
    return hmac.compare_digest(signature, expected)
