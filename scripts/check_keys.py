"""Check that each key in .env is accepted by its provider (no credit is used).

Prints provider, HTTP status and a verdict. Never prints a key.
"""
from __future__ import annotations
import json, pathlib, sys, urllib.request, urllib.error, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "ghante72-keycheck/0.1"

def read_env():
    env = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env

def call(url, headers, data=None, method=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers}, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:  # network problem
        return None, f"{type(e).__name__}: {e}"

def main():
    env = read_env()
    print("72 Ghante key check -", datetime.datetime.now().isoformat(timespec="seconds"))
    print()

    def line(name, status, verdict, extra=""):
        print(f"{name:<10} status={status!s:<5} {verdict} {extra}")

    k = env.get("DEEPGRAM_API_KEY")
    if k:
        st, body = call("https://api.deepgram.com/v1/projects", {"Authorization": f"Token {k}"})
        line("Deepgram", st, "ACCEPTED" if st == 200 else ("REJECTED" if st in (401, 403) else "UNCLEAR"), "" if st == 200 else body[:160].replace("\n", " "))
        if st == 200:
            try:
                pid = json.loads(body)["projects"][0]["project_id"]
                st2, b2 = call(f"https://api.deepgram.com/v1/projects/{pid}/balances", {"Authorization": f"Token {k}"})
                if st2 == 200:
                    for b in json.loads(b2).get("balances", []):
                        print(f"           balance: {b.get('amount')} {b.get('units')}")
            except Exception as e:
                print("           (balance not read:", type(e).__name__, ")")
    else:
        line("Deepgram", "-", "NO KEY")

    k = env.get("GROQ_API_KEY")
    if k:
        st, body = call("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {k}"})
        line("Groq", st, "ACCEPTED" if st == 200 else ("REJECTED" if st in (401, 403) else "UNCLEAR"), "" if st == 200 else body[:160].replace("\n", " "))
        if st == 200:
            ids = sorted(m["id"] for m in json.loads(body).get("data", []))
            print("           models:", ", ".join(ids))
    else:
        line("Groq", "-", "NO KEY")

    k = env.get("GEMINI_API_KEY")
    if k:
        st, body = call("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": k})
        line("Gemini", st, "ACCEPTED" if st == 200 else ("REJECTED" if st in (400, 401, 403) else "UNCLEAR"), "" if st == 200 else body[:200].replace("\n", " "))
        if st == 200:
            ids = sorted(m["name"].split("/")[-1] for m in json.loads(body).get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []))
            print("           flash models:", ", ".join(i for i in ids if "flash" in i))
    else:
        line("Gemini", "-", "NO KEY")

    k = env.get("SARVAM_API_KEY")
    if k:
        # Deliberately empty request: a valid key gives a validation error (400/422), a bad key gives 401/403. Costs nothing.
        st, body = call("https://api.sarvam.ai/text-to-speech", {"api-subscription-key": k, "Content-Type": "application/json"}, data=b"{}", method="POST")
        verdict = "ACCEPTED" if st in (400, 422) else ("REJECTED" if st in (401, 403) else "UNCLEAR")
        line("Sarvam", st, verdict, body[:160].replace("\n", " "))
    else:
        line("Sarvam", "-", "NO KEY")

    lk = [x for x in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET") if not env.get(x)]
    print(f"{'LiveKit':<10} " + ("all three values present (not tested here)" if not lk else "MISSING: " + ", ".join(lk)))
    jev = "present" if env.get("JEV_API_KEY") else "none (Laya will be used)"
    print(f"{'Jev':<10} {jev}")

if __name__ == "__main__":
    main()
