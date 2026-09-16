"""Contexto de cliente (tenant) y aplicación de guardarraíles.

En Fase 1 los límites se aplican en memoria durante la corrida. La Fase 2
añade el vault de credenciales y la persistencia del gasto acumulado del mes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config.schema import LimitsConfig, ProfileConfig, TenantConfig


class BudgetExceeded(RuntimeError):
    """Se alcanzó el tope de gasto del cliente para esta corrida."""


class LimitExceeded(RuntimeError):
    """Se alcanzó un guardarraíl de ejecución (iteraciones o tool calls)."""


@dataclass
class TenantContext:
    """Todo lo que el núcleo necesita saber del cliente durante una corrida."""

    tenant_id: str
    display_name: str
    plan: str
    limits: LimitsConfig
    enabled_agents: set[str] = field(default_factory=set)
    credentials: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls, tenant: TenantConfig, profile: ProfileConfig
    ) -> TenantContext:
        """Combina los límites del perfil con los topes propios del cliente.

        Siempre gana el más restrictivo: un perfil generoso no puede exceder
        el tope contratado por el cliente.
        """
        limits = profile.limits.model_copy(deep=True)
        if tenant.max_cost_per_run_usd is not None:
            limits.max_cost_usd = min(limits.max_cost_usd, tenant.max_cost_per_run_usd)

        profile_agent_ids = {a.id for a in profile.agents}
        enabled = set(tenant.enabled_agents) or set(profile_agent_ids)
        unknown = enabled - profile_agent_ids
        if unknown:
            raise ValueError(
                f"Tenant '{tenant.tenant_id}' habilita agentes inexistentes "
                f"en el perfil '{profile.name}': {sorted(unknown)}"
            )

        return cls(
            tenant_id=tenant.tenant_id,
            display_name=tenant.display_name,
            plan=tenant.plan,
            limits=limits,
            enabled_agents=enabled,
        )

    def allows_agent(self, agent_id: str) -> bool:
        return agent_id in self.enabled_agents

    def check_budget(self, spent_usd: float) -> None:
        if spent_usd >= self.limits.max_cost_usd:
            raise BudgetExceeded(
                f"Tenant '{self.tenant_id}': gasto ${spent_usd:.4f} alcanzó el "
                f"tope de ${self.limits.max_cost_usd:.4f} para esta corrida."
            )

    def check_tool_calls(self, count: int) -> None:
        if count >= self.limits.max_tool_calls:
            raise LimitExceeded(
                f"Tenant '{self.tenant_id}': se alcanzó el máximo de "
                f"{self.limits.max_tool_calls} llamadas a herramientas."
            )
