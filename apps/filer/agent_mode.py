"""Agent mode: a browser-use agent reads the portal's pages and fills the form itself, on a free-tier LLM (TechDecisions §7).

Checked against browser-use 0.13.11. The agent works in the Filer's own window through its debugging port. Whether it
succeeded is decided afterwards by looking at the page, not by what the agent says.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import time
from urllib.parse import urlparse

from ghante_shared import config, usage

LABELS = [  # (page heading, [(label on the page, form key)])
    ("Page 1 of 3, Farmer and policy", [("Application number", "application_no"), ("Farmer name", "farmer_name"), ("Mobile number", "mobile"),
                                        ("State", "state"), ("District", "district"), ("Tehsil", "tehsil"), ("Village", "village")]),
    ("Page 2 of 3, Loss details", [("Season", "season"), ("Crop", "crop"), ("Khasra (survey) number", "khasra_no"),
                                   ("Insured area (hectares)", "insured_area_ha"), ("Date of loss", "loss_date"), ("Time of loss", "loss_time"),
                                   ("Cause of loss", "cause_of_loss"), ("Crop stage", "crop_stage"), ("Affected area (hectares)", "affected_area_ha"),
                                   ("Damage (percent)", "damage_pct"), ("Remarks", "remarks")]),
    ("Page 3 of 3, Evidence and declaration", [("GPS latitude", "gps_lat"), ("GPS longitude", "gps_lon"), ("Submitted by", "submitted_by")]),
]


def available() -> tuple[bool, str]:
    try:
        import browser_use  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"browser-use is not installed in this environment ({type(e).__name__})"
    if not chain():
        return False, "no key for any model in BROWSER_LLM_CHAIN"
    return True, "ready"


def chain() -> list[tuple[str, str]]:
    """(provider, model) pairs from BROWSER_LLM_CHAIN for which a key is set."""
    out = []
    # `or`: a blank BROWSER_LLM_CHAIN= line in .env (left from the first template) must not switch the agent off
    for item in (config.env("BROWSER_LLM_CHAIN") or "groq:openai/gpt-oss-120b,gemini:gemini-3.8-flash").split(","):
        provider, _, model = item.strip().partition(":")
        key = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider)
        if key and model and config.env(key):
            out.append((provider, model))
    return out


def make_llm(provider: str, model: str):
    if provider == "groq":
        from browser_use import ChatGroq

        return ChatGroq(model=model, api_key=config.env("GROQ_API_KEY"))
    from browser_use import ChatGoogle

    return ChatGoogle(model=model, api_key=config.env("GEMINI_API_KEY"))


KEEP_ACTIONS = {"click", "input", "select_dropdown", "upload_file", "done"}
ALL_ACTIONS = ["click", "close", "done", "dropdown_options", "evaluate", "extract", "find_elements", "find_text", "go_back", "input", "navigate", "read_file",
               "replace_file", "save_as_pdf", "screenshot", "scroll", "search", "search_page", "select_dropdown", "send_keys", "switch", "upload_file",
               "wait", "write_file"]


def page_task(number: int, form: dict, photo_path: str) -> str:
    """What the agent is asked to do on one page of the form. One page per agent keeps each request small."""
    heading, fields = LABELS[number - 1]
    button = "Submit report" if number == 3 else "Next"
    lines = [f"A web form is open on {heading.lower()}. Fill every field listed below with exactly the given value, all in one go, "
             f"and then click the '{button}' button as the last action. Do not change, translate or reformat any value. Do not open another page.", ""]
    for label, key in fields:
        if str(form.get(key, "")) != "":
            lines.append(f"- {label}: {form[key]}")
    if number == 2:
        lines.append("(Date of loss is typed as YYYY-MM-DD and Time of loss as HH:MM, exactly as given. Crop stage is a radio button: click the one with that label.)")
    if number == 3:
        lines.append(f"- Photo of the damaged crop: upload the file {photo_path}")
        lines.append("- Tick the declaration checkbox.")
    return "\n".join(lines)


def _describe(action, state) -> tuple[str, str]:
    """(action, field) for one agent action, for the dashboard. Never raises."""
    try:
        data = action.model_dump(exclude_unset=True, exclude_none=True)
        name, params = next(iter(data.items()))
        params = params if isinstance(params, dict) else {}
        field = ""
        index = params.get("index")
        if index is not None:
            node = getattr(getattr(state, "dom_state", None), "selector_map", {}).get(index)
            attrs = getattr(node, "attributes", None) or {}
            field = attrs.get("id") or attrs.get("name") or ""
        verb = {"input": "fill", "input_text": "fill", "click": "click", "click_element_by_index": "click", "select_dropdown": "select",
                "select_dropdown_option": "select", "upload_file": "upload", "navigate": "open", "go_to_url": "open", "done": "done"}.get(name, name)
        return verb, field or ("page" if verb == "open" else "")
    except Exception:  # noqa: BLE001
        return "act", ""


async def focus_form(browser, portal) -> None:
    """Attach to the actual form tab; Chrome's active tab can be about:blank."""
    from browser_use.browser.events import SwitchTabEvent

    await browser.start()
    form_url = (await portal.page()).url
    tabs = await browser.get_tabs()
    target = next((tab for tab in tabs if tab.url == form_url), None)
    if target is None:
        raise RuntimeError("the claim form tab is not available to the browser agent")
    event = browser.event_bus.dispatch(SwitchTabEvent(target_id=target.target_id))
    await event
    await event.event_result(raise_if_any=True, raise_if_none=False)
    if await browser.get_current_page_url() != form_url:
        raise RuntimeError("the browser agent could not focus the claim form tab")


