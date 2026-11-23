"""Agent analityk: analizuje jedną jednostkę kodu i zwraca notatkę dla redaktora (ModuleNote).

Co robi: create_note() dla jednego zadania z planu (AnalysisTask) składa prompt analityka
i wywołuje model agenta analyst ze schematem odpowiedzi ModuleNote (schemas.py). W prompcie:
    - pełny kod plików jednostki (plik ponad limitem analysis.max_file_size_kb z config.yaml
      idzie tylko jako szkielet, z adnotacją),
    - szkielety (outline) wszystkich pozostałych jednostek kodu projektu - analityk widzi
      sygnatury i docstringi funkcji, które jednostka wywołuje z innych plików,
    - wskazówka plannera i podsumowanie projektu z planu,
    - pełne pliki bazy wiedzy wybrane przez plannera dla analityków (plan.analyst_kb_files).

Najważniejsze pole notatki to process_steps: kolejne akcje robota z konkretami (aplikacje,
adresy, przyciski, pola, pliki), decyzje i pętle - z nich redaktor składa rozdział
„Ścieżki procesu krok po kroku”.

Kod czyta wyłącznie pliki jednostek kodu z mapy projektu (rola source) i pliki bazy wiedzy
przez read_kb_file() - pliki z sekretami nigdy nie trafiają do modelu.

Na tym etapie analityk działa bez grafu; węzeł grafu z równoległym uruchomieniem
analityków dla wszystkich zadań dojdzie w kroku 30.

Test ręczny z katalogu repo (analizuje jedną jednostkę na podstawie output/plan.json
z poprzedniego uruchomienia main.py; wymaga LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.agents.analyst <katalog projektu>
    python -m doc_agents.agents.analyst <katalog projektu> <nazwa jednostki, np. src/report.py>
"""

import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage

from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.knowledge import read_kb_file
from doc_agents.llm import get_structured_output_method, invoke_structured
from doc_agents.prompts import render_prompt
from doc_agents.scanner import build_project_map
from doc_agents.schemas import AnalysisTask, CodeUnit, ModuleNote, Plan, ProjectMap
from doc_agents.technologies import get_technology
from doc_agents.technologies.base import Technology


# --- Kod jednostki i kontekst projektu ---


def find_code_unit(project_map: ProjectMap, unit_name: str) -> CodeUnit:
    """Zwraca jednostkę kodu o podanej nazwie z mapy projektu; gdy jej nie ma, rzuca ValueError z listą nazw.

    Po co: nazwę jednostki podaje planner (model) - literówka albo zmyślona nazwa ma dać czytelny
    błąd zamiast analizy pustego kodu.
    """
    for unit in project_map.code_units:
        if unit.name == unit_name:
            return unit

    nazwy_jednostek = []
    for unit in project_map.code_units:
        nazwy_jednostek.append(unit.name)
    komunikat_bledu = f"Jednostki '{unit_name}' nie ma w mapie projektu. Jednostki w mapie: {nazwy_jednostek}"
    raise ValueError(komunikat_bledu)


def read_source_file(root: str, path: str) -> str:
    """Zwraca treść pliku projektu (ścieżka względna do root), z encoding="utf-8" i errors="replace".

    Po co: analizowany kod bywa w różnych kodowaniach - błędny znak nie może przerwać analizy.
    """
    with open(os.path.join(root, path), encoding="utf-8", errors="replace") as f:
        tresc_pliku = f.read()
    return tresc_pliku


def build_unit_code(root: str, unit: CodeUnit, technology: Technology | None, max_file_size_kb: int) -> str:
    """Zwraca kod plików jednostki do promptu: każdy plik w tagu <plik sciezka="...">. Plik większy niż
    max_file_size_kb trafia tylko jako szkielet, poprzedzony adnotacją o rozmiarze i limicie.

    Po co: analityk dostaje pełny kod tam, gdzie to możliwe, a koszt i rozmiar promptu pozostają
    przewidywalne także przy bardzo dużych plikach (limit z config.yaml, sekcja analysis).
    """
    czesci = []
    for path in unit.files:
        size_kb = os.path.getsize(os.path.join(root, path)) / 1024
        if size_kb > max_file_size_kb:
            outline_text = ""
            if technology is not None:
                outline_text = technology.outline(root, path)
            czesci.append(
                f'<plik sciezka="{path}" tresc="szkielet">\n'
                f"(Plik ma {size_kb:.0f} KB - więcej niż limit {max_file_size_kb} KB, poniżej tylko szkielet.)\n"
                f"{outline_text}\n</plik>"
            )
        else:
            czesci.append(f'<plik sciezka="{path}">\n{read_source_file(root, path)}\n</plik>')

    kod_jednostki = "\n\n".join(czesci)
    return kod_jednostki


def build_project_outlines(root: str, project_map: ProjectMap, unit: CodeUnit, technology: Technology | None) -> str:
    """Zwraca szkielety wszystkich plików pozostałych jednostek kodu projektu, każdy w tagu <szkielet sciezka="...">.
    Gdy technologia nie jest rozpoznana albo nie ma innych jednostek, zwraca informację w nawiasie.

    Po co: analityk widzi strukturę całego projektu (funkcje, klasy, docstringi) i rozumie wywołania
    z innych plików, bez płacenia za ich pełny kod.
    """
    czesci = []
    if technology is not None:
        for other_unit in project_map.code_units:
            if other_unit.name == unit.name:
                continue
            for path in other_unit.files:
                czesci.append(f'<szkielet sciezka="{path}">\n{technology.outline(root, path)}\n</szkielet>')

    szkielety = "(brak innych jednostek kodu)"
    if czesci:
        szkielety = "\n\n".join(czesci)
    return szkielety


