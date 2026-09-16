"""Motor de ejecución del orquestador.

Punto de entrada único: recibe una tarea de un cliente y devuelve el estado
completo de la corrida (resultado + traza auditable).
"""

from __future__ import annotations

from core.config.loader import load_profile, load_tenant
from core.config.schema import ProfileConfig, TenantConfig
from core.llm.provider import LLMProvider
from core.observability.logger import get_logger
from core.orchestrator.patterns import STRATEGIES
from core.orchestrator.state import RunState, RunStatus, Step, StepType
from core.tenancy.context import BudgetExceeded, LimitExceeded, TenantContext
from core.tools.common.builtin import default_tools
from core.tools.registry import ToolRegistry

logger = get_logger(__name__)


class Orchestrator:
    """Ensambla el sistema para un cliente y ejecuta tareas."""

    def __init__(
        self,
        profile: ProfileConfig,
        tenant: TenantConfig,
        provider: LLMProvider,
        tools: ToolRegistry | None = None,
    ) -> None:
        if tenant.profile != profile.name:
            raise ValueError(
                f"El tenant '{tenant.tenant_id}' está asignado al perfil "
                f"'{tenant.profile}', no a '{profile.name}'."
            )
        if not tenant.active:
            raise ValueError(f"El tenant '{tenant.tenant_id}' está inactivo.")

        self.profile = profile
        self.tenant_config = tenant
        self.provider = provider
        self.tools = tools or self._default_registry()
        self.context = TenantContext.from_config(tenant, profile)

        strategy_cls = STRATEGIES[profile.orchestration_pattern.value]
        self.strategy = strategy_cls(
            profile, provider, self.tools, self.context
        )

    @classmethod
    def from_names(
        cls, profile_name: str, tenant_id: str, provider: LLMProvider
    ) -> Orchestrator:
        profile = load_profile(profile_name)
        tenant = load_tenant(tenant_id)
        return cls(profile, tenant, provider)

    def run(self, task: str) -> RunState:
        """Ejecuta una tarea de principio a fin y devuelve la traza completa."""
        state = RunState(
            tenant_id=self.context.tenant_id,
            profile=self.profile.name,
            task=task,
            metadata={
                "plan": self.context.plan,
                "pattern": self.profile.orchestration_pattern.value,
                "provider": self.provider.name,
                "enabled_agents": sorted(self.context.enabled_agents),
            },
        )
        logger.info(
            "run.start",
            extra={"tenant_id": state.tenant_id, "run_id": state.run_id},
        )

        try:
            self.strategy.execute(state)
        except BudgetExceeded as exc:
            self._halt(state, RunStatus.BUDGET_EXCEEDED, str(exc))
        except LimitExceeded as exc:
            self._halt(state, RunStatus.MAX_ITERATIONS, str(exc))
        except Exception as exc:
            logger.exception("run.failed", extra={"run_id": state.run_id})
            self._halt(state, RunStatus.FAILED, f"{type(exc).__name__}: {exc}")

        logger.info(
            "run.end",
            extra={
                "tenant_id": state.tenant_id,
                "run_id": state.run_id,
                "status": state.status.value,
                "cost_usd": state.usage.cost_usd,
            },
        )
        return state

    # --- internos --------------------------------------------------------

    @staticmethod
    def _default_registry() -> ToolRegistry:
        registry = ToolRegistry()
        registry.register_many(default_tools())
        return registry

    @staticmethod
    def _halt(state: RunState, status: RunStatus, message: str) -> None:
        state.record(
            Step(
                type=StepType.ESCALATION,
                actor="engine",
                summary=f"Corrida detenida: {status.value}",
                output=message,
                error=message,
            )
        )
        state.finish(status, message)
