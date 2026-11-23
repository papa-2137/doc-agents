"""Agent redaktor - część formalna dokumentu: lista kontrolna informacji operacyjnych o robocie.

Co robi: create_formal_part() wypełnia pola części formalnej opisane w
knowledge_base/templates/formal_template.yaml i składa z nich Markdown według
knowledge_base/templates/formal_template.md (Jinja2). Kod nie zna konkretnych pól - wszystko
wynika z szablonów, więc nowe pole to tylko wpis w YAML (i ewentualnie zmiana układu w .md).

Skąd wartości pól (klucz source w YAML):
    - source: scanner - kod bierze je z mapy projektu, bez modelu: scanner: entrypoints
      (punkty wejścia) albo scanner: role:<rola> (ścieżki plików o tej roli, np. role:secret),
    - source: llm - jedno wywołanie modelu agenta editor dla wszystkich takich pól naraz,
      na podstawie notatek analityków (w całości, jako JSON), podsumowania z planu i plików
      wiedzy wybranych przez plannera dla redaktora (plan.editor_kb_files).
Model zwraca FormalSection (schemas.py): listę par nazwa pola - wartość; wartość to zawsze
lista tekstów (pole tekstowe = jeden element, łączony przy składaniu).

Braki: pole wymagane (required: true) bez wartości renderuje się jako „_Brak danych._”, a jego
nazwa trafia na listę braków (wydruk i output/formal_missing.txt). Pole o nazwie spoza szablonu
w odpowiedzi modelu jest pomijane. Dokument powstaje zawsze; uzupełnienie braków zleci recenzent.

Wyniki w output/: formal.md (część formalna), formal_section.json (wszystkie pola z wartościami),
formal_missing.txt (lista braków).

Na tym etapie redaktor działa bez grafu (węzeł redaktora dojdzie w kroku 32).

Test ręczny z katalogu repo - na wynikach poprzedniego uruchomienia main.py (output/ nie jest
czyszczony, model wołany tylko dla redaktora; wymaga LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.agents.editor
"""

import json
import os

from jinja2 import Environment, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage

from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.knowledge import load_formal_fields, read_kb_file
from doc_agents.llm import get_structured_output_method, invoke_structured
from doc_agents.output import RunStore
from doc_agents.prompts import render_prompt
from doc_agents.schemas import FormalField, FormalSection, ModuleNote, Plan, ProjectMap


# --- Pola ze skanera ---


def scanner_value(project_map: ProjectMap, scanner_spec: str) -> list[str]:
    """Zwraca wartość pola wypełnianego z mapy projektu: dla "entrypoints" punkty wejścia,
    dla "role:<rola>" ścieżki plików o tej roli. Nieznana specyfikacja kończy się ValueError.

    Po co: fakty, które zna skaner (punkty wejścia, pliki konfiguracyjne, sekrety), trafiają do
    dokumentu bez modelu - taniej i bez ryzyka zmyślenia. Pliki z sekretami to tylko ścieżki,
    skaner nigdy nie czyta ich treści.
    """
    if scanner_spec == "entrypoints":
        wartosc = list(project_map.entrypoints)
        return wartosc
    if scanner_spec.startswith("role:"):
        role = scanner_spec[len("role:"):]
        wartosc = []
        for entry in project_map.files:
            if entry.role == role:
                wartosc.append(entry.path)
        return wartosc

    komunikat_bledu = f"Nieznane źródło skanera w formal_template.yaml: '{scanner_spec}' (dozwolone: entrypoints, role:<rola>)"
    raise ValueError(komunikat_bledu)


# --- Pola z modelu ---


def build_llm_fields_text(template_fields: list[dict]) -> str:
    """Zwraca opis pól do wypełnienia przez model (source: llm) jako JSON: nazwa, tytuł, typ i instrukcja.

    Po co: model dostaje dokładnie te pola, które ma wypełnić, z poleceniem dla każdego -
    lista pochodzi z szablonu, więc zmiana pól nie wymaga zmian w kodzie ani w prompcie.
    """
    pola_dla_modelu = []
    for field_data in template_fields:
        if field_data["source"] == "llm":
            pola_dla_modelu.append(
                {
                    "name": field_data["name"],
                    "title": field_data["title"],
                    "type": field_data["type"],
                    "instruction": field_data["instruction"].strip(),
                }
            )
    tekst_pol = json.dumps(pola_dla_modelu, indent=2, ensure_ascii=False)
    return tekst_pol


