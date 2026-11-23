"""Schematy danych przekazywanych między etapami narzędzia (klasy Pydantic, bez logiki).

Co zawiera: opis kształtu danych, które jeden etap produkuje, a następny odbiera:
    skaner -> ProjectMap -> planner -> Plan -> analitycy -> ModuleNote -> redaktor -> recenzent -> ReviewResult
Na tym etapie: mapa projektu (FileEntry, CodeUnit, ProjectMap), plan plannera (AnalysisTask,
DescriptiveSection, Plan), notatka analityka (ModuleNote) oraz części dokumentu od redaktora:
formalna (FormalField, FormalSection) i opisowa (DescriptiveChapter, DescriptivePart),
oraz wynik recenzji (ReviewResult).

Schematy odpowiedzi modelu (Plan i jego części, ModuleNote, FormalSection, DescriptivePart, ReviewResult) mają przy polach Field(description="...") - wyjątek
od zasady prostoty z AGENTS.md: model widzi tylko schemat JSON, a opis pola jedzie razem z nim,
więc nie rozjedzie się z kodem (komentarze # do modelu nie trafiają). Pozostałe schematy - same typy.

Po co:
    - jasna umowa między etapami - każdy wie, co dostaje i co oddaje,
    - każdy obiekt da się zapisać do JSON (model_dump_json) i wczytać z powrotem
      (model_validate_json) - tak powstają pliki w katalogu runu (np. project_map.json),
    - klasy wyników agentów przekazujemy modelowi językowemu jako schemat structured output,
    - mapa projektu zawiera ścieżki i metadane, a nie treść plików (kod czytamy z dysku dopiero przy analizie).

Test ręczny z katalogu repo (składa ręcznie przykładową mapę i przykładowy plan, wypisuje JSON,
sprawdza odczyt i pokazuje schemat JSON planu, który dostanie model):
    python -m doc_agents.schemas
"""

import json

from pydantic import BaseModel, Field


# --- Mapa projektu (wynik skanera) ---


class FileEntry(BaseModel):
    """Jeden plik dokumentowanego projektu."""

    path: str  # ścieżka względna do katalogu projektu
    role: str  # source | config | data | secret | binary | docs | other
    size_bytes: int
    framework_name: str = ""  # nazwa frameworku, do którego należy plik; "" = kod projektu (custom)


class CodeUnit(BaseModel):
    """Jednostka kodu do analizy - zadanie dla jednego analityka.

    W Pythonie jedna jednostka to zwykle jeden plik; lista plików zostawia miejsce na technologie,
    w których jeden proces składa się z kilku plików (np. UiPath).
    """

    name: str
    files: list[str]


class ProjectMap(BaseModel):
    """Wynik skanera: co jest w projekcie, bez treści plików."""

    project_name: str
    root: str  # ścieżka bezwzględna do katalogu projektu
    technology: str  # np. python; "" = nie rozpoznano technologii
    entrypoints: list[str]  # ścieżki względne plików startowych
    files: list[FileEntry]
    code_units: list[CodeUnit]  # pliki źródłowe kodu projektu (bez frameworku)



# --- Plan (wynik plannera, schemat odpowiedzi modelu) ---


class AnalysisTask(BaseModel):
    """Zadanie dla jednego analityka: jedna jednostka kodu do przeanalizowania."""

    unit_name: str = Field(
        description="Nazwa jednostki kodu dokładnie tak, jak w mapie projektu (code_units[].name), np. 'src/report.py'."
    )
    hint: str = Field(
        description="Krótka wskazówka dla analityka: na co zwrócić uwagę w tej jednostce (np. punkt wejścia, "
        "metody wywoływane przez framework, praca z plikami danych, obsługa błędów)."
    )


class DescriptiveSection(BaseModel):
    """Rozdział części opisowej dokumentu (ten sam kształt co stałe rozdziały w descriptive_template.yaml)."""

    title: str = Field(description="Tytuł rozdziału - nagłówek w dokumencie.")
    instruction: str = Field(description="Co redaktor ma napisać w tym rozdziale - konkretnie dla tego projektu.")


class Plan(BaseModel):
    """Plan pracy zespołu dla dokumentowanego projektu - odpowiedź plannera."""

    summary: str = Field(
        description="2-4 zdania: czym jest projekt i jak działa, na podstawie mapy projektu, bez zgadywania treści plików."
    )
    tasks: list[AnalysisTask] = Field(description="Po jednym zadaniu dla każdej jednostki kodu z mapy projektu.")
    analyst_kb_files: list[str] = Field(
        description="Nazwy plików ze spisu bazy wiedzy potrzebnych analitykom (wspólne dla wszystkich analityków)."
    )
    editor_kb_files: list[str] = Field(description="Nazwy plików ze spisu bazy wiedzy potrzebnych redaktorowi.")
    sections: list[DescriptiveSection] = Field(
        description="Rozdziały części opisowej w kolejności w dokumencie: wszystkie stałe rozdziały (z niezmienionym "
        "tytułem i instrukcją) oraz rozdziały dodatkowe dopasowane do tego projektu."
    )

