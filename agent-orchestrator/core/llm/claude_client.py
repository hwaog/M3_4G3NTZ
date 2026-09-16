"""Cliente de la API de Claude (Messages API con tool use)."""

from __future__ import annotations

import os
import time
from typing import Any

from core.llm.provider import LLMProvider, LLMResponse, ToolCall, estimate_cost
from core.orchestrator.state import Usage


class ClaudeProvider(LLMProvider):
    """Backend real. Requiere ANTHROPIC_API_KEY en el entorno."""

    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.5,
    ) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Falta el paquete 'anthropic'. Instala con: pip install anthropic"
            ) from exc

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "No se encontró ANTHROPIC_API_KEY. Define la variable de entorno "
                "o usa --provider mock para correr sin consumir API."
            )
        self._client = Anthropic(api_key=key)
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        response = self._call_with_retries(kwargs)
        return self._normalize(response, model)

    # --- internos --------------------------------------------------------

    def _call_with_retries(self, kwargs: dict[str, Any]):
        from anthropic import APIStatusError, APITimeoutError, RateLimitError

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.messages.create(**kwargs)
            except (RateLimitError, APITimeoutError) as exc:
                last_exc = exc
                time.sleep(self._backoff_base**attempt)
            except APIStatusError as exc:
                if 500 <= exc.status_code < 600:
                    last_exc = exc
                    time.sleep(self._backoff_base**attempt)
                    continue
                raise
        raise RuntimeError(
            f"La API falló tras {self._max_retries} intentos: {last_exc}"
        ) from last_exc

    @staticmethod
    def _normalize(response: Any, model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                raw.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
                raw.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.input),
                    }
                )

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=estimate_cost(
                model, response.usage.input_tokens, response.usage.output_tokens
            ),
        )
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=response.stop_reason or "end_turn",
            raw_content=raw,
        )
