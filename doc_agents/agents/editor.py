"""Agent redaktor: składa dokument z części formalnej i opisowej.

Część formalna - lista kontrolna informacji operacyjnych o robocie. create_formal_part() wypełnia pola części formalnej opisane w
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

Część opisowa - rozdziały z planu (plan.sections), w tym stałe z descriptive_template.yaml.
create_descriptive_part() wywołuje model drugi raz: dostaje rozdziały z instrukcjami, notatki,
gotową część formalną (żeby jej nie powtarzać) i pliki wiedzy redaktora. Model zwraca DescriptivePart:
listę rozdziałów (tytuł, treść w Markdown). Nagłówki ### wstawia kod w kolejności z planu;
rozdziały o tytułach spoza planu są pomijane. Rozdział wymagany (required: true w YAML) bez treści
albo nieobecny w planie dostaje „_Brak danych._” i trafia na listę braków.

Cały dokument składa render_document() z szablonu knowledge_base/templates/document_template.md
(tytuł, część formalna, część opisowa) - układ zmienia się w szablonie, nie w kodzie.

Wyniki w output/: formal.md, formal_section.json, formal_missing.txt, descriptive_part.json,
descriptive_missing.txt i document.md (cały dokument).

Na tym etapie redaktor działa bez grafu (węzeł redaktora dojdzie w kroku 32).

Test ręczny z katalogu repo - na wynikach poprzedniego uruchomienia main.py (output/ nie jest
czyszczony; dwa wywołania modelu: część formalna i opisowa; wymaga LLM_API_KEY i LLM_BASE_URL):
    python -m doc_agents.agents.editor
"""

import json
import os

from jinja2 import Environment, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage

from doc_agents.config import load_config
from doc_agents.context import RunContext, create_run_context
from doc_agents.knowledge import load_formal_fields, load_required_section_titles, read_kb_file
from doc_agents.llm import get_structured_output_method, invoke_structured
from doc_agents.output import RunStore
from doc_agents.prompts import render_prompt
from doc_agents.schemas import (
    DescriptivePart,
    DescriptiveSection,
    FormalField,
    FormalSection,
    ModuleNote,
    Plan,
    ProjectMap,
)


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


# --- Część opisowa ---


def build_sections_text(sections: list[DescriptiveSection]) -> str:
    """Zwraca rozdziały do napisania (tytuł i instrukcja) jako JSON, w kolejności z planu.

    Po co: model dostaje dokładnie te rozdziały, które zaplanował planner, z instrukcją dla każdego.
    """
    rozdzialy_dane = []
    for section in sections:
        rozdzialy_dane.append(section.model_dump())
    tekst_rozdzialow = json.dumps(rozdzialy_dane, indent=2, ensure_ascii=False)
    return tekst_rozdzialow


def ask_descriptive_part(
    project_map: ProjectMap, plan: Plan, notes: list[ModuleNote], formal_markdown: str, context: RunContext
) -> DescriptivePart:
    """Wywołuje model agenta editor dla rozdziałów części opisowej z planu i zwraca jego odpowiedź (DescriptivePart).

    Po co: drugie wywołanie redaktora - pisze rozdziały dla osoby utrzymującej robota. Model widzi
    gotową część formalną, żeby jej nie powtarzać.
    """
    config = context.config
    variables = {
        "project_name": project_map.project_name,
        "plan_summary": plan.summary,
        "sections": build_sections_text(plan.sections),
        "formal_part": formal_markdown,
        "notes": build_notes_text(notes),
        "kb_files": build_editor_kb_text(config.paths.knowledge_base, plan.editor_kb_files),
    }
    system_text, user_text = render_prompt(config.paths.prompts, "editor_descriptive", variables)
    odpowiedz = invoke_structured(
        context.models["editor"],
        DescriptivePart,
        get_structured_output_method(config, "editor"),
        [SystemMessage(content=system_text), HumanMessage(content=user_text)],
    )
    return odpowiedz


def assemble_descriptive_part(
    sections: list[DescriptiveSection], part: DescriptivePart, required_titles: list[str]
) -> tuple[str, list[str]]:
    """Składa Markdown części opisowej: rozdział po rozdziale w kolejności z planu, z nagłówkiem ### i treścią
    od modelu. Rozdziały wymagane, których nie ma w planie, dochodzą na końcu. Rozdział bez treści dostaje
    „_Brak danych._”. Zwraca (Markdown, lista tytułów wymaganych rozdziałów bez treści).

    Po co: kolejność i nagłówki zawsze wynikają z planu, a obecność wymaganych rozdziałów (np. „Ścieżki procesu
    krok po kroku”) sprawdza kod - bez czekania na recenzenta. Tytuły porównywane bez wielkości liter.
    """
    tresci = {}
    for chapter in part.chapters:
        tresci[chapter.title.strip().lower()] = chapter.content.strip()

    tytuly = []
    for section in sections:
        tytuly.append(section.title)
    tytuly_male = []
    for title in tytuly:
        tytuly_male.append(title.strip().lower())
    for title in required_titles:
        if title.strip().lower() not in tytuly_male:
            tytuly.append(title)

    tytuly_wymagane_male = []
    for title in required_titles:
        tytuly_wymagane_male.append(title.strip().lower())

    czesci = []
    braki = []
    for title in tytuly:
        content = tresci.get(title.strip().lower(), "")
        if content == "":
            content = "_Brak danych._"
            if title.strip().lower() in tytuly_wymagane_male:
                braki.append(title)
        czesci.append(f"### {title}\n\n{content}\n")

    wynik = ("\n".join(czesci), braki)
    return wynik


