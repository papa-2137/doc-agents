"""Punkt wejścia doc-agents: argumenty → config → (docelowo) graf agentów."""

import argparse
import os

from doc_agents.config import load_config

# Domyślny config leży obok main.py - działa niezależnie od katalogu, z którego uruchamiamy.
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def parse_args():
    parser = argparse.ArgumentParser(description="Generowanie dokumentacji projektu przez zespół agentów.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="ścieżka do pliku konfiguracyjnego (domyślnie: config.yaml obok main.py)")
    parser.add_argument("--project", help="ścieżka do dokumentowanego projektu (na razie opcjonalna)")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    print("doc-agents - podsumowanie")
    print(f"  config:  {os.path.abspath(args.config)}")
    print(f"  projekt: {os.path.abspath(args.project) if args.project else '(nie podano)'}")

    print("  profile modeli:")
    for name, profile in config.llm.profiles.items():
        print(f"    {name}: {profile.model} ({profile.provider})")

    print("  agenci:")
    for agent, profile in config.llm.agents.items():
        print(f"    {agent} -> {profile}")

    print("  ścieżki:")
    print(f"    prompts:        {config.paths.prompts}")
    print(f"    knowledge_base: {config.paths.knowledge_base}")
    print(f"    runs:           {config.paths.runs}")


if __name__ == "__main__":
    main()
