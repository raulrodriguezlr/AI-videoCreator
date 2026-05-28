"""
main.py — Punto de entrada de AI-videoCreator v2.0
Toda la lógica de interfaz de línea de comandos se ha movido a src/cli.py.
Toda la lógica de orquestación central se ha movido a src/engines/pipeline_orchestrator.py.
"""
from src.cli import run_cli

if __name__ == "__main__":
    run_cli()
