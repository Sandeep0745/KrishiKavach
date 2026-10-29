"""The pipeline graph. Built with LangGraph when it is installed; otherwise with the small runner below, which follows the
same nodes and edges (TechDecisions §6: the documented fallback keeps node names and events).

Both are built by the same `build()` call, so there is one description of the graph.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

START, END = "__start__", "__end__"


class PipelineState(TypedDict, total=False):
    case_id: str
    start_at: str          # "evidence" (normal) or "filing" (a reviewer approved the case, or filing is tried again)
    note: str              # added to the form's remarks, e.g. "Approved by a human reviewer"
    case: dict
    policy: dict
    pack: dict             # {"evidence": row or None, "weather": {...}, "distance_from_plot_m": float, "loss_estimate_inr": ...}
    checks: list
    verdict: str
    reasons: list
    form: dict
    claim_ref: str
    filing_mode: str
    failed: str            # why filing produced no reference
    seconds: float


Node = Callable[[dict], Awaitable[dict]]


class MiniGraph:
    """The few parts of LangGraph's StateGraph this pipeline uses: nodes, edges, conditional edges, ainvoke."""

    def __init__(self, _state_type: Any = None) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.branches: dict[str, tuple[Callable[[dict], str], dict[str, str]]] = {}

    def add_node(self, name: str, action: Node) -> "MiniGraph":
        self.nodes[name] = action
        return self

    def add_edge(self, source: str, target: str) -> "MiniGraph":
        self.edges[source] = target
        return self

    def add_conditional_edges(self, source: str, path: Callable[[dict], str], path_map: dict[str, str]) -> "MiniGraph":
        self.branches[source] = (path, path_map)
        return self

    def compile(self) -> "MiniGraph":
        return self

    def _next(self, current: str, state: dict) -> str:
        if current in self.branches:
            path, path_map = self.branches[current]
            return path_map[path(state)]
        return self.edges.get(current, END)

    async def ainvoke(self, state: dict) -> dict:
        state = dict(state)
        current = self._next(START, state)
        steps = 0
        while current != END:
            steps += 1
            if steps > 20:
                raise RuntimeError("pipeline graph did not finish")
            state.update(await self.nodes[current](state) or {})
            current = self._next(current, state)
        return state


def engine_name() -> str:
    try:
        import langgraph  # noqa: F401

        return "langgraph"
    except Exception:  # noqa: BLE001 - not installed, or it does not load on this machine
        return "built-in"


def build(nodes: dict[str, Node], engine: str | None = None):
    """evidence -> eligibility -> (filing | end); filing -> (followup | end); followup -> end.
    A run may also start at filing (reviewer approval, or a second try after a failure)."""
    engine = engine or engine_name()
    if engine == "langgraph":
        from langgraph.graph import END as LG_END
        from langgraph.graph import START as LG_START
        from langgraph.graph import StateGraph

        graph, start, end = StateGraph(PipelineState), LG_START, LG_END
    else:
        graph, start, end = MiniGraph(PipelineState), START, END
    for name in ("evidence", "eligibility", "filing", "followup"):
        graph.add_node(name, nodes[name])
    graph.add_conditional_edges(start, lambda s: "filing" if s.get("start_at") == "filing" else "evidence", {"evidence": "evidence", "filing": "filing"})
    graph.add_edge("evidence", "eligibility")
    graph.add_conditional_edges("eligibility", lambda s: "filing" if s.get("verdict") == "eligible" else "end", {"filing": "filing", "end": end})
    graph.add_conditional_edges("filing", lambda s: "followup" if s.get("claim_ref") else "end", {"followup": "followup", "end": end})
    graph.add_edge("followup", end)
    return graph.compile()
