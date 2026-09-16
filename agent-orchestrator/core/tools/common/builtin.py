"""Herramientas genéricas de Fase 1.

Son deliberadamente simples (dummy): su propósito es ejercitar el motor,
los permisos y la traza. Las herramientas reales de cada vertical llegan
en Fase 4 dentro de `profiles/<perfil>/tools/`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.tools.base_tool import BaseTool, ToolResult

# Base de conocimiento simulada, por cliente. En producción esto vive en el
# almacenamiento aislado del tenant, no en el código.
_FAKE_KB: dict[str, list[tuple[str, str]]] = {
    "_default": [
        ("horario", "Atendemos de lunes a viernes, 8:00 a 18:00 (hora Colombia)."),
        ("precio", "El plan Starter cuesta USD 149/mes e incluye 3 asistentes."),
        ("devolucion", "Aceptamos cancelaciones sin costo dentro de los 14 días."),
        ("soporte", "El soporte prioritario está incluido en los planes Pro."),
    ]
}


class KnowledgeBaseSearch(BaseTool):
    """Busca en la base de conocimiento del cliente."""

    name = "kb_search"
    description = (
        "Busca información en la base de conocimiento del cliente: horarios, "
        "precios, políticas de devolución y condiciones de soporte."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Términos a buscar."}
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        query = str(args["query"]).lower()
        tenant_id = context.get("tenant_id", "_default")
        entries = _FAKE_KB.get(tenant_id, _FAKE_KB["_default"])
        hits = [text for key, text in entries if key in query or query in text.lower()]
        if not hits:
            return ToolResult(
                ok=True,
                content="Sin coincidencias en la base de conocimiento.",
                data={"hits": 0},
            )
        return ToolResult(content=" ".join(hits), data={"hits": len(hits)})


class CalendarCheck(BaseTool):
    """Consulta disponibilidad de agenda (simulada)."""

    name = "calendar_check"
    description = (
        "Consulta los espacios disponibles en la agenda para reservar, agendar "
        "o reprogramar una cita, reunión o llamada."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Fecha o rango deseado."}
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        slots = ["martes 10:00", "martes 15:30", "jueves 09:00"]
        return ToolResult(
            content=f"Espacios disponibles: {', '.join(slots)}.",
            data={"slots": slots, "requested": args["query"]},
        )


class DocumentLookup(BaseTool):
    """Busca en los documentos internos del cliente (simulado)."""

    name = "document_lookup"
    description = (
        "Busca y resume documentos internos, informes, manuales y "
        "procedimientos del cliente para tareas de investigación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Tema a investigar."}
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        topic = args["query"]
        return ToolResult(
            content=(
                f"Se encontraron 2 documentos relacionados con '{topic}': "
                "'Manual de operaciones v3' y 'Informe trimestral Q2'."
            ),
            data={"documents": ["Manual de operaciones v3", "Informe trimestral Q2"]},
        )


class CurrentTime(BaseTool):
    """Devuelve la hora actual en UTC."""

    name = "current_time"
    description = "Devuelve la fecha y hora actual en UTC."
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc)
        return ToolResult(
            content=now.strftime("%Y-%m-%d %H:%M UTC"),
            data={"iso": now.isoformat()},
        )


def default_tools() -> list[BaseTool]:
    """Herramientas registradas por defecto en cualquier perfil."""
    return [KnowledgeBaseSearch(), CalendarCheck(), DocumentLookup(), CurrentTime()]
