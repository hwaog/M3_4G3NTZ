"""Agente base: ejecuta el loop de razonamiento y uso de herramientas."""

from __future__ import annotations

import time
from typing import Any

from core.config.schema import AgentConfig
from core.llm.provider import LLMProvider
from core.orchestrator.state import RunState, Step, StepType, Usage
from core.tenancy.context import TenantContext
from core.tools.registry import ToolRegistry


class BaseAgent:
    """Un agente especializado con prompt, modelo y herramientas propias."""

    def __init__(
        self,
        config: AgentConfig,
        provider: LLMProvider,
        tools: ToolRegistry,
        extra_tool_specs: list[dict[str, Any]] | None = None,
        extra_tool_handler: Any | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.tools = tools
        # Herramientas sintéticas (p. ej. delegate_to_*) que no viven en el
        # registro global porque dependen del patrón de orquestación.
        self.extra_tool_specs = extra_tool_specs or []
        self.extra_tool_handler = extra_tool_handler

    @property
    def id(self) -> str:
        return self.config.id

    def run(
        self,
        task: str,
        state: RunState,
        tenant: TenantContext,
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Ejecuta al agente hasta obtener una respuesta de texto."""
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": task})

        specs = self.tools.specs_for(self.config.tools) + self.extra_tool_specs
        last_text = ""

        for _ in range(self.config.max_iterations):
            started = time.perf_counter()
            response = self.provider.complete(
                model=self.config.model,
                system=self.config.system_prompt or "",
                messages=messages,
                tools=specs or None,
                temperature=self.config.temperature,
            )
            latency = int((time.perf_counter() - started) * 1000)

            state.record(
                Step(
                    type=StepType.AGENT_TURN,
                    actor=self.id,
                    summary=(
                        f"{self.id} solicitó {len(response.tool_calls)} herramienta(s)"
                        if response.wants_tools
                        else f"{self.id} respondió"
                    ),
                    input=task if not messages[:-1] else "(continuación)",
                    output=response.text or None,
                    usage=response.usage,
                    latency_ms=latency,
                    metadata={"model": self.config.model},
                )
            )
            tenant.check_budget(state.usage.cost_usd)

            if response.text:
                last_text = response.text

            if not response.wants_tools:
                return last_text

            messages.append({"role": "assistant", "content": response.raw_content})
            results = self._execute_tools(response.tool_calls, state, tenant)
            messages.append({"role": "user", "content": results})

        return last_text or "(el agente agotó sus iteraciones sin respuesta final)"

    # --- internos --------------------------------------------------------

    def _execute_tools(
        self, tool_calls: list[Any], state: RunState, tenant: TenantContext
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        context = {
            "tenant_id": state.tenant_id,
            "run_id": state.run_id,
            "agent_id": self.id,
        }

        for call in tool_calls:
            tenant.check_tool_calls(state.tool_call_count)
            started = time.perf_counter()

            if self.extra_tool_handler and call.name.startswith("delegate_to_"):
                content = self.extra_tool_handler(call, state, tenant)
                step_type = StepType.DELEGATION
                ok = True
            else:
                result = self.tools.execute(
                    call.name,
                    call.arguments,
                    allowed=self.config.tools,
                    context=context,
                )
                content = result.content
                step_type = StepType.TOOL_CALL
                ok = result.ok

            latency = int((time.perf_counter() - started) * 1000)
            state.record(
                Step(
                    type=step_type,
                    actor=self.id,
                    summary=f"{self.id} → {call.name}",
                    input=call.arguments,
                    output=content,
                    latency_ms=latency,
                    usage=Usage(),
                    error=None if ok else content,
                )
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": content,
                    "is_error": not ok,
                }
            )
        return results
