.PHONY: install install-deps test lint demo list

# Requiere pip >= 21.3. Si falla, usa 'make install-deps'.
install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

# Alternativa sin instalación editable: solo dependencias.
# El proyecto corre igual con 'python -m cli.run' desde esta carpeta.
install-deps:
	python -m pip install anthropic pydantic pyyaml pytest ruff

test:
	python -m pytest tests/ -v

lint:
	ruff check core cli tests

list:
	python -m cli.run list

demo:
	@python -m cli.run --tenant acme-demo --task "¿Cuál es el horario y el precio del plan?" -v
	@python -m cli.run --tenant acme-demo --task "Necesito agendar una reunión el martes" -v
	@python -m cli.run --tenant prospecto-trial --task "Quiero agendar una cita" -v
