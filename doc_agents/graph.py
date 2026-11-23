"""Graf LangGraph: kolejność etapów generowania dokumentacji.

Co robi: build_graph() składa graf z węzłów i krawędzi, run_graph() uruchamia go dla projektu.
Na tym etapie graf ma jeden węzeł:
    START -> scan -> END
scan buduje mapę projektu (scanner.build_project_map), zapisuje ją do output/project_map.json
i dopisuje do stanu. Kolejne kroki dodadzą węzły agentów (planner, analitycy, redaktor, recenzent).

Jak czytać graf:
    - węzeł = zwykła funkcja (state, runtime) -> dict: czyta stan, zwraca tylko zmienione pola,
    - krawędź = kolejność węzłów (START i END to wbudowane początek i koniec),
    - runtime.context = RunContext z zależnościami (config, modele, zapis wyników) - patrz context.py,
    - każdy węzeł sam zapisuje swój wynik w output/ (po przebiegu widać wynik każdego etapu,
      także gdy coś padnie w połowie).

Test ręczny z katalogu repo (uruchamia graf i wypisuje stan końcowy):
    python -m doc_agents.graph <katalog projektu>
"""

import os
import sys

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.scanner import build_project_map
from doc_agents.state import DocState


# --- Węzły ---


def scan_node(state: DocState, runtime: Runtime[RunContext]) -> dict:
    """Węzeł scan: buduje mapę projektu z state["project_path"], zapisuje ją jako project_map.json i zwraca ją do stanu.

    Po co: pierwszy etap przebiegu - cała wiedza o projekcie bez modelu językowego, na której
    pracują kolejni agenci. Zwraca tylko pole project_map (częściowa aktualizacja stanu).
    """
    context = runtime.context
    project_map = build_project_map(state["project_path"], context.config.scan)
    context.run_store.save_json("project_map.json", project_map)

    aktualizacja_stanu = {"project_map": project_map}
    return aktualizacja_stanu


# --- Graf ---


def build_graph():
    """Składa i kompiluje graf: START -> scan -> END, ze stanem DocState i kontekstem RunContext.

    Po co: jedno miejsce, w którym widać wszystkie etapy i ich kolejność; kolejne węzły
    dopisuje się tutaj. compile() sprawdza poprawność grafu (np. brakujące krawędzie)
    i zwraca obiekt gotowy do uruchomienia.
    """
    graph_builder = StateGraph(DocState, context_schema=RunContext)
    graph_builder.add_node("scan", scan_node)
    graph_builder.add_edge(START, "scan")
    graph_builder.add_edge("scan", END)

    skompilowany_graf = graph_builder.compile()
    return skompilowany_graf


def run_graph(project_path: str, context: RunContext) -> DocState:
    """Uruchamia graf dla projektu i zwraca stan końcowy.

    Po co: punkt wejścia do całego przebiegu dla main.py i testów. Stan startowy zawiera
    tylko ścieżkę projektu (bezwzględną), resztę uzupełniają węzły.
    """
    stan_poczatkowy = {"project_path": os.path.abspath(project_path)}
    stan_koncowy = build_graph().invoke(stan_poczatkowy, context=context)
    return stan_koncowy


# --- Wyświetlanie ---


def print_final_state(state: DocState) -> None:
    """Wypisuje stan końcowy: ścieżkę projektu i podsumowanie mapy projektu (technologia, pliki, jednostki kodu).

    Po co: przy teście ręcznym widać, że węzeł scan zadziałał i jego wynik trafił do stanu.
    """
    project_map = state["project_map"]
    print("=== Stan końcowy grafu ===")
    print(f"project_path: {state['project_path']}")
    print("project_map:")
    print(f"  technologia:     {project_map.technology}")
    print(f"  pliki:           {len(project_map.files)}")
    print(f"  punkty wejścia:  {project_map.entrypoints}")
    print(f"  jednostki kodu:  {len(project_map.code_units)}")
    for unit in project_map.code_units:
        print(f"    {unit.name}")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: tworzy RunContext z config.yaml, uruchamia graf dla projektu z argumentu
    (domyślnie bieżący katalog) i wypisuje stan końcowy.

    Po co: sprawdzenie grafu na prawdziwym projekcie - mapa w stanie i w output/project_map.json.
    """
    project_path = os.getcwd()
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    context = create_run_context(config)
    final_state = run_graph(project_path, context)
    print_final_state(final_state)


if __name__ == "__main__":
    manual_test()
