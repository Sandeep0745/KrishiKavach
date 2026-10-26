"""Shared helpers for the MCP servers. Works with MCP Python SDK 2.x (MCPServer) and falls back to 1.x (FastMCP)."""
from __future__ import annotations

try:  # SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server

    SDK = 2
except ModuleNotFoundError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

    SDK = 1

from starlette.responses import JSONResponse


def make_server(name: str, instructions: str, host: str, port: int):
    if SDK == 2:
        server = _Server(name, instructions=instructions, log_level="WARNING")
    else:
        server = _Server(name, instructions=instructions, host=host, port=port, log_level="WARNING")

    @server.custom_route("/health", methods=["GET"])
    async def health(request):  # noqa: ARG001
        return JSONResponse({"ok": True, "service": f"mcp-{name}"})

    return server


def run_http(server, host: str, port: int) -> None:
    """Serve streamable HTTP at /mcp."""
    if SDK == 2:
        server.run(transport="streamable-http", host=host, port=port)
    else:
        server.run(transport="streamable-http")
