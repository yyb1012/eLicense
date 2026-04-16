from __future__ import annotations

from fastapi import Request

from src.application.services.chat_service import ChatService


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service