# --- Notatka analityka (wynik analityka, schemat odpowiedzi modelu) ---


class ModuleNote(BaseModel):
    """Notatka analityka o jednej jednostce kodu - jedyne źródło wiedzy o kodzie dla redaktora."""

    unit_name: str = Field(description="Nazwa analizowanej jednostki kodu, dokładnie jak w zadaniu.")
    purpose: str = Field(
        description="2-4 zdania: do czego służy ta jednostka i jaką rolę pełni w procesie robota. "
        "Jeden akapit zwykłego tekstu, nie lista."
    )
    automated_application: str = Field(
        description="Aplikacje, strony i systemy, z którymi ta jednostka pracuje (np. 'przeglądarka Edge, "
        "https://www.rpachallenge.com'); pusty tekst, gdy żadnych."
    )
    key_functions: list[str] = Field(
        description="Najważniejsze funkcje, metody i klasy jednostki, każda jako 'nazwa: co robi'."
    )
    process_steps: list[str] = Field(
        description="Kolejne akcje robota w tej jednostce w kolejności wykonania, jako krótkie zdania z konkretami "
        "(aplikacje, adresy, przyciski, pola, selektory, pliki, arkusze). Decyzje jako 'Jeśli ..., to ...', "
        "pętle jako 'Dla każdego ...:' z krokami wciętymi pod spodem. Kroki osobno wywoływanych funkcji "
        "poprzedzone nazwą funkcji w nawiasach kwadratowych."
    )
    error_handling: list[str] = Field(
        description="Obsługiwane wyjątki i sytuacje błędne oraz to, co robot wtedy robi (ponowienie, pominięcie, "
        "zatrzymanie, zapis do logu)."
    )
    inputs: list[str] = Field(description="Dane wejściowe jednostki: pliki, arkusze, kolumny, parametry, dane ze stron.")
    outputs: list[str] = Field(description="Wyniki jednostki: zapisywane pliki, tabele, raporty, logi, dane przekazywane dalej.")
    config_used: list[str] = Field(
        description="Używana konfiguracja: klucze z plików konfiguracyjnych, zmienne środowiskowe, stałe w kodzie "
        "(z nazwą i znaczeniem, bez wartości sekretów)."
    )
    external_dependencies: list[str] = Field(
        description="Biblioteki i frameworki spoza projektu, z których korzysta jednostka, z krótkim 'do czego'. "
        "Bez biblioteki standardowej języka (np. os, json, pathlib) - tylko to, co trzeba zainstalować."
    )
    pitfalls: list[str] = Field(
        description="Pułapki i ryzyka: kruche selektory, sztywne ścieżki i czasy oczekiwania, sekrety w kodzie, "
        "brak obsługi błędów, niejasne miejsca."
    )
    maintainer_hints: list[str] = Field(
        description="Konkretne wskazówki dla opiekuna: co zmienić przy zmianie strony lub danych, gdzie szukać "
        "przyczyny błędu, czego nie ruszać."
    )


# --- Część formalna (wynik redaktora, schemat odpowiedzi modelu) ---


class FormalField(BaseModel):
    """Jedno pole części formalnej: nazwa z formal_template.yaml i wartość.

    Schemat jest ogólny - lista pól nie jest wpisana w kod, tylko wynika z szablonu.
    """

    name: str = Field(description="Identyfikator pola dokładnie jak 'name' w liście pól do wypełnienia.")
    value: list[str] = Field(
        description="Wartość pola jako lista tekstów: dla pola typu text jeden element (akapit), dla pola typu list "
        "jeden element na punkt. Pusta lista, gdy brak informacji."
    )


class FormalSection(BaseModel):
    """Wypełnione pola części formalnej."""

    fields: list[FormalField] = Field(description="Po jednym wpisie dla każdego pola z listy pól do wypełnienia.")


# --- Część opisowa (wynik redaktora, schemat odpowiedzi modelu) ---


class DescriptiveChapter(BaseModel):
    """Jeden rozdział części opisowej: tytuł z planu i treść w Markdown."""

    title: str = Field(description="Tytuł rozdziału dokładnie jak w liście rozdziałów do napisania.")
    content: str = Field(
        description="Treść rozdziału w Markdown, bez nagłówków #, ## i ### (nagłówek wstawia kod); "
        "podsekcje nagłówkiem ####. Pusty tekst, gdy notatki nie dają informacji."
    )


class DescriptivePart(BaseModel):
    """Napisane rozdziały części opisowej."""

    chapters: list[DescriptiveChapter] = Field(
        description="Po jednym rozdziale dla każdej pozycji z listy rozdziałów, w tej samej kolejności."
    )


# --- Recenzja (wynik recenzenta, schemat odpowiedzi modelu) ---