def build_notes_text(notes: list[ModuleNote]) -> str:
    """Zwraca wszystkie notatki analityków jako jeden JSON (lista notatek).

    Po co: notatki są jedynym źródłem wiedzy redaktora o kodzie - dostaje je w całości.
    """
    notatki_dane = []
    for note in notes:
        notatki_dane.append(note.model_dump())
    tekst_notatek = json.dumps(notatki_dane, indent=2, ensure_ascii=False)
    return tekst_notatek


def build_editor_kb_text(knowledge_base_dir: str, filenames: list[str]) -> str:
    """Zwraca treść plików bazy wiedzy wybranych dla redaktora, każdy w tagu <plik_wiedzy nazwa="...">.

    Po co: redaktor pisze według zasad zespołu (np. documentation_goals.md). Odczyt przez
    read_kb_file() - nazwa od modelu nie może wskazać pliku spoza bazy wiedzy.
    """
    czesci = []
    for filename in filenames:
        czesci.append(f'<plik_wiedzy nazwa="{filename}">\n{read_kb_file(knowledge_base_dir, filename)}\n</plik_wiedzy>')

    tekst_wiedzy = "(planner nie wybrał plików bazy wiedzy dla redaktora)"
    if czesci:
        tekst_wiedzy = "\n\n".join(czesci)
    return tekst_wiedzy


def ask_formal_values(
    template_fields: list[dict], project_map: ProjectMap, plan: Plan, notes: list[ModuleNote], context: RunContext
) -> dict[str, list[str]]:
    """Wywołuje model agenta editor dla pól source: llm i zwraca słownik nazwa pola -> wartość (lista tekstów).
    Pola o nazwach spoza szablonu (zmyślone przez model) są pomijane.

    Po co: jedno wywołanie modelu dla wszystkich pól tekstowych części formalnej - model widzi
    całość notatek, więc wypełnia pola spójnie, a kod pilnuje, że do dokumentu trafią tylko pola z szablonu.
    """
    config = context.config
    variables = {
        "project_name": project_map.project_name,
        "plan_summary": plan.summary,
        "fields": build_llm_fields_text(template_fields),
        "notes": build_notes_text(notes),
        "kb_files": build_editor_kb_text(config.paths.knowledge_base, plan.editor_kb_files),
    }
    system_text, user_text = render_prompt(config.paths.prompts, "editor_formal", variables)
    odpowiedz = invoke_structured(
        context.models["editor"],
        FormalSection,
        get_structured_output_method(config, "editor"),
        [SystemMessage(content=system_text), HumanMessage(content=user_text)],
    )

    nazwy_z_szablonu = []
    for field_data in template_fields:
        nazwy_z_szablonu.append(field_data["name"])
    wartosci_pol = {}
    for formal_field in odpowiedz.fields:
        if formal_field.name in nazwy_z_szablonu:
            wartosci_pol[formal_field.name] = formal_field.value
    return wartosci_pol


# --- Składanie części formalnej ---


def assemble_formal_section(
    template_fields: list[dict], llm_values: dict[str, list[str]], project_map: ProjectMap
) -> tuple[FormalSection, list[str]]:
    """Składa wszystkie pola w kolejności z szablonu: pola source: scanner z mapy projektu, pola source: llm
    z odpowiedzi modelu. Zwraca (FormalSection z wartościami, lista nazw pól wymaganych bez wartości).

    Po co: jedno miejsce, w którym łączą się oba źródła wartości i sprawdzane są braki -
    kolejność i komplet pól zawsze wynikają z szablonu, nie z odpowiedzi modelu.
    """
    pola = []
    braki = []
    for field_data in template_fields:
        if field_data["source"] == "scanner":
            value = scanner_value(project_map, field_data["scanner"])
        else:
            value = llm_values.get(field_data["name"], [])
        pola.append(FormalField(name=field_data["name"], value=value))
        if field_data["required"] and not value:
            braki.append(field_data["name"])

    wynik = (FormalSection(fields=pola), braki)
    return wynik


def render_formal(knowledge_base_dir: str, project_name: str, template_fields: list[dict], section: FormalSection) -> str:
    """Składa Markdown części formalnej z szablonu templates/formal_template.md (Jinja2). Szablon dostaje
    project_name i listę pól (name, title, type, value); pole tekstowe ma elementy złączone pustą linią,
    pole listowe - listę tekstów.

    Po co: układ dokumentu tworzy kod według szablonu, a nie model - każda dokumentacja wygląda tak samo,
    a zespół zmienia układ w pliku .md bez zmian w kodzie.
    """
    wartosci = {}
    for formal_field in section.fields:
        wartosci[formal_field.name] = formal_field.value

    pola_do_szablonu = []
    for field_data in template_fields:
        value = wartosci[field_data["name"]]
        if field_data["type"] == "text":
            value = "\n\n".join(value)
        pola_do_szablonu.append(
            {"name": field_data["name"], "title": field_data["title"], "type": field_data["type"], "value": value}
        )

    template_path = os.path.join(knowledge_base_dir, "templates", "formal_template.md")
    with open(template_path, encoding="utf-8") as f:
        tekst_szablonu = f.read()
    srodowisko = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    markdown = srodowisko.from_string(tekst_szablonu).render(project_name=project_name, fields=pola_do_szablonu)
    return markdown


