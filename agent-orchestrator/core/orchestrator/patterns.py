"""Patrones de coordinación intercambiables por configuración.

Ambos patrones reciben lo mismo y devuelven lo mismo, así que el perfil
puede cambiar de uno a otro sin tocar código.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from core.agents.base_agent import BaseAgent
from core.agents.registry import build_agents
from core.config.schema import ProfileConfig
from core.llm.provider import LLMProvider, ToolCall
from core.orchestrator.state import RunState, RunStatus, Step, StepType
from core.tenancy.context import TenantContext
from core.tools.registry import ToolRegistry


class OrchestrationStrategy(ABC):
    """Contrato de un patrón de orquestación."""

    def __init__(
        self,
        profile: ProfileConfig,
        provider: LLMProvider,
        tools: ToolRegistry,
        tenant: TenantContext,
    ) -> None:
        self.profile = profile
        self.provider = provider
        self.tools = tools
        self.tenant = tenant
        self.agents: dict[str, BaseAgent] = build_agents(
            profile, provider, tools, tenant
        )

    @abstractmethod
    def execute(self, state: RunState) -> None:
        """Corre la tarea y deja el resultado en `state`."""
        raise NotImplementedError


class SupervisorWorkerStrategy(OrchestrationStrategy):
    """Un orquestador planifica, delega en workers y sintetiza el resultado.

    Adecuado cuando una tarea compleja se descompone en subtareas que luego
    hay que integrar (informes, campañas, auditorías).
    """

    def execute(self, state: RunState) -> None:
        delegate_specs = [
            {
                "name": f"delegate_to_{agent_id}",
                "description": (
                    f"Delega una subtarea a '{agent_id}'. "
                    f"{agent.config.description}"
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Subtarea concreta para este agente.",
                        }
                    },
                    "required": ["task"],
                },
            }
            for agent_id, agent in self.agents.items()
        ]

        supervisor = BaseAgent(
            config=self.profile.orchestrator,
            provider=self.provider,
            tools=self.tools,
            extra_tool_specs=delegate_specs,
            extra_tool_handler=self._handle_delegation,
        )

        result = supervisor.run(state.task, state, self.tenant)
        state.record(
            Step(
                type=StepType.SYNTHESIS,
                actor=supervisor.id,
                summary="El orquestador sintetizó el resultado final",
                output=result,
            )
        )
        state.finish(RunStatus.COMPLETED, result)

    def _handle_delegation(
        self, call: ToolCall, state: RunState, tenant: TenantContext
    ) -> str:
        agent_id = call.name.removeprefix("delegate_to_")
        agent = self.agents.get(agent_id)
        if agent is None:
            return f"Error: el agente '{agent_id}' no está habilitado para este cliente."
        subtask = str(call.arguments.get("task", state.task))
        return agent.run(subtask, state, tenant)


class RouterStrategy(OrchestrationStrategy):
    """Un clasificador enruta cada solicitud al asistente correcto.

    Adecuado para el paquete de asistentes virtuales: llegan mensajes sueltos
    por distintos canales y hay que decidir quién los atiende, con una ruta
    explícita de escalamiento a humano cuando la confianza es baja.
    """

    CLASSIFY_TOOL = "classify_intent"

    def execute(self, state: RunState) -> None:
        router_cfg = self.profile.router
        decision = self._classify(state)

        agent_id = decision.get("agent_id", "escalate")
        confidence = float(decision.get("confidence", 0.0))
        reason = str(decision.get("reason", ""))

        state.record(
            Step(
                type=StepType.ROUTING,
                actor="router",
                summary=f"Router → {agent_id} (confianza {confidence:.2f})",
                input=state.task,
                output=reason,
                metadata={"agent_id": agent_id, "confidence": confidence},
            )
        )

        if agent_id == "escalate" or confidence < router_cfg.confidence_threshold:
            if router_cfg.default_agent and agent_id == "escalate":
                agent_id = router_cfg.default_agent
            else:
                self._escalate(state, reason or "Confianza por debajo del umbral.")
                return

        agent = self.agents.get(agent_id)
        if agent is None:
            self._escalate(
                state, f"El asistente '{agent_id}' no está habilitado para este plan."
            )
            return

        result = agent.run(state.task, state, self.tenant)
        state.finish(RunStatus.COMPLETED, result)

    # --- internos --------------------------------------------------------

    def _classify(self, state: RunState) -> dict[str, Any]:
        """Pide al clasificador una decisión estructurada vía tool use."""
        descriptions = {
            agent_id: agent.config.description for agent_id, agent in self.agents.items()
        }
        options = [*descriptions.keys(), "escalate"]

        spec = {
            "name": self.CLASSIFY_TOOL,
            "description": "Registra a qué asistente corresponde esta solicitud.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "enum": options,
                        "description": (
                            "Asistente que debe atender la solicitud. Opciones y "
                            "responsabilidades::" + json.dumps(descriptions, ensure_ascii=False)
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confianza en la clasificación, de 0 a 1.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Justificación breve de la decisión.",
                    },
                },
                "required": ["agent_id", "confidence", "reason"],
            },
        }

        catalog = "\n".join(f"- {aid}: {desc}" for aid, desc in descriptions.items())
        system = (
            "Router de asistentes virtuales.\n"
            "Clasificas cada solicitud entrante y la asignas al asistente adecuado.\n"
            "Asistentes disponibles:\n"
            f"{catalog}\n"
            "- escalate: ninguno aplica, o el caso requiere criterio humano.\n\n"
            f"Usa siempre la herramienta {self.CLASSIFY_TOOL}. Si dudas entre dos "
            "opciones, baja la confianza en vez de inventar una certeza."
        )

        started = time.perf_counter()
        response = self.provider.complete(
            model=self.profile.router.model,
            system=system,
            messages=[{"role": "user", "content": state.task}],
            tools=[spec],
            temperature=0.0,
        )
        latency = int((time.perf_counter() - started) * 1000)

        state.record(
            Step(
                type=StepType.AGENT_TURN,
                actor="router",
                summary="Clasificación de intención",
                usage=response.usage,
                latency_ms=latency,
                metadata={"model": self.profile.router.model},
            )
        )
        self.tenant.check_budget(state.usage.cost_usd)

        for call in response.tool_calls:
            if call.name == self.CLASSIFY_TOOL:
                return call.arguments
        return {
            "agent_id": "escalate",
            "confidence": 0.0,
            "reason": "El clasificador no devolvió una decisión estructurada.",
        }

    def _escalate(self, state: RunState, reason: str) -> None:
        state.record(
            Step(
                type=StepType.ESCALATION,
                actor="router",
                summary="Escalado a humano",
                output=reason,
            )
        )
        state.escalate(reason, self.profile.router.escalation_message)


STRATEGIES = {
    "supervisor_worker": SupervisorWorkerStrategy,
    "router": RouterStrategy,
}
