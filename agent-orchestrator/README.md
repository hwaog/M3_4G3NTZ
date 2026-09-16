# Orquestador multi-tenant de agentes de IA

Motor de orquestación agnóstico de dominio con perfiles enchufables. El mismo
núcleo sirve para cualquier vertical (asistentes virtuales, marketing digital,
desarrollo web): una vertical nueva es una carpeta de configuración, no código.

**Estado: Fase 1 completa.** Núcleo funcional, multi-tenant, con los dos
patrones de orquestación y agentes dummy.

## Instalación

**Requisitos: Python 3.11 o superior, y pip 21.3 o superior.**

```bash
python3 --version                        # debe ser 3.11+
python3 -m venv venv && source venv/bin/activate
python -m pip install --upgrade pip      # el pip del venv suele venir desactualizado
python -m pip install -e ".[dev]"
cp .env.example .env                     # solo si vas a usar --provider claude
```

Si la instalación editable falla, el proyecto funciona igual sin ella: basta
con instalar las dependencias y ejecutar desde la raíz del repositorio.

```bash
python -m pip install anthropic pydantic pyyaml pytest ruff
python -m cli.run list
```

## Uso

```bash
# Ver perfiles y clientes configurados
python -m cli.run list

# Ejecutar una tarea (modo simulado: no consume API)
python -m cli.run --tenant acme-demo --task "¿Cuál es el horario de atención?"

# Con detalle de cada paso y guardando la traza en runs/
python -m cli.run --tenant acme-demo --task "Agenda una reunión" --verbose --save

# Contra la API real de Claude
python -m cli.run --tenant acme-demo --task "..." --provider claude
```

El proveedor por defecto es `mock`: ejecuta el sistema completo (routing,
permisos, herramientas, trazas, conteo de costo) sin llamar a la API. Esto
permite desarrollar, testear en CI y ensayar demos con costo cero.

## Arquitectura

```
core/            Núcleo reutilizable. No conoce ninguna vertical.
  config/        Esquemas Pydantic + carga de profile.yaml y tenants
  llm/           Abstracción del proveedor: ClaudeProvider y MockProvider
  tools/         Contrato de herramienta, registro y permisos
  agents/        Agente base (loop de tool use) y fábrica
  orchestrator/  Estado, patrones de coordinación y motor
  tenancy/       Contexto de cliente y guardarraíles de costo
  observability/ Logging estructurado y reporte de corrida

profiles/        Verticales enchufables (no se toca core/ para agregar una)
  demo_asistentes/   Perfil piloto: router + 3 asistentes
  _template/         Andamio para crear una vertical nueva

tenants/         Un YAML por cliente del servicio gestionado
cli/             Interfaz de línea de comandos
tests/           Suite de Fase 1 (21 tests)
```

### Patrones de orquestación

| Patrón | Cuándo usarlo |
|---|---|
| `router` | Llegan solicitudes sueltas y hay que decidir quién las atiende. Incluye ruta explícita de escalamiento a humano. Es el del paquete de asistentes virtuales. |
| `supervisor_worker` | Una tarea compleja se descompone en subtareas que luego hay que integrar. Es el de informes, campañas y auditorías. |

Se cambia de uno a otro editando una línea del `profile.yaml`.

## Multi-tenancy

Toda unidad de trabajo nace atada a un `tenant_id`; no existe ruta de ejecución
sin cliente asociado. Cada tenant:

- instancia un perfil sin modificarlo,
- activa un subconjunto de agentes según su plan (`enabled_agents`),
- tiene su propio tope de gasto, y
- guarda sus trazas en un directorio propio bajo `runs/`.

Cuando los límites del perfil y los del cliente difieren, **siempre gana el más
restrictivo**: un perfil generoso no puede exceder lo contratado.

Los dos tenants de ejemplo demuestran el gating por plan: `prospecto-trial`
solo tiene `soporte` habilitado, así que una solicitud de agendamiento escala
a humano en vez de atenderse.

## Crear una vertical nueva

```bash
cp -r profiles/_template profiles/marketing_digital
```

Luego edita `profile.yaml` (el campo `name` debe coincidir con el nombre de la
carpeta), escribe los prompts en `agents/*.md` y registra las herramientas
específicas del dominio. **No se modifica `core/`.**

## Guardarraíles implementados

- Permisos de herramienta por agente: un agente solo invoca lo que su
  `profile.yaml` lista explícitamente.
- Tope de costo por corrida, con corte inmediato al alcanzarlo.
- Máximo de iteraciones y de llamadas a herramientas.
- Fallos de herramienta aislados: no tumban el loop del agente, vuelven como
  `tool_result` con error para que el agente reaccione.
- Validación estricta de configuración al cargar: un typo en un modelo o una
  herramienta inexistente falla al arrancar, no a mitad de una corrida.

## Testing

```bash
make test        # 21 tests, sin consumir API
make lint
make demo        # recorre los casos principales
```

## Notas

- La tabla de precios en `core/llm/provider.py` es para estimación interna.
  Verifícala contra <https://claude.com/pricing> antes de facturar a un cliente.
- El vault de credenciales por cliente y la persistencia del gasto mensual
  acumulado llegan en Fase 2; en Fase 1 los límites se aplican en memoria
  durante la corrida.
