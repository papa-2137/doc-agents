"""Graf LangGraph: kolejność etapów generowania dokumentacji.

Co robi: build_graph() składa graf z węzłów i krawędzi, run_graph() uruchamia go dla projektu.
Na tym etapie graf ma trzy węzły:
    START -> scan -> plan -> analyze (równolegle, po jednym na zadanie z planu) -> END
    - scan buduje mapę projektu (scanner.build_project_map), zapisuje ją do output/project_map.json
      i dopisuje do stanu,
    - plan (agent planner, doc_agents/agents/planner.py) na podstawie mapy tworzy plan pracy zespołu,
      zapisuje go do output/plan.json i dopisuje do stanu,
    - analyze (agent analityk, doc_agents/agents/analyst.py) analizuje jedną jednostkę kodu, zapisuje
      notatkę w output/notes/ i dokleja ją do listy notes w stanie.
Kolejne kroki dodadzą węzły redaktora i recenzenta.

Równoległość (Send): po węźle plan funkcja dispatch_analysts() zwraca listę Send("analyze", dane) -
po jednym na zadanie z planu. LangGraph uruchamia wtedy węzeł analyze tyle razy, ile jest zadań,
równolegle, a każde wywołanie dostaje tylko swoje dane (AnalystInput w state.py). Wyniki łączy
reducer pola notes. Liczbę równoczesnych wywołań ogranicza analysis.max_concurrency z config.yaml
(przekazywane w invoke jako max_concurrency).
Węzły agentów leżą w doc_agents/agents/ (każdy agent w osobnym pliku) - tu tylko je łączymy.

Jak czytać graf:
    - węzeł = zwykła funkcja (state, runtime) -> dict: czyta stan, zwraca tylko zmienione pola,
    - krawędź = kolejność węzłów (START i END to wbudowane początek i koniec),
    - runtime.context = RunContext z zależnościami (config, modele, zapis wyników) - patrz context.py,
    - każdy węzeł sam zapisuje swój wynik w output/ (po przebiegu widać wynik każdego etapu,
      także gdy coś padnie w połowie).

Test ręczny z katalogu repo (uruchamia graf i wypisuje stan końcowy; wymaga LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.graph <katalog projektu>
"""

import os
import sys

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from doc_agents.agents.analyst import analyst_node
from doc_agents.agents.planner import planner_node
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


def dispatch_analysts(state: DocState) -> list[Send]:
    """Zwraca listę Send("analyze", dane analityka) - po jednym na każde zadanie z planu.

    Po co: krawędź warunkowa po węźle plan - tak LangGraph uruchamia równolegle tyle analityków,
    ile zadań jest w planie. Dane analityka (AnalystInput) to zadanie, mapa projektu i plan;
    węzeł analyze nie potrzebuje reszty stanu.
    """
    wysylki = []
    for task in state["plan"].tasks:
        dane_analityka = {"task": task, "project_map": state["project_map"], "plan": state["plan"]}
        wysylki.append(Send("analyze", dane_analityka))
    return wysylki


# --- Graf ---


def build_graph():
    """Składa i kompiluje graf: START -> scan -> plan -> analyze (×N, równolegle) -> END,
    ze stanem DocState i kontekstem RunContext.

    Po co: jedno miejsce, w którym widać wszystkie etapy i ich kolejność; kolejne węzły
    dopisuje się tutaj. compile() sprawdza poprawność grafu (np. brakujące krawędzie)
    i zwraca obiekt gotowy do uruchomienia.
    """
    graph_builder = StateGraph(DocState, context_schema=RunContext)
    graph_builder.add_node("scan", scan_node)
    graph_builder.add_node("plan", planner_node)
    graph_builder.add_node("analyze", analyst_node)
    graph_builder.add_edge(START, "scan")
    graph_builder.add_edge("scan", "plan")
    graph_builder.add_conditional_edges("plan", dispatch_analysts, ["analyze"])
    graph_builder.add_edge("analyze", END)

    skompilowany_graf = graph_builder.compile()
    return skompilowany_graf


def run_graph(project_path: str, context: RunContext) -> DocState:
    """Uruchamia graf dla projektu i zwraca stan końcowy.

    Po co: punkt wejścia do całego przebiegu dla main.py i testów. Stan startowy zawiera
    tylko ścieżkę projektu (bezwzględną), resztę uzupełniają węzły. max_concurrency z configu
    ogranicza liczbę równocześnie działających węzłów (analityków wołających model).
    """
    stan_poczatkowy = {"project_path": os.path.abspath(project_path)}
    ustawienia_przebiegu = {"max_concurrency": context.config.analysis.max_concurrency}
    stan_koncowy = build_graph().invoke(stan_poczatkowy, config=ustawienia_przebiegu, context=context)
    return stan_koncowy


# --- Wyświetlanie ---


def print_final_state(state: DocState) -> None:
    """Wypisuje stan końcowy: ścieżkę projektu, podsumowanie mapy projektu (technologia, pliki, jednostki kodu),
    planu (liczba zadań, pliki wiedzy, rozdziały) i notatek analityków (liczba, jednostki).

    Po co: przy teście ręcznym widać, że wszystkie węzły zadziałały i ich wyniki trafiły do stanu -
    w szczególności, że notatek jest tyle, ile zadań w planie.
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
    plan = state["plan"]
    print("plan:")
    print(f"  zadania analityków:        {len(plan.tasks)}")
    print(f"  pliki wiedzy - analitycy:  {plan.analyst_kb_files}")
    print(f"  pliki wiedzy - redaktor:   {plan.editor_kb_files}")
    print(f"  rozdziały części opisowej: {len(plan.sections)}")
    for section in plan.sections:
        print(f"    {section.title}")
    notes = state["notes"]
    print(f"notes: {len(notes)} (zadań w planie: {len(plan.tasks)})")
    for note in notes:
        print(f"  {note.unit_name}: {len(note.process_steps)} kroków procesu")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: tworzy RunContext z config.yaml, uruchamia graf dla projektu z argumentu
    (domyślnie bieżący katalog) i wypisuje stan końcowy.

    Po co: sprawdzenie grafu na prawdziwym projekcie - mapa, plan i notatki w stanie oraz w output/.
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