def build_kb_text(knowledge_base_dir: str, filenames: list[str]) -> str:
    """Zwraca treść wskazanych plików bazy wiedzy, każdy w tagu <plik_wiedzy nazwa="...">.

    Po co: analityk dostaje wiedzę wybraną przez plannera (np. jak działa framework RPA).
    Odczyt przez read_kb_file() - nazwa od modelu nie może wskazać pliku spoza bazy wiedzy.
    """
    czesci = []
    for filename in filenames:
        czesci.append(f'<plik_wiedzy nazwa="{filename}">\n{read_kb_file(knowledge_base_dir, filename)}\n</plik_wiedzy>')

    tekst_wiedzy = "(planner nie wybrał plików bazy wiedzy)"
    if czesci:
        tekst_wiedzy = "\n\n".join(czesci)
    return tekst_wiedzy


# --- Analiza ---


def create_note(task: AnalysisTask, project_map: ProjectMap, plan: Plan, context: RunContext) -> ModuleNote:
    """Tworzy notatkę dla jednego zadania z planu: składa prompt analityka (kod jednostki, szkielety projektu,
    wskazówka, podsumowanie, baza wiedzy), wywołuje model agenta analyst ze schematem ModuleNote i zwraca notatkę.

    Po co: cała logika analityka w jednej funkcji, z której skorzysta węzeł grafu (krok 30) i test ręczny.
    Nazwę jednostki w notatce ustawia kod (task.unit_name), żeby notatka zawsze dała się przypisać
    do zadania, nawet gdy model przepisze nazwę z błędem.
    """
    config = context.config
    root = project_map.root
    unit = find_code_unit(project_map, task.unit_name)
    technology = get_technology(project_map.technology)

    variables = {
        "project_name": project_map.project_name,
        "unit_name": unit.name,
        "hint": task.hint,
        "plan_summary": plan.summary,
        "unit_code": build_unit_code(root, unit, technology, config.analysis.max_file_size_kb),
        "project_outlines": build_project_outlines(root, project_map, unit, technology),
        "kb_files": build_kb_text(config.paths.knowledge_base, plan.analyst_kb_files),
    }
    system_text, user_text = render_prompt(config.paths.prompts, "analyst", variables)

    notatka = invoke_structured(
        context.models["analyst"],
        ModuleNote,
        get_structured_output_method(config, "analyst"),
        [SystemMessage(content=system_text), HumanMessage(content=user_text)],
    )
    notatka.unit_name = task.unit_name
    return notatka


# --- Wyświetlanie ---


def print_list(title: str, items: list[str]) -> None:
    """Wypisuje tytuł i elementy listy jako punkty; pustą listę jako „(brak)”.

    Po co: wspólny format dla wszystkich pól listowych notatki w teście ręcznym.
    """
    print(f"\n{title}:")
    if not items:
        print("  (brak)")
    for item in items:
        print(f"  - {item}")


def print_note(note: ModuleNote) -> None:
    """Wypisuje wszystkie pola notatki analityka w czytelnej postaci.

    Po co: przy teście ręcznym widać, czy analityk zrozumiał jednostkę, a szczególnie czy kroki
    procesu są konkretne (nazwy przycisków, adresy, pliki), bo z nich powstaną ścieżki procesu.
    """
    print(f"=== Notatka analityka: {note.unit_name} ===\n")
    print(f"Przeznaczenie: {note.purpose}")
    print(f"Automatyzowana aplikacja: {note.automated_application}")
    print_list("Kluczowe funkcje", note.key_functions)
    print_list("Kroki procesu", note.process_steps)
    print_list("Obsługa błędów", note.error_handling)
    print_list("Wejścia", note.inputs)
    print_list("Wyjścia", note.outputs)
    print_list("Używana konfiguracja", note.config_used)
    print_list("Zależności zewnętrzne", note.external_dependencies)
    print_list("Pułapki", note.pitfalls)
    print_list("Wskazówki dla opiekuna", note.maintainer_hints)


def print_missing_plan(plan_path: str) -> None:
    """Wypisuje informację o braku planu z poprzedniego uruchomienia i jak go utworzyć.

    Po co: test analityka korzysta z gotowego planu, żeby nie płacić za ponowne wywołanie plannera.
    """
    print(f"Brak planu: {plan_path}")
    print("Najpierw uruchom: python main.py --project <katalog projektu>")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: wczytuje output/plan.json z poprzedniego uruchomienia main.py, skanuje projekt z argumentu
    (domyślnie bieżący katalog), analizuje jednostkę z drugiego argumentu (domyślnie pierwszą z planu)
    i wypisuje notatkę.

    Po co: sprawdzenie analityka na jednej jednostce bez całego grafu i bez ponownego wywołania plannera.
    Plan jest wczytywany przed utworzeniem kontekstu (który czyści output/) i zapisywany z powrotem,
    więc kolejne testy analityka mogą z niego korzystać.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plan_path = os.path.join(repo_dir, "output", "plan.json")
    if not os.path.isfile(plan_path):
        print_missing_plan(plan_path)
        return
    with open(plan_path, encoding="utf-8") as f:
        plan = Plan.model_validate_json(f.read())

    project_path = os.getcwd()
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    task = plan.tasks[0]
    if len(sys.argv) > 2:
        task = AnalysisTask(unit_name=sys.argv[2], hint="(test ręczny - bez wskazówki plannera)")
        for plan_task in plan.tasks:
            if plan_task.unit_name == sys.argv[2]:
                task = plan_task

    config = load_config(os.path.join(repo_dir, "config.yaml"))
    context = create_run_context(config)
    context.run_store.save_json("plan.json", plan)
    project_map = build_project_map(os.path.abspath(project_path), config.scan)

    note = create_note(task, project_map, plan, context)
    print_note(note)


if __name__ == "__main__":
    manual_test()
