from __future__ import annotations

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - fallback for dependency bootstrap stage
    END = "END"
    START = "START"
    StateGraph = None


def _context_bootstrap(state: GraphState) -> GraphState:
    return {
        **state,
        "errors": state.get("errors", []),
    }


def _placeholder_orchestrate(state: GraphState) -> GraphState:
    message = state.get("user_input", "").strip()
    if not message:
        message = "empty message"
    return {
        **state,
        "route": "pass",
        "answer_text": f"[stub] request accepted: {message}",
    }


class Orchestrator:
    """Minimal executable orchestrator for N03."""

    def __init__(self) -> None:
        self._compiled_graph = self._build_graph()

    def _build_graph(self):
        if StateGraph is None:
            logger.warning("langgraph_not_installed_fallback_enabled")
            return None

        graph = StateGraph(GraphState)
        graph.add_node("context_bootstrap", _context_bootstrap)
        graph.add_node("placeholder_orchestrate", _placeholder_orchestrate)
        graph.add_edge(START, "context_bootstrap")
        graph.add_edge("context_bootstrap", "placeholder_orchestrate")
        graph.add_edge("placeholder_orchestrate", END)
        return graph.compile()

    async def run(self, state: GraphState) -> GraphState:
        if self._compiled_graph is None:
            return _placeholder_orchestrate(_context_bootstrap(state))
        return self._compiled_graph.invoke(state)
