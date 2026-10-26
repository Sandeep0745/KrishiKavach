"""Call a tool on one of our MCP servers and report the call as an mcp.tool_called event.

Works with MCP Python SDK 2.x (mcp.Client) and falls back to the 1.x client.
"""
from __future__ import annotations

import asyncio
import json
import time

from . import config, http


def _parse(result) -> dict:
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


async def list_tools(url: str) -> list[str]:
    try:
        from mcp import Client
    except ImportError:
        Client = None
    if Client is not None:
        async with Client(url) as c:
            return [t.name for t in (await c.list_tools()).tools]
    from mcp import ClientSession  # SDK 1.x
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            return [t.name for t in (await s.list_tools()).tools]


class _Pool:
    """One long-lived MCP session per server, for a program that makes many calls (the fleet makes over a thousand).

    Opening a session costs several HTTP requests; a call on an open one costs one. The session is opened and closed inside one
    task, as the SDK's task groups require; callers hand their calls to that task and wait for the answer."""

    def __init__(self) -> None:
        self._queues: dict[tuple[int, str], asyncio.Queue] = {}
        self._workers: dict[tuple[int, str], asyncio.Task] = {}

    async def call(self, url: str, tool: str, args: dict) -> dict:
        loop = asyncio.get_running_loop()
        key = (id(loop), url)
        worker = self._workers.get(key)
        if worker is None or worker.done():
            self._queues[key] = asyncio.Queue()
            self._workers[key] = loop.create_task(self._serve(url, self._queues[key]))
        future: asyncio.Future = loop.create_future()
        self._queues[key].put_nowait((tool, args, future))
        return await future

    @staticmethod
    async def _serve(url: str, queue: asyncio.Queue) -> None:
        from mcp import Client

        item = await queue.get()
        while True:
            try:
                async with Client(url) as session:
                    while True:
                        tool, args, future = item
                        try:
                            result = _parse(await session.call_tool(tool, args))
                        except Exception as e:  # noqa: BLE001 - this call failed; open a fresh session for the next one
                            if not future.done():
                                future.set_exception(e)
                            item = await queue.get()
                            break
                        if not future.done():
                            future.set_result(result)
                        item = await queue.get()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the server could not be reached at all
                if not item[2].done():
                    item[2].set_exception(e)
                item = await queue.get()


_pool = _Pool()


async def call_tool(url: str, tool: str, args: dict | None = None, *, server: str = "", client: str = "", case_id: str | None = None,
                    agent: str | None = None, pooled: bool = False, emit=None) -> dict:
    """`client` is the program that made the call (shown in the tool-call log); `agent` is the agent it was made for.
    `pooled` reuses one session per server. `emit(type, data, case_id, agent)` reports the call directly (used inside the
    orchestrator); without it the call is reported to the orchestrator over HTTP."""
    args = args or {}
    t0 = time.perf_counter()
    try:
        from mcp import Client
    except ImportError:
        Client = None
    if Client is not None and pooled:
        out = await _pool.call(url, tool, args)
    elif Client is not None:
        async with Client(url) as c:
            out = _parse(await c.call_tool(tool, args))
    else:
        from mcp import ClientSession  # SDK 1.x
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                out = _parse(await s.call_tool(tool, args))
    ms = round((time.perf_counter() - t0) * 1000)
    summary = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:4])
    data = {"server": server, "tool": tool, "args_summary": summary, "ms": ms, "client": client}
    who = agent or (client if client in ("intake", "evidence", "eligibility", "sentinel", "dispatcher") else "system")
    if emit is not None:
        emit("mcp.tool_called", data, case_id, who)
    else:
        http.post_event(config.ORCH_URL, "mcp.tool_called", data, case_id=case_id, agent=who)
    return out


def call_tool_sync(url: str, tool: str, args: dict | None = None, **kw) -> dict:
    return asyncio.run(call_tool(url, tool, args, **kw))
