"""Carga de perfiles de dominio y tenants desde disco."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from core.config.schema import AgentConfig, ProfileConfig, TenantConfig

PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"
TENANTS_DIR = Path(__file__).resolve().parents[2] / "tenants"


class ConfigError(RuntimeError):
    """Error de configuración legible para el operador del servicio."""


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"No se encontró el archivo: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"El archivo {path} no contiene un mapeo YAML válido.")
    return data


def _resolve_prompt(agent: AgentConfig, base_path: Path) -> None:
    """Sustituye system_prompt_file por el contenido real del archivo."""
    if agent.system_prompt:
        return
    prompt_path = base_path / agent.system_prompt_file
    if not prompt_path.exists():
        raise ConfigError(
            f"Agente '{agent.id}': no existe el prompt {prompt_path}"
        )
    agent.system_prompt = prompt_path.read_text(encoding="utf-8").strip()


def load_profile(name: str, profiles_dir: Path | None = None) -> ProfileConfig:
    """Carga un perfil por nombre y resuelve sus prompts en disco."""
    root = profiles_dir or PROFILES_DIR
    base_path = root / name
    data = _read_yaml(base_path / "profile.yaml")

    try:
        profile = ProfileConfig(**data, base_path=base_path)
    except ValidationError as exc:
        raise ConfigError(f"Perfil '{name}' inválido:\n{exc}") from exc

    # Los directorios con guion bajo son andamios (scaffolds): se copian y
    # renombran para crear una vertical nueva, no se ejecutan tal cual.
    if not name.startswith("_") and profile.name != name:
        raise ConfigError(
            f"El perfil en 'profiles/{name}/' declara name: '{profile.name}'. "
            f"Deben coincidir para que los tenants lo referencien sin ambigüedad."
        )

    for agent in profile.agents:
        _resolve_prompt(agent, base_path)
    if profile.orchestrator:
        _resolve_prompt(profile.orchestrator, base_path)

    return profile


def load_tenant(tenant_id: str, tenants_dir: Path | None = None) -> TenantConfig:
    """Carga la configuración de un cliente del servicio gestionado."""
    root = tenants_dir or TENANTS_DIR
    data = _read_yaml(root / f"{tenant_id}.yaml")
    try:
        return TenantConfig(**data)
    except ValidationError as exc:
        raise ConfigError(f"Tenant '{tenant_id}' inválido:\n{exc}") from exc


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    root = profiles_dir or PROFILES_DIR
    if not root.exists():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "profile.yaml").exists() and not p.name.startswith("_")
    )


def list_tenants(tenants_dir: Path | None = None) -> list[str]:
    root = tenants_dir or TENANTS_DIR
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.yaml"))