def create_formal_part(
    project_map: ProjectMap, plan: Plan, notes: list[ModuleNote], context: RunContext
) -> tuple[str, FormalSection, list[str]]:
    """Tworzy część formalną: wczytuje pola z formal_template.yaml, wypełnia pola source: llm modelem,
    pola source: scanner z mapy projektu, sprawdza braki i składa Markdown.
    Zwraca (Markdown, FormalSection z wartościami, lista brakujących pól wymaganych).

    Po co: cała logika części formalnej w jednej funkcji - użyje jej węzeł redaktora (krok 32) i test ręczny.
    """
    knowledge_base_dir = context.config.paths.knowledge_base
    template_fields = load_formal_fields(knowledge_base_dir)
    llm_values = ask_formal_values(template_fields, project_map, plan, notes, context)
    section, missing = assemble_formal_section(template_fields, llm_values, project_map)
    markdown = render_formal(knowledge_base_dir, project_map.project_name, template_fields, section)

    wynik = (markdown, section, missing)
    return wynik


def save_formal_part(run_store: RunStore, markdown: str, section: FormalSection, missing: list[str]) -> None:
    """Zapisuje w output/ część formalną (formal.md), pola z wartościami (formal_section.json)
    i listę brakujących pól wymaganych (formal_missing.txt; „brak” gdy wszystkie są).

    Po co: po przebiegu widać wynik redaktora i braki - także gdy dalszy etap się nie powiedzie.
    """
    run_store.save_text("formal.md", markdown)
    run_store.save_json("formal_section.json", section)
    tekst_brakow = "brak"
    if missing:
        tekst_brakow = "\n".join(missing)
    run_store.save_text("formal_missing.txt", tekst_brakow + "\n")


# --- Wczytanie wyników poprzednich etapów ---


def load_notes(run_store: RunStore) -> list[ModuleNote]:
    """Wczytuje wszystkie notatki analityków z output/notes/ (posortowane po nazwie pliku).

    Po co: test redaktora pracuje na notatkach z poprzedniego uruchomienia, bez ponownej analizy.
    """
    notatki = []
    for filename in sorted(os.listdir(run_store.path("notes"))):
        notatki.append(run_store.load_json("notes/" + filename, ModuleNote))
    return notatki


# --- Wyświetlanie ---


def print_formal_part(markdown: str, missing: list[str]) -> None:
    """Wypisuje złożoną część formalną i listę brakujących pól wymaganych.

    Po co: przy teście ręcznym widać od razu gotowy fragment dokumentu i to, czego w nim brakuje.
    """
    print(markdown)
    print("=== Brakujące pola wymagane ===")
    if not missing:
        print("brak")
    for name in missing:
        print(f"- {name}")


def print_missing_inputs(output_dir: str) -> None:
    """Wypisuje informację o braku wyników poprzedniego uruchomienia i jak je utworzyć.

    Po co: test redaktora korzysta z gotowej mapy, planu i notatek, żeby nie płacić za ponowną analizę.
    """
    print(f"Brak wyników poprzedniego uruchomienia w {output_dir} (project_map.json, plan.json, notes/).")
    print("Najpierw uruchom: python main.py --project <katalog projektu>")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: na wynikach poprzedniego uruchomienia main.py (output/ bez czyszczenia) tworzy część
    formalną (jedno wywołanie modelu), zapisuje ją w output/ i wypisuje razem z listą braków.

    Po co: strojenie promptu i szablonu części formalnej na stałych danych wejściowych - bez kosztu
    ponownej analizy i z porównywalnymi wynikami między uruchomieniami.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    context = create_run_context(config, clear_output=False)
    run_store = context.run_store
    if not os.path.isfile(run_store.path("plan.json")) or not os.path.isdir(run_store.path("notes")):
        print_missing_inputs(run_store.output_dir)
        return

    project_map = run_store.load_json("project_map.json", ProjectMap)
    plan = run_store.load_json("plan.json", Plan)
    notes = load_notes(run_store)

    markdown, section, missing = create_formal_part(project_map, plan, notes, context)
    save_formal_part(run_store, markdown, section, missing)
    print_formal_part(markdown, missing)


if __name__ == "__main__":
    manual_test()