class ReviewResult(BaseModel):
    """Wynik recenzji dokumentu: decyzja, problemy do poprawy i sugestie."""

    approved: bool = Field(description="true tylko wtedy, gdy lista issues jest pusta - dokument nie wymaga poprawek.")
    issues: list[str] = Field(
        description="Problemy do poprawy w kolejnej wersji; każdy zaczyna się od nazwy rozdziału lub pola "
        "w nawiasie kwadratowym i mówi, co dokładnie poprawić."
    )
    suggestions: list[str] = Field(
        description="Drobne uwagi, które nie blokują akceptacji; ten sam format co issues."
    )


# --- Test ręczny ---


def build_example_project_map() -> ProjectMap:
    """Składa ręcznie przykładową mapę projektu (kilka plików robota testowego, dwie jednostki kodu).

    Po co: dane do testu zapisu i odczytu JSON bez uruchamiania skanera. Prawdziwą mapę buduje
    scanner.build_project_map().
    """
    files = [
        FileEntry(path="main.py", role="source", size_bytes=5801),
        FileEntry(path="src/parabank_page.py", role="source", size_bytes=2986),
        FileEntry(path="config.yml", role="config", size_bytes=560),
        FileEntry(path="resources/in/challenge.xlsx", role="data", size_bytes=34124),
        FileEntry(path="certs/client.pfx", role="secret", size_bytes=162),
    ]
    code_units = [
        CodeUnit(name="main.py", files=["main.py"]),
        CodeUnit(name="src/parabank_page.py", files=["src/parabank_page.py"]),
    ]
    przykladowa_mapa = ProjectMap(
        project_name="01_rpa_challange_roboforge",
        root=r"C:\Users\jankiwoj_box\Documents\projects\claude\tests\01_rpa_challange_roboforge",
        technology="python",
        entrypoints=["main.py"],
        files=files,
        code_units=code_units,
    )
    return przykladowa_mapa


def build_example_plan() -> Plan:
    """Składa ręcznie przykładowy plan dla robota testowego (dwa zadania, jeden stały i jeden dodatkowy rozdział).

    Po co: dane do testu zapisu i odczytu planu bez wywoływania modelu. Prawdziwy plan zwróci planner (krok 27).
    """
    przykladowy_plan = Plan(
        summary="Robot RPA w Pythonie na frameworku Roboforge: wypełnia formularze RPA Challenge danymi z Excela "
        "i sprawdza saldo w ParaBank; wyniki zapisuje w bazie SQLite.",
        tasks=[
            AnalysisTask(unit_name="main.py", hint="Punkt wejścia; metody wywoływane przez framework Roboforge."),
            AnalysisTask(unit_name="src/challange_page.py", hint="Obsługa strony RPA Challenge: selektory i kolejność pól."),
        ],
        analyst_kb_files=["rpa_framework.md", "python_conventions.md"],
        editor_kb_files=["documentation_goals.md", "rpa_framework.md"],
        sections=[
            DescriptiveSection(title="Ścieżki procesu krok po kroku", instruction="Instrukcja ze stałego rozdziału."),
            DescriptiveSection(title="Praca z plikiem Excel", instruction="Jak robot czyta challenge.xlsx i co się dzieje przy błędnym wierszu."),
        ],
    )
    return przykladowy_plan


def print_round_trip(title: str, model_json: str, is_equal: bool) -> None:
    """Wypisuje obiekt jako JSON z tytułem i wynik porównania odczytu z oryginałem.

    Po co: czytelny wynik testu ręcznego zapisu i odczytu.
    """
    print(f"=== {title} ===\n")
    print(model_json)
    print(f"\nOdczyt z JSON zgodny z oryginałem: {is_equal}\n")


def print_schema(title: str, schema_json: str) -> None:
    """Wypisuje schemat JSON z tytułem.

    Po co: pokazuje, co dokładnie zobaczy model jako format odpowiedzi (pola, typy i opisy z Field).
    """
    print(f"=== {title} ===\n")
    print(schema_json)


def manual_test() -> None:
    """Test ręczny: zapis i odczyt JSON przykładowej mapy projektu i przykładowego planu oraz schemat JSON planu.

    Po co: sprawdzenie, że schematy dają się zapisać i odczytać bez utraty danych (tak powstają
    project_map.json i plan.json) i że opisy pól planu trafiają do schematu dla modelu.
    """
    project_map = build_example_project_map()
    project_map_json = project_map.model_dump_json(indent=2)
    print_round_trip("ProjectMap", project_map_json, ProjectMap.model_validate_json(project_map_json) == project_map)

    plan = build_example_plan()
    plan_json = plan.model_dump_json(indent=2)
    print_round_trip("Plan", plan_json, Plan.model_validate_json(plan_json) == plan)

    plan_schema_json = json.dumps(Plan.model_json_schema(), indent=2, ensure_ascii=False)
    print_schema("Schemat JSON planu (format odpowiedzi modelu)", plan_schema_json)


if __name__ == "__main__":
    manual_test()
