"""Abstracción sobre el proveedor LLM.

El núcleo nunca habla con la API directamente: pasa por esta interfaz. Eso
permite (a) correr todo el sistema sin gastar créditos usando MockProvider,
(b) medir tokens y costo de forma uniforme, y (c) cambiar de proveedor sin
tocar la lógica de orquestación.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from core.orchestrator.state import Usage

# Costo por millón de tokens (USD). VERIFICAR contra https://claude.com/pricing
# antes de facturar a un cliente: estas cifras son para estimación interna y
# deben actualizarse cuando cambien las tarifas.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
_FALLBACK_PRICE = (3.00, 15.00)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICING.get(model, _FALLBACK_PRICE)
    cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return round(cost, 8)


class ToolCall(BaseModel):
    """Solicitud del modelo para ejecutar una herramienta."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Respuesta normalizada, independiente del proveedor."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str = "end_turn"
    raw_content: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Contrato mínimo que debe cumplir cualquier backend de modelo."""

    name: str = "base"

    @abstractmethod
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
        """Genera una respuesta del modelo."""
        raise NotImplementedError
