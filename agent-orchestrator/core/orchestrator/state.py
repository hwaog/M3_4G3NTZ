"""Estado compartido de una corrida.

Toda unidad de trabajo del sistema nace atada a un `tenant_id`. No existe
una ruta de ejecución sin cliente asociado: eso es lo que garantiza el
aislamiento de datos y la imputación correcta de costos en el modelo de
servicio gestionado.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    MAX_ITERATIONS = "max_iterations"


class StepType(str, Enum):
    ROUTING = "routing"
    AGENT_TURN = "agent_turn"
    TOOL_CALL = "tool_call"
    DELEGATION = "delegation"
    ESCALATION = "escalation"
    SYNTHESIS = "synthesis"


class Usage(BaseModel):
    """Consumo de tokens y costo estimado."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd = round(self.cost_usd + other.cost_usd, 6)


class Step(BaseModel):
    """Un paso auditable de la corrida.

    La traza completa de pasos es lo que convierte cada ejecución en un
    experimento reproducible y, a la vez, en el reporte que ve el cliente.
    """

    step_id: str = Field(default_factory=lambda: _new_id("step"))
    type: StepType
    actor: str
    summary: str
    input: Any = None
    output: Any = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    started_at: datetime = Field(default_factory=_now)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunState(BaseModel):
    """Estado vivo de una corrida del orquestador."""

    run_id: str = Field(default_factory=lambda: _new_id("run"))
    tenant_id: str
    profile: str
    task: str
    status: RunStatus = RunStatus.RUNNING
    steps: list[Step] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    result: str | None = None
    escalation_reason: str | None = None
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # --- mutadores -------------------------------------------------------

    def record(self, step: Step) -> Step:
        self.steps.append(step)
        self.usage.add(step.usage)
        return step

    def finish(self, status: RunStatus, result: str | None = None) -> None:
        self.status = status
        self.result = result
        self.finished_at = _now()

    def escalate(self, reason: str, message: str) -> None:
        self.escalation_reason = reason
        self.finish(RunStatus.ESCALATED, message)

    # --- consultas -------------------------------------------------------

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.steps if s.type is StepType.TOOL_CALL)

    @property
    def duration_ms(self) -> int:
        end = self.finished_at or _now()
        return int((end - self.started_at).total_seconds() * 1000)

    def summary_line(self) -> str:
        return (
            f"[{self.status.value}] tenant={self.tenant_id} run={self.run_id} "
            f"pasos={len(self.steps)} tokens={self.usage.input_tokens}/"
            f"{self.usage.output_tokens} costo=${self.usage.cost_usd:.4f} "
            f"tiempo={self.duration_ms}ms"
        )
