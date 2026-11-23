"""Graf LangGraph: kolejność etapów generowania dokumentacji.

Co robi: build_graph() składa graf z węzłów i krawędzi, run_graph() uruchamia go dla projektu.
Graf ma sześć węzłów:
    START -> scan -> plan -> analyze (równolegle, po jednym na zadanie z planu) -> edit -> review
    review -> finalize -> END   (dokument zaakceptowany albo osiągnięty limit recenzji)
    review -> edit              (dokument odrzucony - redaktor poprawia go według uwag)
    - scan buduje mapę projektu (scanner.build_project_map), zapisuje ją do output/project_map.json
      i dopisuje do stanu,
    - plan (agent planner, doc_agents/agents/planner.py) na podstawie mapy tworzy plan pracy zespołu,
      zapisuje go do output/plan.json i dopisuje do stanu,
    - analyze (agent analityk, doc_agents/agents/analyst.py) analizuje jedną jednostkę kodu, zapisuje
      notatkę w output/notes/ i dokleja ją do listy notes w stanie,
    - edit (agent redaktor, doc_agents/agents/editor.py) uruchamia się, gdy wszyscy analitycy skończą,
      i po każdej odrzuconej recenzji: składa (albo poprawia) dokument (output/document_NN.md)
      i oddaje do stanu dokument i braki,
    - review (agent recenzent, doc_agents/agents/reviewer.py) ocenia dokument (output/review_NN.json)
      i ustala review_done,
    - finalize zapisuje ostatnią wersję dokumentu w output/final.md.

Równoległość (Send): po węźle plan funkcja dispatch_analysts() zwraca listę Send("analyze", dane) -
po jednym na zadanie z planu. LangGraph uruchamia wtedy węzeł analyze tyle razy, ile jest zadań,
równolegle, a każde wywołanie dostaje tylko swoje dane (AnalystInput w state.py). Wyniki łączy
reducer pola notes. Liczbę równoczesnych wywołań ogranicza analysis.max_concurrency z config.yaml
(przekazywane przy uruchomieniu jako max_concurrency).
Węzły agentów leżą w doc_agents/agents/ (każdy agent w osobnym pliku) - tu tylko je łączymy.

Postęp na ekranie: run_graph() uruchamia graf przez stream(stream_mode=["tasks", "values"]) zamiast invoke().
Tryb "tasks" zgłasza start i koniec każdego wywołania węzła (z danymi wejściowymi, wynikiem albo błędem),
z tego powstaje jedna linia postępu na zdarzenie (godzina, agent, czas trwania, krótki wynik).
Tryb "values" oddaje stan po każdym kroku - ostatni to stan końcowy. Agenci nic nie wypisują sami.

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
import time
from datetime import datetime

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from doc_agents.agents.analyst import analyst_node
from doc_agents.agents.editor import editor_node
from doc_agents.agents.planner import planner_node
from doc_agents.agents.reviewer import reviewer_node
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


def finalize_node(state: DocState, runtime: Runtime[RunContext]) -> dict:
    """Węzeł finalize: zapisuje dokument ze stanu jako output/final.md.

    Po co: jedno, stałe miejsce wyniku końcowego - ostatnia wersja po pętli recenzji (zaakceptowana
    albo ostatnia przed limitem). Wersje robocze to document_NN.md. Węzeł nie zmienia stanu.
    """
    runtime.context.run_store.save_text("final.md", state["document"])

    aktualizacja_stanu = {}
    return aktualizacja_stanu


def route_after_review(state: DocState) -> str:
    """Zwraca nazwę następnego węzła po recenzji: "finalize", gdy pętla recenzji się zakończyła
    (review_done), inaczej "edit" - redaktor poprawia dokument według uwag.

    Po co: krawędź warunkowa pętli recenzji. Decyzję (akceptacja albo limit rund) liczy węzeł review;
    tu ją tylko odczytujemy.
    """
    nastepny_wezel = "edit"
    if state["review_done"]:
        nastepny_wezel = "finalize"
    return nastepny_wezel


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
    """Składa i kompiluje graf: START -> scan -> plan -> analyze (×N, równolegle) -> edit -> review,
    a po review: finalize -> END albo powrót do edit (pętla recenzji). Stan DocState, kontekst RunContext.
    Krawędź analyze -> edit uruchamia edit raz, po zakończeniu wszystkich równoległych analityków.

    Po co: jedno miejsce, w którym widać wszystkie etapy i ich kolejność; kolejne węzły
    dopisuje się tutaj. compile() sprawdza poprawność grafu (np. brakujące krawędzie)
    i zwraca obiekt gotowy do uruchomienia.
    """
    graph_builder = StateGraph(DocState, context_schema=RunContext)
    graph_builder.add_node("scan", scan_node)
    graph_builder.add_node("plan", planner_node)
    graph_builder.add_node("analyze", analyst_node)
    graph_builder.add_node("edit", editor_node)
    graph_builder.add_node("review", reviewer_node)
    graph_builder.add_node("finalize", finalize_node)
    graph_builder.add_edge(START, "scan")
    graph_builder.add_edge("scan", "plan")
    graph_builder.add_conditional_edges("plan", dispatch_analysts, ["analyze"])
    graph_builder.add_edge("analyze", "edit")
    graph_builder.add_edge("edit", "review")
    graph_builder.add_conditional_edges("review", route_after_review, ["edit", "finalize"])
    graph_builder.add_edge("finalize", END)

    skompilowany_graf = graph_builder.compile()
    return skompilowany_graf


def run_graph(project_path: str, context: RunContext) -> DocState:
    """Uruchamia graf dla projektu, w trakcie wypisuje postęp (start i koniec każdego etapu) i zwraca stan końcowy.

    Po co: punkt wejścia do całego przebiegu dla main.py i testów. Stan startowy zawiera
    tylko ścieżkę projektu (bezwzględną), resztę uzupełniają węzły. max_concurrency z configu
    ogranicza liczbę równocześnie działających węzłów (analityków wołających model).
    Postęp: przebieg trwa kilka minut, a pojedyncze wywołanie modelu nawet ponad minutę - linie
    postępu pokazują, który etap trwa, więc widać, że program pracuje, a nie stoi.
    """
    stan_poczatkowy = {"project_path": os.path.abspath(project_path)}
    ustawienia_przebiegu = {"max_concurrency": context.config.analysis.max_concurrency}
    zdarzenia = build_graph().stream(
        stan_poczatkowy, config=ustawienia_przebiegu, context=context, stream_mode=["tasks", "values"]
    )
    rozpoczete_zadania = {}
    stan_koncowy = {}
    for tryb, dane in zdarzenia:
        if tryb == "values":
            stan_koncowy = dane
        else:
            linia_postepu = build_progress_line(dane, rozpoczete_zadania)
            print_progress(linia_postepu)
    return stan_koncowy


# --- Postęp ---


def describe_task(node_name: str, node_input: dict) -> str:
    """Zwraca krótki opis wywołania węzła do linii postępu, np. "analityk src/report.py" albo "redaktor, runda 2".

    Po co: sama nazwa węzła ("analyze") nie mówi, którą jednostkę kodu analizuje dane wywołanie
    ani która to runda recenzji. Dane wejściowe: dla analyze - AnalystInput, dla pozostałych - stan.
    Runda redaktora i recenzenta = liczba dotychczasowych recenzji + 1 (review_round w stanie).
    """
    runda = node_input.get("review_round", 0) + 1
    opis = node_name
    if node_name == "scan":
        opis = "skan projektu"
    elif node_name == "plan":
        opis = "planner"
    elif node_name == "analyze":
        opis = f"analityk {node_input['task'].unit_name}"
    elif node_name == "edit":
        opis = f"redaktor, runda {runda}"
    elif node_name == "review":
        opis = f"recenzent, runda {runda}"
    elif node_name == "finalize":
        opis = "zapis final.md"
    return opis


def describe_result(node_name: str, node_result: dict) -> str:
    """Zwraca krótki opis wyniku węzła do linii postępu (np. "odrzucony, uwagi: 2") albo "", gdy nie ma czego pokazać.

    Po co: przy planie, redaktorze i recenzencie od razu widać, co z etapu wyszło (liczba zadań,
    braki, decyzja recenzenta) - bez czekania na podsumowanie na końcu przebiegu.
    node_result to pola stanu zwrócone przez węzeł.
    """
    opis_wyniku = ""
    if node_name == "plan":
        opis_wyniku = f"zadań analityków: {len(node_result['plan'].tasks)}"
    elif node_name == "edit":
        opis_wyniku = f"braki: {len(node_result['missing'])}"
    elif node_name == "review":
        review = node_result["review"]
        if review.approved:
            opis_wyniku = "zaakceptowany"
        else:
            opis_wyniku = f"odrzucony, uwagi: {len(review.issues)}"
    return opis_wyniku


def format_duration(seconds: float) -> str:
    """Zwraca czas trwania w czytelnej postaci: "17 s" albo "1 min 47 s".

    Po co: czasy etapów w linii postępu - przy wywołaniach modelu liczą się sekundy i minuty.
    """
    pelne_sekundy = int(round(seconds))
    czas = f"{pelne_sekundy} s"
    if pelne_sekundy >= 60:
        czas = f"{pelne_sekundy // 60} min {pelne_sekundy % 60} s"
    return czas


def build_progress_line(task_event: dict, started_tasks: dict) -> str:
    """Zwraca linię postępu dla zdarzenia trybu "tasks": start albo koniec (lub błąd) wywołania węzła.

    Po co: zamienia surowe zdarzenie LangGraph na jedną czytelną linię z godziną. Zdarzenie startu
    ma klucz "input"; zdarzenie końca ma "result" i "error" i to samo "id" co start.
    started_tasks (id -> (czas startu, opis)) jest uzupełniany przy starcie i opróżniany przy końcu -
    stąd czas trwania i opis przy końcu. Uwaga: przy większej liczbie analityków niż max_concurrency
    LangGraph zgłasza start wszystkich naraz, więc czas części z nich obejmuje też czekanie w kolejce.
    """
    godzina = datetime.now().strftime("%H:%M:%S")
    zadanie_id = task_event["id"]
    nazwa_wezla = task_event["name"]
    if "input" in task_event:
        opis = describe_task(nazwa_wezla, task_event["input"])
        started_tasks[zadanie_id] = (time.monotonic(), opis)
        linia = f"[{godzina}] start   {opis}"
        return linia

    czas_startu, opis = started_tasks.pop(zadanie_id, (time.monotonic(), nazwa_wezla))
    czas_trwania = format_duration(time.monotonic() - czas_startu)
    blad = task_event["error"]
    if blad is not None:
        linia = f"[{godzina}] BŁĄD    {opis} ({czas_trwania}) - {type(blad).__name__}: {blad}"
        return linia

    linia = f"[{godzina}] koniec  {opis} ({czas_trwania})"
    opis_wyniku = describe_result(nazwa_wezla, task_event["result"])
    if opis_wyniku != "":
        linia = f"{linia} - {opis_wyniku}"
    return linia


# --- Wyświetlanie ---


def print_progress(line: str) -> None:
    """Wypisuje jedną linię postępu przebiegu i od razu ją pokazuje (flush).

    Po co: bez flush konsola może buforować wydruk i linie pojawiałyby się z opóźnieniem,
    co psułoby cały sens podglądu postępu.
    """
    print(line, flush=True)


def print_final_state(state: DocState) -> None:
    """Wypisuje stan końcowy: ścieżkę projektu, podsumowanie mapy projektu (technologia, pliki, jednostki kodu),
    planu (liczba zadań, pliki wiedzy, rozdziały), notatek analityków (liczba, jednostki) oraz dokumentu
    (liczba linii i braki).

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
    print(f"document: {len(state['document'].splitlines())} linii")
    print(f"missing: {state['missing']}")
    print(f"recenzje: {state['review_round']}, zaakceptowany: {state['review'].approved}, problemy: {len(state['review'].issues)}")


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
