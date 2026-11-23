"""Punkt wejścia doc-agents.

Co robi: wczytuje argumenty i config.yaml, przygotowuje kontekst uruchomienia (RunContext)
i uruchamia graf LangGraph (doc_agents/graph.py), a na końcu wypisuje podsumowanie ze stanu
końcowego grafu. Na tym etapie graf skanuje projekt (bez modelu językowego, wynik:
output/project_map.json), tworzy plan pracy zespołu (agent planner, wynik: output/plan.json)
równolegle analizuje jednostki kodu (analitycy, wyniki: output/notes/), składa dokumentację (redaktor,
output/document_NN.md) i recenzuje ją (recenzent, output/review_NN.json) - odrzucony dokument wraca
do redaktora, najwyżej limits.max_review_rounds razy. Wynik końcowy: output/final.md.

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
from doc_agents.context import create_run_context
from doc_agents.graph import run_graph
from doc_agents.schemas import Plan, ProjectMap, ReviewResult


# --- Wyświetlanie ---


def print_summary(
    config_path: str,
    project_map: ProjectMap,
    map_path: str,
    plan: Plan,
    plan_path: str,
    notes_count: int,
    notes_dir: str,
    missing: list[str],
    review: ReviewResult,
    review_round: int,
    final_path: str,
) -> None:
    """Wypisuje podsumowanie przebiegu: plik configu, projekt, technologię, liczbę plików, punkty wejścia,
    jednostki kodu do analizy, ścieżkę mapy projektu, skrót planu (zadania, rozdziały) i ścieżkę planu
    liczbę notatek analityków i ich katalog, braki w dokumencie, wynik recenzji (liczba rund, decyzja,
    nierozwiązane problemy) i ścieżkę dokumentu końcowego.

    Po co: na obecnym etapie to widoczny efekt uruchomienia main.py - od razu widać, czy projekt
    został rozpoznany i jak planner zaplanował pracę, a szczegóły są w project_map.json i plan.json.
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
    print(f"  plan: {len(plan.tasks)} zadań analityków, {len(plan.sections)} rozdziałów części opisowej")
    for section in plan.sections:
        print(f"    {section.title}")
    print(f"  plan pracy:    {plan_path}")
    print(f"  notatki analityków: {notes_count} z {len(plan.tasks)} zadań")
    print(f"  katalog notatek: {notes_dir}")
    print("  braki w dokumencie (pola formalne i rozdziały wymagane):")
    if not missing:
        print("    brak")
    for name in missing:
        print(f"    {name}")
    decyzja = "nie zaakceptowany (osiągnięto limit recenzji)"
    if review.approved:
        decyzja = "zaakceptowany"
    print(f"  recenzja: {review_round} rund(y), dokument {decyzja}")
    if not review.approved:
        print("  nierozwiązane uwagi recenzenta (szczegóły w output/review_NN.json):")
        for issue in review.issues:
            print(f"    - {issue}")
    print(f"  DOKUMENTACJA:  {final_path}")


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
    """Uruchamia program: argumenty -> config -> kontekst uruchomienia -> graf -> podsumowanie ze stanu końcowego.

    Po co: spis treści całego przebiegu. Etapy (skan, planner, analitycy, redaktor, recenzent)
    są węzłami grafu w doc_agents/graph.py i same zapisują swoje wyniki w output/ -
    tu tylko uruchamiamy graf i pokazujemy, co powstało.
    """
    args = parse_args()
    config = load_config(args.config)

    context = create_run_context(config)
    final_state = run_graph(args.project, context)
    map_path = context.run_store.path("project_map.json")
    plan_path = context.run_store.path("plan.json")
    notes_dir = context.run_store.path("notes")
    final_path = context.run_store.path("final.md")

    print_summary(
        args.config,
        final_state["project_map"],
        map_path,
        final_state["plan"],
        plan_path,
        len(final_state["notes"]),
        notes_dir,
        final_state["missing"],
        final_state["review"],
        final_state["review_round"],
        final_path,
    )


if __name__ == "__main__":
    main()
