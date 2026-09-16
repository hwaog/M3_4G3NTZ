"""Registro central de herramientas y control de permisos."""

from __future__ import annotations

from typing import Any, Iterable

from core.tools.base_tool import BaseTool, ToolResult


class ToolNotAllowed(PermissionError):
    """Un agente intentó usar una herramienta fuera de su lista permitida."""


class ToolRegistry:
    """Contiene las herramientas disponibles y aplica los permisos."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Herramienta duplicada: '{tool.name}'")
        self._tools[tool.name] = tool

    def register_many(self, tools: Iterable[BaseTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Herramienta no registrada: '{name}'")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def validate_requested(self, requested: Iterable[str], agent_id: str) -> None:
        """Falla al cargar el perfil si un agente pide una herramienta inexistente."""
        unknown = [n for n in requested if n not in self._tools]
        if unknown:
            raise KeyError(
                f"Agente '{agent_id}' solicita herramientas no registradas: "
                f"{unknown}. Disponibles: {self.names()}"
            )

    def specs_for(self, allowed: Iterable[str]) -> list[dict[str, Any]]:
        """Specs en formato API solo de las herramientas permitidas al agente."""
        return [self._tools[n].spec() for n in allowed if n in self._tools]

    def execute(
        self,
        name: str,
        args: dict[str, Any],
        *,
        allowed: Iterable[str],
        context: dict[str, Any],
    ) -> ToolResult:
        """Ejecuta una herramienta verificando permiso y argumentos."""
        allowed_set = set(allowed)
        if name not in allowed_set:
            raise ToolNotAllowed(
                f"El agente '{context.get('agent_id')}' no tiene permitida la "
                f"herramienta '{name}'. Permitidas: {sorted(allowed_set)}"
            )
        tool = self.get(name)
        error = tool.validate_args(args)
        if error:
            return ToolResult.failure(error)
        try:
            return tool.run(args, context)
        except Exception as exc:  # aislar fallos de tool del loop del agente
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")
