"""Check the three LiveKit values in .env by asking LiveKit Cloud to list rooms (free, changes nothing).

Never prints the key or the secret.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, pathlib, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent

def read_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def main():
    env = read_env()
    url, key, secret = env.get("LIVEKIT_URL", ""), env.get("LIVEKIT_API_KEY", ""), env.get("LIVEKIT_API_SECRET", "")
    print("LiveKit check")
    missing = [n for n, v in (("LIVEKIT_URL", url), ("LIVEKIT_API_KEY", key), ("LIVEKIT_API_SECRET", secret)) if not v]
    if missing:
        print("MISSING in .env:", ", ".join(missing))
        return
    if any(c.isspace() for c in url + key + secret):
        print("PROBLEM: one of the three values contains a space or line break (the secret must be on ONE line).")
    if not url.startswith("wss://"):
        print("PROBLEM: LIVEKIT_URL must start with wss:// (it is the Websocket URL, not the dashboard web address).")
        return
    print("URL host:", url[6:])
    print("Key starts with:", key[:6] + "...", "| secret length:", len(secret))
    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"iss": key, "nbf": now - 10, "exp": now + 300, "video": {"roomList": True}}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    token = f"{header}.{payload}.{sig}"
    api = "https://" + url[6:].rstrip("/") + "/twirp/livekit.RoomService/ListRooms"
    req = urllib.request.Request(api, data=b"{}", method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "ghante72-keycheck/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(5000).decode("utf-8", "replace")
            print(f"status={r.status} ACCEPTED - URL, key and secret all match. Rooms now: {len(json.loads(body).get('rooms', []))}")
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", "replace").replace("\n", " ")
        verdict = "REJECTED - key and secret do not match each other (or belong to another project)" if e.code in (401, 403) else "UNCLEAR"
        print(f"status={e.code} {verdict} {body[:200]}")
    except Exception as e:
        print("NETWORK PROBLEM or wrong URL:", type(e).__name__, e)

if __name__ == "__main__":
    main()
