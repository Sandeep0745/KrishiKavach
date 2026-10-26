"""Mandi price MCP server (SystemDesign §9, P1). Port 8103. Fixture mode only for now."""
from __future__ import annotations

import json

from ghante_shared import config

from ._base import make_server, run_http

HOST, PORT = "127.0.0.1", config.port_of(config.MCP_MANDI_URL, 8103)
server = make_server("mandi", "Market (mandi) prices for crops.", HOST, PORT)


@server.tool()
def get_price(crop: str, district: str) -> dict:
    """Modal market price for a crop in a district, in rupees per quintal."""
    if config.env("MANDI_MODE", "fixture") != "fixture":
        return {"error": "live mandi mode is not built yet; set MANDI_MODE=fixture"}
    prices = json.loads((config.DATA_DIR / "fixtures" / "mandi.json").read_text(encoding="utf-8"))
    for row in prices:
        if row["crop"].lower() == crop.strip().lower() and row["district"].lower() == district.strip().lower():
            return {**row, "source": "fixture"}
    return {"error": f"no fixture price for {crop} in {district}"}


if __name__ == "__main__":
    run_http(server, HOST, PORT)
