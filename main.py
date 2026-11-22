"""Punkt wejścia doc-agents.

Co robi: wczytuje argumenty i config.yaml, skanuje wskazany projekt (bez modelu językowego),
zapisuje mapę projektu do output/project_map.json i wypisuje podsumowanie. Docelowo w tym
miejscu uruchomi się graf agentów generujący dokumentację.

Uruchomienie z katalogu repo:
    python main.py --project <ścieżka do projektu>
    python main.py --project <ścieżka do projektu> --config <ścieżka do config.yaml>

Domyślny config to config.yaml leżący obok main.py, więc program działa niezależnie od
katalogu, z którego go uruchamiamy. Katalog output/ (obok main.py) zawiera wyniki tylko
ostatniego uruchomienia - przy każdym starcie jest czyszczony.
"""

import argparse
import os

from doc_agents.config import load_config
from doc_agents.output import create_run_store
from doc_agents.scanner import build_project_map
from doc_agents.schemas import ProjectMap


# --- Wyświetlanie ---


def print_summary(config_path: str, project_map: ProjectMap, map_path: str) -> None:
    """Wypisuje podsumowanie skanu: plik configu, projekt, technologię, liczbę plików, punkty wejścia,
    jednostki kodu do analizy i ścieżkę zapisanej mapy projektu.

    Po co: na obecnym etapie to widoczny efekt uruchomienia main.py - od razu widać, czy projekt
    został rozpoznany i co trafi do analizy, a szczegóły są w zapisanym project_map.json.
    """
    technology_name = "(nie rozpoznano)"
    if project_map.technology != "":
        technology_name = project_map.technology

    print("doc-agents - skan projektu")
    print(f"  config:      {os.path.abspath(config_path)}")
    print(f"  projekt:     {project_map.project_name} ({project_map.root})")
    print(f"  technologia: {technology_name}")
    print(f"  pliki:       {len(project_map.files)}")
    print("  punkty wejścia:")
    for path in project_map.entrypoints:
        print(f"    {path}")
    print(f"  jednostki kodu do analizy: {len(project_map.code_units)}")
    for unit in project_map.code_units:
        print(f"    {unit.name}")
    print(f"  mapa projektu: {map_path}")


# --- Uruchomienie ---


def parse_args():
    """Odczytuje argumenty wiersza poleceń: --project (wymagany, musi być istniejącym katalogiem)
    i --config (domyślnie config.yaml obok main.py).

    Po co: jeden punkt, w którym zdefiniowane są opcje programu. Sprawdzenie katalogu projektu
    od razu daje czytelny komunikat zamiast pustej mapy przy literówce w ścieżce; domyślna
    ścieżka configu liczona względem main.py sprawia, że program działa z dowolnego katalogu.
    """
    default_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    parser = argparse.ArgumentParser(description="Generowanie dokumentacji projektu przez zespół agentów.")
    parser.add_argument("--project", required=True, help="ścieżka do katalogu dokumentowanego projektu")
    parser.add_argument("--config", default=default_config, help="ścieżka do pliku konfiguracyjnego (domyślnie: config.yaml obok main.py)")
    args = parser.parse_args()
    if not os.path.isdir(args.project):
        parser.error(f"--project: katalog nie istnieje: {args.project}")
    return args


def main():
    """Uruchamia program: argumenty -> config -> skan projektu -> zapis project_map.json -> podsumowanie.

    Po co: spis treści całego przebiegu - tu będą dochodzić kolejne etapy (planner, analitycy,
    redaktor, recenzent), a szczegóły każdego z nich zostają w osobnych funkcjach i modułach.
    """
    args = parse_args()
    config = load_config(args.config)

    project_map = build_project_map(args.project, config.scan)
    run_store = create_run_store()
    map_path = run_store.save_json("project_map.json", project_map)

    print_summary(args.config, project_map, map_path)


if __name__ == "__main__":
    main()
