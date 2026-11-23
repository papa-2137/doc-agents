"""Agent recenzent: sprawdza gotowy dokument i decyduje, czy wymaga poprawek.

Co robi: review_document() łączy dwie kontrole:
    - kod: braki policzone przez redaktora (pola wymagane części formalnej i rozdziały wymagane
      części opisowej, lista missing) - każdy brak to problem do poprawy i blokuje akceptację,
    - model agenta reviewer: czyta cały dokument razem z notatkami analityków i ocenia zgodność
      z notatkami (czy nic nie jest dopowiedziane), konkretność wskazówek, kompletność ścieżek procesu,
      powtórzenia między rozdziałami i obecność wartości sekretów. Zwraca ReviewResult: approved,
      issues (problemy do poprawy) i suggestions (uwagi, które nie blokują).
Wynik końcowy: issues = braki z kodu + problemy od modelu; approved = decyzja modelu, ale tylko
gdy kod nie znalazł braków.

Uwagi to zdania zaczynające się od nazwy rozdziału lub pola w nawiasie kwadratowym, np.
„[Ścieżki procesu krok po kroku] ...” - w kroku 34 trafią do redaktora jako polecenia poprawek.

reviewer_node() to węzeł grafu review: recenzuje dokument ze stanu, zapisuje output/review_NN.json
(NN = numer recenzji: 01, 02, ...) i ustala, czy pętla recenzji się kończy - dokument zaakceptowany
albo osiągnięty limit limits.max_review_rounds z config.yaml. Test ręczny zapisuje output/review.json.

Test ręczny z katalogu repo - na wynikach poprzedniego uruchomienia main.py (output/ nie jest
czyszczony; jedno wywołanie modelu; wymaga LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.agents.reviewer
"""

import os

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from doc_agents.agents.editor import build_editor_kb_text, build_notes_text, load_notes
from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.llm import get_structured_output_method, invoke_structured
from doc_agents.output import RunStore
from doc_agents.prompts import render_prompt
from doc_agents.schemas import ModuleNote, Plan, ProjectMap, ReviewResult
from doc_agents.state import DocState


# --- Recenzja ---


def ask_review(
    project_name: str, document: str, plan: Plan, notes: list[ModuleNote], context: RunContext
) -> ReviewResult:
    """Wywołuje model agenta reviewer z dokumentem, notatkami analityków i plikami wiedzy redaktora
    i zwraca jego ocenę (ReviewResult).

    Po co: ocena jakości, której nie da się sprawdzić kodem - czy dokument zgadza się z notatkami,
    czy wskazówki są konkretne, czy ścieżki procesu są kompletne. Zasady pisania (pliki wiedzy
    redaktora, np. documentation_goals.md) są miarą oceny.
    """
    config = context.config
    variables = {
        "project_name": project_name,
        "document": document,
        "notes": build_notes_text(notes),
        "kb_files": build_editor_kb_text(config.paths.knowledge_base, plan.editor_kb_files),
    }
    system_text, user_text = render_prompt(config.paths.prompts, "reviewer", variables)
    ocena = invoke_structured(
        context.models["reviewer"],
        ReviewResult,
        get_structured_output_method(config, "reviewer"),
        [SystemMessage(content=system_text), HumanMessage(content=user_text)],
    )
    return ocena


def review_document(
    project_name: str, document: str, plan: Plan, notes: list[ModuleNote], missing: list[str], context: RunContext
) -> ReviewResult:
    """Recenzuje dokument: braki z kodu (missing) zamienia na problemy, dodaje ocenę modelu i zwraca
    wynik końcowy. Dokument jest zaakceptowany, gdy model go zaakceptował i nie ma braków.

    Po co: braki wymaganych pól i rozdziałów to fakt sprawdzony kodem - nie mogą zostać przeoczone
    przez model; o jakości treści decyduje model. Jedna funkcja dla węzła grafu (krok 34) i testu ręcznego.
    """
    ocena_modelu = ask_review(project_name, document, plan, notes, context)

    issues = []
    for name in missing:
        issues.append(f"[{name}] Brak treści w polu lub rozdziale wymaganym - uzupełnij na podstawie notatek.")
    for issue in ocena_modelu.issues:
        issues.append(issue)
    approved = ocena_modelu.approved and not missing

    wynik = ReviewResult(approved=approved, issues=issues, suggestions=ocena_modelu.suggestions)
    return wynik


# --- Węzeł grafu ---


