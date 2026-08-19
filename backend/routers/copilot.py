"""
routers/copilot.py

STUB (Day 1). Returns a fixed, hardcoded copilot answer in the exact
shape the real Day 2 pipeline (local RAG + Ollama) will produce, so the
AICopilot page and its components can be built and demoed today. No LLM,
no retrieval, no database access happens here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["copilot"])


class ChatRequest(BaseModel):
    question: str = ""


@router.post("/chat")
def post_chat(payload: ChatRequest) -> dict:
    return {
        "summary": "Edge Router 7 is showing repeated BGP session resets with rising packet loss on its uplink.",
        "root_cause": "BGP session instability between router-7 and router-5 causing route withdrawal and reconvergence.",
        "risk": 0.78,
        "affected_component": "router-7",
        "recommended_action": "restart_bgp_session",
        "evidence": [
            {"source": "runbook_bgp_flap.md", "snippet": "Repeated BGP resets within a 5 minute window indicate session instability.", "score": 0.91},
            {"source": "telemetry_logs", "snippet": "router-7 packet_loss crossed the critical threshold (5.0%).", "score": 0.84},
        ],
        "confidence": 0.82,
        "requires_human_approval": True,
    }
