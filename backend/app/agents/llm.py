"""LLM factory — returns an OpenAI / Azure OpenAI chat model, or None if not configured."""
from __future__ import annotations

from typing import Optional

from app.config import settings


def get_chat_model():
    """Return a LangChain chat model bound to either Azure OpenAI or OpenAI.

    Returns None if no credentials are configured (deterministic fallback used)."""
    s = settings()
    if s.azure_endpoint and s.azure_api_key and s.azure_deployment:
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            azure_endpoint=s.azure_endpoint,
            api_key=s.azure_api_key,
            azure_deployment=s.azure_deployment,
            api_version=s.azure_api_version,
            temperature=0,
        )
    if s.openai_api_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=s.openai_api_key,
            model=s.openai_model,
            temperature=0,
        )
    return None
