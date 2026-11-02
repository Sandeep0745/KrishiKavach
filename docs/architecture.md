# Architecture — planned, not implemented
Android/desktop browser (HTML/JS) → Starlette API → SQLite + decision service.
Event producers → SSE → dashboard.
One LiveKit voice user → voice agent → bounded MCP tools → case API.
339 synthetic farmer actors → simulator → case API.
Filing adapter → local sandbox portal ONLY → receipt/status to case API.

No services in this diagram are operational other than the scaffold HTTP server.