def review_filename(round_number: int) -> str:
    """Zwraca nazwę pliku recenzji danej rundy: review_01.json, review_02.json, ...

    Po co: każda recenzja zostaje w output/ obok dokumentu z tej samej rundy (document_NN.md).
    """
    nazwa_pliku = f"review_{round_number:02d}.json"
    return nazwa_pliku


def reviewer_node(state: DocState, runtime: Runtime[RunContext]) -> dict:
    """Węzeł review: recenzuje dokument ze stanu, zapisuje recenzję jako output/review_NN.json i zwraca do stanu
    recenzję, numer recenzji i decyzję review_done (zaakceptowany albo osiągnięty limit recenzji z configu).

    Po co: punkt decyzji pętli recenzji. Decyzję liczy węzeł (ma dostęp do configu), a krawędź
    warunkowa w graph.py tylko ją odczytuje - logika limitu jest w jednym miejscu.
    """
    context = runtime.context
    round_number = 1
    if "review_round" in state:
        round_number = state["review_round"] + 1

    review = review_document(
        state["project_map"].project_name, state["document"], state["plan"], state["notes"], state["missing"], context
    )
    context.run_store.save_json(review_filename(round_number), review)
    review_done = review.approved or round_number >= context.config.limits.max_review_rounds

    aktualizacja_stanu = {"review": review, "review_round": round_number, "review_done": review_done}
    return aktualizacja_stanu


# --- Wczytanie wyników poprzednich etapów ---


def load_missing(run_store: RunStore) -> list[str]:
    """Wczytuje listy braków zapisane przez redaktora (formal_missing.txt i descriptive_missing.txt)
    i zwraca je jako jedną listę; „brak” w pliku oznacza pustą listę.

    Po co: test recenzenta pracuje na wynikach poprzedniego uruchomienia - te same braki, które
    w grafie są w stanie (pole missing).
    """
    braki = []
    for filename in ["formal_missing.txt", "descriptive_missing.txt"]:
        with open(run_store.path(filename), encoding="utf-8") as f:
            for line in f.read().splitlines():
                if line.strip() != "" and line.strip() != "brak":
                    braki.append(line.strip())
    return braki


# --- Wyświetlanie ---


def print_review(review: ReviewResult, review_path: str) -> None:
    """Wypisuje wynik recenzji: decyzję, problemy do poprawy, sugestie i ścieżkę zapisanego pliku.

    Po co: przy teście ręcznym widać od razu, czy recenzent łapie realne problemy i czy uwagi
    są na tyle konkretne, że redaktor będzie mógł je poprawić.
    """
    decyzja = "ODRZUCONY - wymaga poprawek"
    if review.approved:
        decyzja = "ZAAKCEPTOWANY"
    print(f"=== Recenzja: {decyzja} ===")
    print(f"\nProblemy do poprawy ({len(review.issues)}):")
    if not review.issues:
        print("  brak")
    for issue in review.issues:
        print(f"  - {issue}")
    print(f"\nSugestie ({len(review.suggestions)}):")
    if not review.suggestions:
        print("  brak")
    for suggestion in review.suggestions:
        print(f"  - {suggestion}")
    print(f"\nWynik: {review_path}")


def print_missing_inputs(output_dir: str) -> None:
    """Wypisuje informację o braku wyników poprzedniego uruchomienia i jak je utworzyć.

    Po co: test recenzenta korzysta z gotowego dokumentu, planu, notatek i list braków.
    """
    print(f"Brak wyników poprzedniego uruchomienia w {output_dir} (final.md, plan.json, notes/, *_missing.txt).")
    print("Najpierw uruchom: python main.py --project <katalog projektu>")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: na wynikach poprzedniego uruchomienia main.py (output/ bez czyszczenia) recenzuje
    final.md (jedno wywołanie modelu), zapisuje wynik w output/review.json i wypisuje go.

    Po co: strojenie promptu recenzenta na stałym dokumencie - bez kosztu ponownej analizy i redakcji.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    context = create_run_context(config, clear_output=False)
    run_store = context.run_store
    if not os.path.isfile(run_store.path("final.md")) or not os.path.isfile(run_store.path("formal_missing.txt")):
        print_missing_inputs(run_store.output_dir)
        return

    with open(run_store.path("final.md"), encoding="utf-8") as f:
        document = f.read()
    project_map = run_store.load_json("project_map.json", ProjectMap)
    plan = run_store.load_json("plan.json", Plan)
    notes = load_notes(run_store)
    missing = load_missing(run_store)

    review = review_document(project_map.project_name, document, plan, notes, missing, context)
    review_path = run_store.save_json("review.json", review)
    print_review(review, review_path)


if __name__ == "__main__":
    manual_test()
