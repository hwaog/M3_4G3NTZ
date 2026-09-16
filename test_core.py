"""Suite de Fase 1: valida el núcleo, la tenancy y ambos patrones."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config.loader import ConfigError, load_profile, load_tenant  # noqa: E402
from core.config.schema import AgentConfig, ProfileConfig, TenantConfig  # noqa: E402
from core.llm.mock_client import MockProvider  # noqa: E402
from core.orchestrator.engine import Orchestrator  # noqa: E402
from core.orchestrator.state import RunStatus, StepType  # noqa: E402
from core.tenancy.context import TenantContext  # noqa: E402
from core.tools.common.builtin import default_tools  # noqa: E402
from core.tools.registry import ToolNotAllowed, ToolRegistry  # noqa: E402


# --- configuración -------------------------------------------------------


def test_profile_carga_y_resuelve_prompts():
    profile = load_profile("demo_asistentes")
    assert profile.orchestration_pattern.value == "router"
    assert {a.id for a in profile.agents} == {"soporte", "agenda", "investigacion"}
    for agent in profile.agents:
        assert agent.system_prompt, f"prompt vacío en {agent.id}"


def test_modelo_invalido_es_rechazado():
    with pytest.raises(ValueError, match="Modelo desconocido"):
        AgentConfig(
            id="x", description="descripción válida", model="gpt-inexistente",
            system_prompt="hola",
        )


def test_router_sin_config_falla():
    with pytest.raises(ValueError, match="requiere la clave 'router'"):
        ProfileConfig(
            name="p", display_name="P", orchestration_pattern="router",
            agents=[AgentConfig(id="a", description="descripción", system_prompt="x")],
        )


def test_ids_duplicados_fallan():
    agent = AgentConfig(id="a", description="descripción", system_prompt="x")
    with pytest.raises(ValueError, match="duplicados"):
        ProfileConfig(
            name="p", display_name="P",
            orchestration_pattern="supervisor_worker",
            orchestrator=AgentConfig(
                id="o", description="orquestador de prueba", system_prompt="x"
            ),
            agents=[agent, agent.model_copy()],
        )


def test_scaffold_template_es_valido(tmp_path):
    """La plantilla debe validar: es la base de toda vertical nueva."""
    dest = tmp_path / "template_supervisor"
    shutil.copytree(ROOT / "profiles" / "_template", dest)
    profile = load_profile("template_supervisor", profiles_dir=tmp_path)
    assert profile.orchestration_pattern.value == "supervisor_worker"
    assert profile.orchestrator is not None


# --- tenancy -------------------------------------------------------------


def test_limite_mas_restrictivo_gana():
    profile = load_profile("demo_asistentes")  # max_cost_usd 0.50
    tenant = TenantConfig(
        tenant_id="t1", display_name="T1", profile="demo_asistentes",
        max_cost_per_run_usd=0.02,
    )
    ctx = TenantContext.from_config(tenant, profile)
    assert ctx.limits.max_cost_usd == 0.02


def test_tenant_no_puede_habilitar_agente_inexistente():
    profile = load_profile("demo_asistentes")
    tenant = TenantConfig(
        tenant_id="t2", display_name="T2", profile="demo_asistentes",
        enabled_agents=["no_existe"],
    )
    with pytest.raises(ValueError, match="agentes inexistentes"):
        TenantContext.from_config(tenant, profile)


def test_tenant_de_otro_perfil_es_rechazado():
    profile = load_profile("demo_asistentes")
    tenant = TenantConfig(
        tenant_id="t3", display_name="T3", profile="otro_perfil"
    )
    with pytest.raises(ValueError, match="está asignado al perfil"):
        Orchestrator(profile=profile, tenant=tenant, provider=MockProvider())


def test_tenant_inactivo_no_corre():
    profile = load_profile("demo_asistentes")
    tenant = TenantConfig(
        tenant_id="t4", display_name="T4", profile="demo_asistentes", active=False
    )
    with pytest.raises(ValueError, match="inactivo"):
        Orchestrator(profile=profile, tenant=tenant, provider=MockProvider())


# --- permisos de herramientas -------------------------------------------


def test_agente_no_puede_usar_herramienta_no_permitida():
    registry = ToolRegistry()
    registry.register_many(default_tools())
    with pytest.raises(ToolNotAllowed):
        registry.execute(
            "calendar_check", {"query": "martes"},
            allowed=["kb_search"],
            context={"tenant_id": "t", "run_id": "r", "agent_id": "soporte"},
        )


def test_herramienta_inexistente_falla_al_validar():
    registry = ToolRegistry()
    registry.register_many(default_tools())
    with pytest.raises(KeyError, match="no registradas"):
        registry.validate_requested(["tool_fantasma"], "soporte")


def test_argumentos_faltantes_devuelven_error_no_excepcion():
    registry = ToolRegistry()
    registry.register_many(default_tools())
    result = registry.execute(
        "kb_search", {}, allowed=["kb_search"],
        context={"tenant_id": "t", "run_id": "r", "agent_id": "soporte"},
    )
    assert not result.ok
    assert "requeridos" in result.error


# --- patrón router -------------------------------------------------------


def _orchestrator(tenant_id: str = "acme-demo") -> Orchestrator:
    return Orchestrator(
        profile=load_profile("demo_asistentes"),
        tenant=load_tenant(tenant_id),
        provider=MockProvider(),
    )


def test_router_enruta_a_soporte():
    state = _orchestrator().run("¿Cuál es el horario y el precio del plan?")
    assert state.status is RunStatus.COMPLETED
    routing = [s for s in state.steps if s.type is StepType.ROUTING][0]
    assert routing.metadata["agent_id"] == "soporte"


def test_router_enruta_a_agenda():
    state = _orchestrator().run("Necesito agendar una reunión para el martes")
    routing = [s for s in state.steps if s.type is StepType.ROUTING][0]
    assert routing.metadata["agent_id"] == "agenda"


def test_router_escala_si_no_hay_coincidencia():
    state = _orchestrator().run("qwerty zxcvb asdfg")
    assert state.status is RunStatus.ESCALATED
    assert any(s.type is StepType.ESCALATION for s in state.steps)


def test_plan_trial_no_accede_a_agentes_fuera_de_su_plan():
    """El tenant trial solo tiene 'soporte': pedir agenda debe escalar."""
    orch = _orchestrator("prospecto-trial")
    assert set(orch.strategy.agents) == {"soporte"}
    state = orch.run("Quiero agendar una cita para el jueves")
    assert state.status is RunStatus.ESCALATED


def test_toda_corrida_lleva_tenant_id():
    state = _orchestrator().run("¿Cuál es el horario?")
    assert state.tenant_id == "acme-demo"
    assert state.usage.cost_usd > 0


def test_tope_de_costo_detiene_la_corrida():
    profile = load_profile("demo_asistentes")
    tenant = TenantConfig(
        tenant_id="pobre", display_name="Tope mínimo", profile="demo_asistentes",
        max_cost_per_run_usd=0.0000001,
    )
    orch = Orchestrator(profile=profile, tenant=tenant, provider=MockProvider())
    state = orch.run("¿Cuál es el horario y el precio del plan?")
    assert state.status is RunStatus.BUDGET_EXCEEDED


# --- patrón supervisor-worker -------------------------------------------


def test_supervisor_delega_y_sintetiza(tmp_path):
    dest = tmp_path / "template_supervisor"
    shutil.copytree(ROOT / "profiles" / "_template", dest)
    profile = load_profile("template_supervisor", profiles_dir=tmp_path)
    tenant = TenantConfig(
        tenant_id="sup-test", display_name="Supervisor test",
        profile="template_supervisor", max_cost_per_run_usd=1.0,
    )
    orch = Orchestrator(profile=profile, tenant=tenant, provider=MockProvider())
    state = orch.run("Prepara un informe de desempeño trimestral")

    assert state.status is RunStatus.COMPLETED
    delegated = {s.summary for s in state.steps if s.type is StepType.DELEGATION}
    assert len(delegated) == 2, "el supervisor debe delegar en ambos workers"
    assert any(s.type is StepType.SYNTHESIS for s in state.steps)


# --- trazabilidad --------------------------------------------------------


def test_traza_es_serializable_y_persistible(tmp_path):
    from core.observability.tracer import render_trace, save_run

    state = _orchestrator().run("¿Cuál es el horario?")
    path = save_run(state, tmp_path)
    assert path.exists()
    assert path.parent.name == "acme-demo", "las trazas se aíslan por cliente"
    assert "Corrida" in render_trace(state)


def test_perfil_inexistente_da_error_claro():
    with pytest.raises(ConfigError, match="No se encontró"):
        load_profile("perfil_que_no_existe")
