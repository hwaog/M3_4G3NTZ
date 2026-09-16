"""Reporte de corrida.

La traza es a la vez el registro reproducible del experimento y el insumo
del reporte que verá el cliente en Fase 3.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.orchestrator.state import RunState

_ICON = {
    "routing": "→",
    "agent_turn": "•",
    "tool_call": "⚙",
    "delegation": "⇒",
    "escalation": "!",
    "synthesis": "=",
}


def render_trace(state: RunState, verbose: bool = False) -> str:
    """Traza legible para el operador del servicio."""
    lines = [
        "",
        f"Corrida {state.run_id}",
        f"  cliente : {state.tenant_id}",
        f"  perfil  : {state.profile} ({state.metadata.get('pattern')})",
        f"  tarea   : {state.task}",
        "",
        "Pasos:",
    ]

    for i, step in enumerate(state.steps, 1):
        icon = _ICON.get(step.type.value, "·")
        lines.append(f"  {i:>2}. {icon} {step.summary}  ({step.latency_ms}ms)")
        if step.error:
            lines.append(f"       error: {step.error}")
        elif verbose and step.output:
            snippet = str(step.output).replace("\n", " ")[:160]
            lines.append(f"       {snippet}")

    lines += [
        "",
        f"Estado   : {state.status.value}",
        f"Tokens   : {state.usage.input_tokens} entrada / "
        f"{state.usage.output_tokens} salida",
        f"Costo    : ${state.usage.cost_usd:.6f}",
        f"Duración : {state.duration_ms}ms",
        "",
        "Resultado:",
        f"  {state.result or '(sin resultado)'}",
        "",
    ]
    if state.escalation_reason:
        lines.insert(-1, f"  Motivo de escalamiento: {state.escalation_reason}")
    return "\n".join(lines)


def save_run(state: RunState, output_dir: Path) -> Path:
    """Guarda la corrida completa en JSON, particionada por cliente."""
    tenant_dir = output_dir / state.tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    path = tenant_dir / f"{state.run_id}.json"
    path.write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
