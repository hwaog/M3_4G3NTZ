"""Construcción de agentes a partir del perfil y el tenant."""

from __future__ import annotations

from core.agents.base_agent import BaseAgent
from core.config.schema import ProfileConfig
from core.llm.provider import LLMProvider
from core.tenancy.context import TenantContext
from core.tools.registry import ToolRegistry


def build_agents(
    profile: ProfileConfig,
    provider: LLMProvider,
    tools: ToolRegistry,
    tenant: TenantContext,
) -> dict[str, BaseAgent]:
    """Instancia solo los agentes que el plan del cliente tiene habilitados."""
    agents: dict[str, BaseAgent] = {}
    for cfg in profile.agents:
        if not tenant.allows_agent(cfg.id):
            continue
        tools.validate_requested(cfg.tools, cfg.id)
        agents[cfg.id] = BaseAgent(config=cfg, provider=provider, tools=tools)

    if not agents:
        raise ValueError(
            f"El tenant '{tenant.tenant_id}' no tiene ningún agente habilitado "
            f"en el perfil '{profile.name}'."
        )
    return agents
