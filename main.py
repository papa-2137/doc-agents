"""Punkt wejścia doc-agents.

Co robi: wczytuje argumenty i config.yaml, a docelowo uruchomi graf agentów generujący
dokumentację wskazanego projektu. Na obecnym etapie wypisuje podsumowanie konfiguracji
(profile modeli, przypisania agentów, ścieżki) - to szybki test, że szkielet działa.

Uruchomienie z katalogu repo:
    python main.py
    python main.py --project <ścieżka do projektu> --config <ścieżka do config.yaml>

Domyślny config to config.yaml leżący obok main.py, więc program działa niezależnie od
katalogu, z którego go uruchamiamy.
"""

import argparse
import os

from doc_agents.config import load_config


# --- Wyświetlanie ---


def print_summary(config_path: str, project_path: str | None, config) -> None:
    """Wypisuje podsumowanie wczytanej konfiguracji: plik configu, projekt, profile modeli, przypisania agentów i ścieżki.

    Po co: na obecnym etapie to jedyny widoczny efekt uruchomienia main.py - pozwala szybko sprawdzić,
    że config wczytał się poprawnie i ścieżki wskazują właściwe miejsca, zanim dojdzie skanowanie i agenci.
    """
    print("doc-agents - podsumowanie")
    print(f"  config:  {os.path.abspath(config_path)}")
    print(f"  projekt: {os.path.abspath(project_path) if project_path else '(nie podano)'}")

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


# --- Uruchomienie ---


def parse_args():
    """Odczytuje argumenty wiersza poleceń: --config (domyślnie config.yaml obok main.py) i --project.

    Po co: jeden punkt, w którym zdefiniowane są opcje programu; domyślna ścieżka configu liczona
    względem main.py sprawia, że program działa niezależnie od katalogu, z którego go uruchamiamy.
    """
    default_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    parser = argparse.ArgumentParser(description="Generowanie dokumentacji projektu przez zespół agentów.")
    parser.add_argument("--config", default=default_config, help="ścieżka do pliku konfiguracyjnego (domyślnie: config.yaml obok main.py)")
    parser.add_argument("--project", help="ścieżka do dokumentowanego projektu (na razie opcjonalna)")
    args = parser.parse_args()
    return args


def main():
    """Uruchamia program: argumenty -> wczytanie configu -> podsumowanie.

    Po co: spis treści całego przebiegu - tu będą dochodzić kolejne etapy (skan projektu, graf agentów),
    a szczegóły każdego z nich zostają w osobnych funkcjach i modułach.
    """
    args = parse_args()
    config = load_config(args.config)
    print_summary(args.config, args.project, config)


if __name__ == "__main__":
    main()
