"""Schematy danych przekazywanych między etapami narzędzia (klasy Pydantic, bez logiki).

Co zawiera: opis kształtu danych, które jeden etap produkuje, a następny odbiera:
    skaner -> ProjectMap -> planner -> Plan -> analitycy -> ModuleNote -> redaktor -> recenzent -> ReviewResult
Na tym etapie jest tylko mapa projektu (FileEntry, CodeUnit, ProjectMap). Plan, ModuleNote
i ReviewResult dojdą w kolejnych krokach.

Po co:
    - jasna umowa między etapami - każdy wie, co dostaje i co oddaje,
    - każdy obiekt da się zapisać do JSON (model_dump_json) i wczytać z powrotem
      (model_validate_json) - tak powstają pliki w katalogu runu (np. project_map.json),
    - klasy wyników agentów przekazujemy modelowi językowemu jako schemat structured output,
    - mapa projektu zawiera ścieżki i metadane, a nie treść plików (kod czytamy z dysku dopiero przy analizie).

Uruchomienie testowe z katalogu repo (składa przykładową mapę ręcznie, wypisuje JSON i sprawdza odczyt):
    python -m doc_agents.schemas
"""

from pydantic import BaseModel


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


def print_round_trip(project_map_json: str, is_equal: bool) -> None:
    """Wypisuje mapę projektu jako JSON i wynik porównania odczytu z oryginałem.

    Po co: czytelny wynik testu ręcznego.
    """
    print(project_map_json)
    print(f"\nOdczyt z JSON zgodny z oryginałem: {is_equal}")


def manual_test() -> None:
    """Test ręczny: składa przykładową mapę projektu, zamienia ją na JSON, wczytuje z powrotem i porównuje.

    Po co: sprawdzenie, że schematy dają się zapisać do JSON i odczytać bez utraty danych -
    tak powstaje i jest czytany project_map.json.
    """
    project_map = build_example_project_map()
    project_map_json = project_map.model_dump_json(indent=2)
    loaded_map = ProjectMap.model_validate_json(project_map_json)
    print_round_trip(project_map_json, loaded_map == project_map)


if __name__ == "__main__":
    manual_test()