def create_descriptive_part(
    project_map: ProjectMap, plan: Plan, notes: list[ModuleNote], formal_markdown: str, context: RunContext
) -> tuple[str, DescriptivePart, list[str]]:
    """Tworzy część opisową: wywołuje model dla rozdziałów z planu, składa Markdown z nagłówkami i sprawdza
    wymagane rozdziały. Zwraca (Markdown części opisowej, odpowiedź modelu, lista brakujących wymaganych rozdziałów).

    Po co: cała logika części opisowej w jednej funkcji - użyje jej węzeł redaktora (krok 32) i test ręczny.
    """
    part = ask_descriptive_part(project_map, plan, notes, formal_markdown, context)
    required_titles = load_required_section_titles(context.config.paths.knowledge_base)
    markdown, missing = assemble_descriptive_part(plan.sections, part, required_titles)

    wynik = (markdown, part, missing)
    return wynik


def save_descriptive_part(run_store: RunStore, part: DescriptivePart, missing: list[str]) -> None:
    """Zapisuje w output/ odpowiedź modelu z rozdziałami (descriptive_part.json) i listę brakujących
    wymaganych rozdziałów (descriptive_missing.txt; „brak” gdy wszystkie są).

    Po co: po przebiegu widać surową treść rozdziałów i braki, niezależnie od złożonego dokumentu.
    """
    run_store.save_json("descriptive_part.json", part)
    tekst_brakow = "brak"
    if missing:
        tekst_brakow = "\n".join(missing)
    run_store.save_text("descriptive_missing.txt", tekst_brakow + "\n")


# --- Cały dokument ---


def render_document(knowledge_base_dir: str, project_name: str, formal_markdown: str, descriptive_markdown: str) -> str:
    """Składa cały dokument z szablonu templates/document_template.md (Jinja2): tytuł, część formalna, część opisowa.

    Po co: układ całego dokumentu (np. tytuł, data, stopka) zespół zmienia w szablonie, bez zmian w kodzie.
    """
    template_path = os.path.join(knowledge_base_dir, "templates", "document_template.md")
    with open(template_path, encoding="utf-8") as f:
        tekst_szablonu = f.read()
    srodowisko = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    dokument = srodowisko.from_string(tekst_szablonu).render(
        project_name=project_name, formal_part=formal_markdown, descriptive_part=descriptive_markdown
    )
    return dokument


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


def print_missing(title: str, missing: list[str]) -> None:
    """Wypisuje nagłówek i listę braków („brak”, gdy lista pusta).

    Po co: wspólny format listy brakujących pól i rozdziałów w teście ręcznym.
    """
    print(f"=== {title} ===")
    if not missing:
        print("brak")
    for name in missing:
        print(f"- {name}")


def print_document(document: str, formal_missing: list[str], descriptive_missing: list[str], document_path: str) -> None:
    """Wypisuje cały dokument, listy braków w obu częściach i ścieżkę zapisanego pliku.

    Po co: przy teście ręcznym widać od razu gotowy dokument i to, czego w nim brakuje.
    """
    print(document)
    print_missing("Brakujące pola wymagane (część formalna)", formal_missing)
    print_missing("Brakujące rozdziały wymagane (część opisowa)", descriptive_missing)
    print(f"\nDokument: {document_path}")


def print_missing_inputs(output_dir: str) -> None:
    """Wypisuje informację o braku wyników poprzedniego uruchomienia i jak je utworzyć.

    Po co: test redaktora korzysta z gotowej mapy, planu i notatek, żeby nie płacić za ponowną analizę.
    """
    print(f"Brak wyników poprzedniego uruchomienia w {output_dir} (project_map.json, plan.json, notes/).")
    print("Najpierw uruchom: python main.py --project <katalog projektu>")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: na wynikach poprzedniego uruchomienia main.py (output/ bez czyszczenia) tworzy część
    formalną i opisową (dwa wywołania modelu), składa cały dokument, zapisuje wyniki w output/
    i wypisuje dokument razem z listami braków.

    Po co: strojenie promptów i szablonów redaktora na stałych danych wejściowych - bez kosztu
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

    formal_markdown, section, formal_missing = create_formal_part(project_map, plan, notes, context)
    save_formal_part(run_store, formal_markdown, section, formal_missing)
    descriptive_markdown, part, descriptive_missing = create_descriptive_part(
        project_map, plan, notes, formal_markdown, context
    )
    save_descriptive_part(run_store, part, descriptive_missing)

    knowledge_base_dir = config.paths.knowledge_base
    document = render_document(knowledge_base_dir, project_map.project_name, formal_markdown, descriptive_markdown)
    document_path = run_store.save_text("document.md", document)
    print_document(document, formal_missing, descriptive_missing, document_path)


if __name__ == "__main__":
    manual_test()
