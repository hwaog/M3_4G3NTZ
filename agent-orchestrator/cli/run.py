"""CLI del orquestador.

Ejemplos:
    python -m cli.run list
    python -m cli.run --tenant acme-demo --task "¿Cuál es el horario?"
    python -m cli.run --tenant acme-demo --task "Agenda una llamada" --verbose
    python -m cli.run --tenant acme-demo --task "..." --provider claude
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config.loader import (  # noqa: E402
    ConfigError,
    list_profiles,
    list_tenants,
    load_profile,
    load_tenant,
)
from core.llm.claude_client import ClaudeProvider  # noqa: E402
from core.llm.mock_client import MockProvider  # noqa: E402
from core.observability.tracer import render_trace, save_run  # noqa: E402
from core.orchestrator.engine import Orchestrator  # noqa: E402

RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def _build_provider(name: str):
    if name == "mock":
        return MockProvider()
    if name == "claude":
        return ClaudeProvider()
    raise ValueError(f"Proveedor desconocido: {name}")


def _cmd_list() -> int:
    profiles = list_profiles()
    tenants = list_tenants()

    print("\nPerfiles disponibles:")
    for name in profiles:
        profile = load_profile(name)
        agent_ids = ", ".join(a.id for a in profile.agents)
        print(f"  {name}")
        print(f"    patrón : {profile.orchestration_pattern.value}")
        print(f"    agentes: {agent_ids}")

    print("\nClientes (tenants):")
    for tenant_id in tenants:
        tenant = load_tenant(tenant_id)
        scope = ", ".join(tenant.enabled_agents) if tenant.enabled_agents else "todos"
        estado = "activo" if tenant.active else "inactivo"
        print(f"  {tenant_id}  [{tenant.plan}] {estado}")
        print(f"    perfil  : {tenant.profile}")
        print(f"    agentes : {scope}")
        print(f"    tope/mes: ${tenant.monthly_budget_usd:.2f}")
    print()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    tenant = load_tenant(args.tenant)
    profile = load_profile(args.profile or tenant.profile)
    provider = _build_provider(args.provider)

    orchestrator = Orchestrator(
        profile=profile, tenant=tenant, provider=provider
    )
    state = orchestrator.run(args.task)

    print(render_trace(state, verbose=args.verbose))

    if args.save:
        path = save_run(state, RUNS_DIR)
        print(f"Traza guardada en: {path}\n")

    return 0 if state.status.value in {"completed", "escalated"} else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Orquestador multi-tenant de agentes de IA (Fase 1).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "list"],
        help="'run' ejecuta una tarea; 'list' muestra perfiles y clientes.",
    )
    parser.add_argument("--tenant", "-c", help="Id del cliente.")
    parser.add_argument("--task", "-t", help="Tarea o mensaje entrante.")
    parser.add_argument(
        "--profile", "-p", help="Forzar un perfil distinto al del tenant."
    )
    parser.add_argument(
        "--provider",
        default="mock",
        choices=["mock", "claude"],
        help="Backend del modelo. 'mock' no consume API (por defecto).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Muestra la salida de cada paso."
    )
    parser.add_argument(
        "--save", "-s", action="store_true", help="Guarda la traza en runs/."
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            return _cmd_list()
        if not args.tenant or not args.task:
            parser.error("'run' requiere --tenant y --task.")
        return _cmd_run(args)
    except ConfigError as exc:
        print(f"\nError de configuración:\n{exc}\n", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n{type(exc).__name__}: {exc}\n", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
