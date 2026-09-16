"""Contrato estándar de herramienta.

Una herramienta declara su nombre, su schema JSON y su ejecutor. El núcleo
nunca ejecuta una herramienta que el agente no tenga explícitamente permitida
en su `profile.yaml`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Resultado normalizado de una ejecución de herramienta."""

    ok: bool = True
    content: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def failure(cls, message: str) -> ToolResult:
        return cls(ok=False, content=f"Error: {message}", error=message)


class BaseTool(ABC):
    """Herramienta invocable por un agente."""

    name: str = "unnamed_tool"
    description: str = ""
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    # Si es True, requiere aprobación humana antes de ejecutarse (Fase 5).
    requires_approval: bool = False

    def spec(self) -> dict[str, Any]:
        """Formato que espera la API de Claude para tool use."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def validate_args(self, args: dict[str, Any]) -> str | None:
        """Comprobación mínima de campos requeridos. Devuelve el error o None."""
        required = self.input_schema.get("required", [])
        missing = [k for k in required if k not in args or args[k] in (None, "")]
        if missing:
            return f"Faltan argumentos requeridos: {', '.join(missing)}"
        return None

    @abstractmethod
    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        """Ejecuta la herramienta.

        `context` trae al menos tenant_id, run_id y agent_id, para que una
        herramienta nunca opere sobre datos de otro cliente.
        """
        raise NotImplementedError