async def run(cdp_http_url: str, portal_url: str, form: dict, photo_path: str, timeout_s: float, on_step, portal) -> dict:
    """Let the agent fill the form, one page at a time. `portal` is the Filer's own view of the window (PortalBrowser): it opens
    page 1 and tells us which page the window is on, so each page's agent can stop as soon as its page has been accepted.

    Why one agent per page (measured on 7 Oct, Phase3Results.md): the free tier allows 8,000 tokens a minute for each model. One
    agent for the whole form made 7 requests and spent most of 182 seconds waiting for that allowance. Per page, each request is
    small and there is no closing "done" request: 3 requests, about 8,400 tokens and 31 seconds for the whole form.

    Returns {"llm_steps", "actions", "provider", "model", "models", "tokens", "error"}; `error` is "" when all three pages were accepted."""
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    from browser_use import Agent, Browser, Tools

    models = chain()
    host = urlparse(portal_url).hostname or "127.0.0.1"
    # The model has to repeat the file path exactly. Forward slashes survive that; Windows backslashes inside JSON often do not.
    shown_path = pathlib.Path(photo_path).as_posix()
    counter = {"actions": 0, "llm": 0, "tokens": 0}
    used: list[str] = []
    t0 = time.perf_counter()
    error = ""
    await portal.open_form()
    for number in (1, 2, 3):
        left = timeout_s - (time.perf_counter() - t0)
        if left < 3:
            error = f"the agent took longer than {int(timeout_s)} seconds"
            break
        # Every page goes to the first model of the chain; the second is only browser-use's fallback when a request fails.
        # (Measured: Groq gpt-oss-120b fills all three pages correctly; qwen3.8-27b could not upload the photo; gpt-oss-20b
        # cannot produce the action format; Gemini's free tier answered 503.)
        provider, model = models[0]
        used.append(f"{provider}:{model}")
        other = models[1] if len(models) > 1 else None
        browser = Browser(cdp_url=cdp_http_url, keep_alive=True, allowed_domains=[host])
        page_llm = {"n": 0}

        def step_callback(state, output, step_number, page_llm=page_llm, provider=provider, model=model, number=number) -> None:
            page_llm["n"] = max(page_llm["n"], int(step_number or 0))
            did = []
            for action in getattr(output, "action", None) or []:
                verb, field = _describe(action, state)
                did.append(f"{verb} {field}".strip())
                if verb == "done":
                    continue
                counter["actions"] += 1
                on_step(counter["actions"], verb, field)
            # one line per LLM answer, with the time, so a slow run can be read afterwards
            print(f"[filer] agent page {number} {provider}:{model} answer {step_number} at {time.perf_counter() - t0:.1f} s: {', '.join(did)[:300]}", flush=True)

        async def moved_on(number=number) -> bool:
            return (await portal.where()) != number

        agent = Agent(task=page_task(number, form, shown_path), llm=make_llm(provider, model), fallback_llm=make_llm(*other) if other else None,
                      browser=browser, tools=Tools(exclude_actions=[a for a in ALL_ACTIONS if a not in KEEP_ACTIONS]), use_vision=False,
                      max_actions_per_step=14, flash_mode=True, max_failures=2, available_file_paths=sorted({shown_path, photo_path}), use_judge=False,
                      enable_signal_handler=False, register_new_step_callback=step_callback, register_should_stop_callback=moved_on,
                      directly_open_url=False, generate_gif=False, calculate_cost=False, llm_timeout=30, step_timeout=60)
        if number == 1:
            usage.add(provider, "browser_agent_runs")
        try:
            await asyncio.wait_for(focus_form(browser, portal), timeout=min(left, 15))
            left = timeout_s - (time.perf_counter() - t0)
            history = await asyncio.wait_for(agent.run(max_steps=4), timeout=max(0.01, left))
            spent = getattr(getattr(history, "usage", None), "total_tokens", None)
            if spent:
                counter["tokens"] += int(spent)
                print(f"[filer] agent page {number} used {spent} tokens ({getattr(history.usage, 'total_prompt_tokens', '?')} in the prompt)", flush=True)
            if (await portal.where()) == number:
                errors = [e for e in history.errors() if e]
                error = f"page {number} was not completed" + (f": {str(errors[-1])[:140]}" if errors else "")
        except asyncio.TimeoutError:
            error = f"the agent took longer than {int(timeout_s)} seconds"
            try:
                agent.stop()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001 - rate limits and model errors arrive here
            if (await portal.where()) == number:
                error = f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            counter["llm"] += page_llm["n"]
            try:
                # Agent.close() with keep_alive only stops its event bus. Explicitly
                # detach CDP/watchdogs so old sessions cannot spawn blank tabs later.
                await asyncio.wait_for(browser.stop(), 10)
            except Exception:  # noqa: BLE001
                pass
        if error:
            break
    provider, model = models[0]
    usage.add(provider, "browser_agent_llm_steps", counter["llm"])
    print(f"[filer] agent ended after {time.perf_counter() - t0:.1f} s, {counter['llm']} answers, {counter['actions']} actions, {counter['tokens']} tokens"
          + (f"; {error}" if error else ""), flush=True)
    return {"llm_steps": counter["llm"], "actions": counter["actions"], "provider": provider, "model": model, "models": used,
            "tokens": counter["tokens"], "error": error}
