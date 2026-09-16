"""Esquemas de validación para los perfiles de dominio.

Un `profile.yaml` describe QUE agentes existen y QUE herramientas usan.
El núcleo decide COMO se ejecutan. Este módulo es el contrato entre ambos:
si un perfil no valida contra estos esquemas, no se instancia nada.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class OrchestrationPattern(str, Enum):
    """Patrones de coordinación soportados por el núcleo."""

    SUPERVISOR_WORKER = "supervisor_worker"
    ROUTER = "router"


# Modelos disponibles en la API de Claude. Se mantiene como lista cerrada
# para que un typo en un perfil falle al cargar y no en mitad de una corrida.
KNOWN_MODELS = {
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
}

DEFAULT_MODEL = "claude-sonnet-5"
FAST_MODEL = "claude-haiku-4-5-20251001"


class AgentConfig(BaseModel):
    """Definición declarativa de un agente especializado."""

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(
        ...,
        min_length=10,
        description="Qué hace el agente. El router lo usa para clasificar.",
    )
    model: str = DEFAULT_MODEL
    system_prompt_file: str | None = None
    system_prompt: str | None = None
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=6, ge=1, le=30)
    temperature: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("model")
    @classmethod
    def _check_model(cls, v: str) -> str:
        if v not in KNOWN_MODELS:
            raise ValueError(
                f"Modelo desconocido '{v}'. Disponibles: {sorted(KNOWN_MODELS)}"
            )
        return v

    @model_validator(mode="after")
    def _check_prompt_source(self) -> AgentConfig:
        if not self.system_prompt_file and not self.system_prompt:
            raise ValueError(
                f"Agente '{self.id}': define 'system_prompt_file' o 'system_prompt'."
            )
        return self


class RouterConfig(BaseModel):
    """Configuración del agente clasificador (solo patrón router)."""

    model: str = FAST_MODEL
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    escalation_message: str = (
        "Voy a derivar esta conversación con una persona del equipo para "
        "asegurarme de que te den la mejor respuesta."
    )
    default_agent: str | None = Field(
        default=None,
        description="Agente al que va lo no clasificado. Si es None, escala.",
    )

    @field_validator("model")
    @classmethod
    def _check_model(cls, v: str) -> str:
        if v not in KNOWN_MODELS:
            raise ValueError(f"Modelo desconocido '{v}'.")
        return v


class LimitsConfig(BaseModel):
    """Guardarraíles de ejecución. Se aplican por corrida, no por agente."""

    max_iterations: int = Field(default=8, ge=1, le=50)
    max_cost_usd: float = Field(default=1.0, gt=0)
    max_tool_calls: int = Field(default=25, ge=1)


class ProfileConfig(BaseModel):
    """Un perfil de dominio completo: la 'maqueta' reutilizable."""

    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    description: str = ""
    orchestration_pattern: OrchestrationPattern
    orchestrator: AgentConfig | None = None
    router: RouterConfig | None = None
    agents: list[AgentConfig] = Field(..., min_length=1)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    human_in_the_loop: bool = False

    # Ruta del perfil en disco. La inyecta el loader, no viene del YAML.
    base_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _check_pattern_requirements(self) -> ProfileConfig:
        ids = [a.id for a in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay ids de agente duplicados en el perfil.")

        if self.orchestration_pattern is OrchestrationPattern.SUPERVISOR_WORKER:
            if self.orchestrator is None:
                raise ValueError(
                    "El patrón 'supervisor_worker' requiere la clave 'orchestrator'."
                )
        if self.orchestration_pattern is OrchestrationPattern.ROUTER:
            if self.router is None:
                raise ValueError("El patrón 'router' requiere la clave 'router'.")
            default = self.router.default_agent
            if default and default not in ids:
                raise ValueError(
                    f"router.default_agent '{default}' no existe en 'agents'."
                )
        return self

    def agent(self, agent_id: str) -> AgentConfig:
        for a in self.agents:
            if a.id == agent_id:
                return a
        raise KeyError(f"Agente '{agent_id}' no definido en el perfil '{self.name}'.")


class TenantConfig(BaseModel):
    """Un cliente del servicio gestionado.

    Parametriza un perfil sin modificarlo: activa un subconjunto de agentes,
    fija su propio tope de gasto y apunta a sus credenciales cifradas.
    """

    tenant_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str
    profile: str = Field(..., description="Nombre del perfil que instancia.")
    plan: Literal["trial", "starter", "pro", "custom"] = "trial"
    enabled_agents: list[str] = Field(
        default_factory=list,
        description="Subconjunto de agentes activos. Vacío = todos los del perfil.",
    )
    monthly_budget_usd: float = Field(default=5.0, gt=0)
    max_cost_per_run_usd: float | None = Field(default=None, gt=0)
    active: bool = True
    notes: str = ""
