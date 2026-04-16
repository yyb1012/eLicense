from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.application.services.chat_service import ChatService
from src.interfaces.api.dependencies import get_chat_service
from src.shared.tracing import ensure_trace_id

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    work_order_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    decision: dict[str, str]
    risk_level: str
    next_action: str
    trace_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    trace_id = ensure_trace_id()
    result = await service.chat(
        session_id=request.session_id,
        work_order_id=request.work_order_id,
        message=request.message,
        user_id=request.user_id,
        trace_id=trace_id,
    )
    return ChatResponse(
        answer=result.answer,
        decision=result.decision,
        risk_level=result.risk_level,
        next_action=result.next_action,
        trace_id=result.trace_id,
    )
