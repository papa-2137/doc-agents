"""Agent planner: na podstawie mapy projektu planuje pracę zespołu - zanim ktokolwiek przeczyta kod.

Co robi: create_plan() składa prompt plannera z czterech części (mapa projektu, spis bazy wiedzy,
stałe rozdziały części opisowej, tytuły pól części formalnej), wywołuje model agenta planner ze schematem odpowiedzi Plan
(schemas.py) i zwraca gotowy plan. planner_node() to węzeł grafu: tworzy plan, zapisuje go
do output/plan.json i dokłada do stanu.

Co jest w planie (szczegóły w schemas.Plan):
    - zadania dla analityków - po jednym na jednostkę kodu, ze wskazówką,
    - pliki bazy wiedzy dla analityków i osobno dla redaktora,
    - rozdziały części opisowej (stałe z descriptive_template.yaml i dodatkowe dla projektu).

Dane trafiają do promptu jako JSON (mapa projektu w tej samej postaci co project_map.json),
więc model widzi dokładne nazwy jednostek kodu i plików wiedzy, które ma przepisać do planu.
Tytuły pól części formalnej idą jako zwykła lista - model ma tylko nie powielać ich w części opisowej.
Kod nie poprawia odpowiedzi modelu - zgodność planu z mapą i spisem sprawdzi recenzent,
a read_kb_file() i tak odrzuci plik spoza bazy wiedzy.

Test ręczny z katalogu repo (skanuje projekt, wywołuje model plannera i wypisuje plan;
wymaga zmiennych LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.agents.planner <katalog projektu>
"""

import json
import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.knowledge import KBEntry, load_fixed_sections, load_formal_field_titles
from doc_agents.llm import get_structured_output_method
from doc_agents.prompts import render_prompt
from doc_agents.scanner import build_project_map
from doc_agents.schemas import DescriptiveSection, Plan, ProjectMap
from doc_agents.state import DocState


# --- Planowanie ---


def build_planner_variables(
    project_map: ProjectMap,
    kb_index: list[KBEntry],
    fixed_sections: list[DescriptiveSection],
    formal_field_titles: list[str],
) -> dict:
    """Zwraca zmienne do szablonu prompts/planner/user.md: nazwę projektu, mapę, spis bazy wiedzy
    i stałe rozdziały jako JSON oraz tytuły pól części formalnej jako listę punktów.

    Po co: oddziela przygotowanie danych od wywołania modelu - widać w jednym miejscu, co dokładnie
    planner dostaje. JSON bez zamiany polskich znaków na kody (ensure_ascii=False), żeby model
    i człowiek czytający prompt widzieli zwykły tekst.
    """
    kb_index_data = []
    for entry in kb_index:
        kb_index_data.append(entry.model_dump())
    fixed_sections_data = []
    for section in fixed_sections:
        fixed_sections_data.append(section.model_dump())
    formal_fields_lines = []
    for title in formal_field_titles:
        formal_fields_lines.append(f"- {title}")

    zmienne_promptu = {
        "project_name": project_map.project_name,
        "project_map": project_map.model_dump_json(indent=2),
        "kb_index": json.dumps(kb_index_data, indent=2, ensure_ascii=False),
        "fixed_sections": json.dumps(fixed_sections_data, indent=2, ensure_ascii=False),
        "formal_fields": "\n".join(formal_fields_lines),
    }
    return zmienne_promptu


def create_plan(project_map: ProjectMap, context: RunContext) -> Plan:
    """Tworzy plan dla projektu: składa prompt plannera, wywołuje model agenta planner ze schematem Plan
    i zwraca odpowiedź jako obiekt Plan.

    Po co: cała logika plannera w jednej funkcji, z której korzysta węzeł grafu i test ręczny.
    with_structured_output() każe modelowi odpowiedzieć zgodnie ze schematem Plan (metoda z profilu
    agenta w config.yaml) i zamienia odpowiedź na obiekt; odpowiedź niezgodna ze schematem kończy się
    błędem walidacji Pydantic.
    """
    config = context.config
    fixed_sections = load_fixed_sections(config.paths.knowledge_base)
    formal_field_titles = load_formal_field_titles(config.paths.knowledge_base)
    variables = build_planner_variables(project_map, context.kb_index, fixed_sections, formal_field_titles)
    system_text, user_text = render_prompt(config.paths.prompts, "planner", variables)

    model_ze_schematem = context.models["planner"].with_structured_output(
        Plan, method=get_structured_output_method(config, "planner")
    )
    plan = model_ze_schematem.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
    return plan


# --- Węzeł grafu ---


def planner_node(state: DocState, runtime: Runtime[RunContext]) -> dict:
    """Węzeł plan: tworzy plan dla mapy projektu ze stanu, zapisuje go jako plan.json i zwraca go do stanu.

    Po co: drugi etap przebiegu - plan decyduje, których analityków uruchomić i z jaką wiedzą,
    oraz jakie rozdziały napisze redaktor. Zwraca tylko pole plan (częściowa aktualizacja stanu).
    """
    context = runtime.context
    plan = create_plan(state["project_map"], context)
    context.run_store.save_json("plan.json", plan)

    aktualizacja_stanu = {"plan": plan}
    return aktualizacja_stanu


# --- Wyświetlanie ---


def print_plan(plan: Plan) -> None:
    """Wypisuje plan: podsumowanie projektu, zadania analityków, pliki wiedzy i rozdziały części opisowej.

    Po co: przy teście ręcznym widać od razu, czy planner zrozumiał projekt i czy uwzględnił
    wszystkie jednostki kodu i stałe rozdziały.
    """
    print("=== Plan ===\n")
    print(plan.summary)
    print(f"\nZadania analityków: {len(plan.tasks)}")
    for task in plan.tasks:
        print(f"  {task.unit_name}")
        print(f"    {task.hint}")
    print(f"\nPliki wiedzy - analitycy: {plan.analyst_kb_files}")
    print(f"Pliki wiedzy - redaktor:  {plan.editor_kb_files}")
    print(f"\nRozdziały części opisowej: {len(plan.sections)}")
    for section in plan.sections:
        print(f"  {section.title}")
        print(f"    {section.instruction}")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: tworzy RunContext z config.yaml, skanuje projekt z argumentu (domyślnie bieżący katalog),
    tworzy plan (jedno wywołanie modelu), zapisuje go do output/plan.json i wypisuje.

    Po co: sprawdzenie plannera na prawdziwym projekcie bez uruchamiania całego grafu - łatwo
    porównać plan po każdej zmianie promptu.
    """
    project_path = os.getcwd()
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    context = create_run_context(config)
    project_map = build_project_map(os.path.abspath(project_path), config.scan)
    plan = create_plan(project_map, context)
    context.run_store.save_json("plan.json", plan)
    print_plan(plan)


if __name__ == "__main__":
    manual_test()
