"""Skaner projektu: mapa projektu (ProjectMap) - pliki z rolami, framework, technologia, punkty wejścia i jednostki kodu.

Co robi:
    1. list_files() - przechodzi po katalogu projektu i zwraca posortowane ścieżki względne
       (separator "/"), pomijając pliki i katalogi pasujące do `scan.ignore` w config.yaml
       (np. .git, __pycache__, *.pyc) oraz zawsze - środowiska wirtualne Pythona, rozpoznawane
       po pliku pyvenv.cfg, a nie po nazwie (venv bywa nazwany dowolnie, np. test-venv).
    2. build_file_entries() - nadaje każdemu plikowi rolę (source, config, data, secret,
       binary, docs, other), rozmiar i nazwę frameworku, jeśli plik do niego należy;
       wynik to lista FileEntry do mapy projektu.
    3. build_project_map() - składa całą mapę projektu: nazwa, technologia, punkty wejścia,
       pliki i jednostki kodu do analizy (pliki źródłowe kodu projektu, bez frameworku
       i bez pustych plików). To jedyna funkcja, której potrzebuje reszta narzędzia.

Jak ustalana jest rola (pierwsza pasująca reguła wygrywa):
    secret  - nazwa pasuje do `scan.secret_patterns` (certyfikaty, klucze, .env). Sprawdzane
              jako pierwsze, a treść takiego pliku nie jest nawet otwierana.
    source  - kod źródłowy według technologii projektu (technology.is_source, np. .py).
    config / docs / data / binary - nazwa pasuje do wzorców z `scan.role_patterns`
              (kolejność ról z configu, np. requirements*.txt jako config przed *.txt jako data).
    binary / other - plik niepasujący do niczego: binary, jeśli wygląda na binarny
              (bajt zerowy w pierwszych 8 KB i brak znacznika BOM), w przeciwnym razie other.

Framework (`scan.frameworks`): słownik nazwa frameworku -> wzorce ścieżek. Plik pasujący do wzorców
dostaje framework_name; pozostałe pliki mają framework_name "" - to kod projektu. Dotyczy
frameworku skopiowanego do katalogu projektu; framework instalowany jako pakiet (pip) nie leży
w projekcie i widać go tylko w importach.

Wszystkie wzorce są w stylu powłoki (fnmatch: *, ?, [abc]) i nie rozróżniają wielkości liter.
Wzorce ignore, sekretów i ról porównujemy z samą nazwą pliku lub katalogu, wzorce frameworków -
z całą ścieżką względną (separator "/"; * obejmuje też podkatalogi, np. "framework/*").
Skaner nie czyta treści plików (poza pierwszymi 8 KB pliku o nieznanym typie) i niczego nie
uruchamia.

Uruchomienie testowe z katalogu repo (wypisuje tabelę plików, punkty wejścia, jednostki kodu i mapę jako JSON):
    python -m doc_agents.scanner <katalog projektu>
"""

import fnmatch
import os
import sys

from doc_agents.config import ScanConfig, load_config
from doc_agents.schemas import CodeUnit, FileEntry, ProjectMap
from doc_agents.technologies import detect_technology
from doc_agents.technologies.base import Technology


# --- Dopasowanie wzorców ---


def matches_any(name: str, patterns: list[str]) -> bool:
    """Sprawdza, czy nazwa (pliku lub katalogu) albo ścieżka względna pasuje do któregoś wzorca z listy.

    Po co: jedno miejsce porównywania nazw i ścieżek z regułami z configu (ignore, sekrety, role, frameworki),
    żeby wszystkie reguły działały tak samo. Wielkość liter nie ma znaczenia w każdym systemie
    (jak w Windows), żeby np. NOTES.TXT pasowało do wzorca "*.txt".
    """
    nazwa_malymi_literami = name.lower()
    pasuje_do_wzorca = False
    for pattern in patterns:
        if fnmatch.fnmatchcase(nazwa_malymi_literami, pattern.lower()):
            pasuje_do_wzorca = True
            break
    return pasuje_do_wzorca


def is_virtualenv(directory: str) -> bool:
    """Sprawdza, czy katalog jest środowiskiem wirtualnym Pythona, czyli czy zawiera plik pyvenv.cfg.

    Po co: venv w katalogu projektu to tysiące plików cudzych bibliotek, a jego nazwa bywa
    dowolna (venv, .venv, test-venv) - lista nazw w configu nie złapie każdej, a plik pyvenv.cfg
    jest w każdym venvie. Argument: ścieżka bezwzględna katalogu.
    """
    jest_venv = os.path.isfile(os.path.join(directory, "pyvenv.cfg"))
    return jest_venv


# --- Przejście po plikach ---


def list_files(root: str, scan: ScanConfig) -> list[str]:
    """Zwraca posortowaną listę ścieżek względnych (separator "/") wszystkich plików projektu,
    bez plików i katalogów pasujących do scan.ignore i bez środowisk wirtualnych.

    Po co: pierwszy krok analizy - z tej listy korzystają technologie (detect, punkty wejścia),
    klasyfikacja plików i mapa projektu. Separator "/" niezależnie od systemu, żeby ścieżki
    w mapie i w dokumencie wyglądały tak samo w Windows i w Linuksie (os.path.join w Windows
    przyjmuje je bez problemu).
    """
    root_abs = os.path.abspath(root)
    sciezki_plikow = []
    for directory, subdirectories, filenames in os.walk(root_abs):
        katalogi_do_przejscia = []
        for name in subdirectories:
            if matches_any(name, scan.ignore):
                continue
            if is_virtualenv(os.path.join(directory, name)):
                continue
            katalogi_do_przejscia.append(name)
        # zmiana listy w miejscu mówi os.walk, do których podkatalogów nie wchodzić
        subdirectories[:] = katalogi_do_przejscia

        for filename in filenames:
            if matches_any(filename, scan.ignore):
                continue
            relative_path = os.path.relpath(os.path.join(directory, filename), root_abs)
            sciezki_plikow.append(relative_path.replace(os.sep, "/"))

    posortowane_sciezki = sorted(sciezki_plikow, key=str.lower)
    return posortowane_sciezki


# --- Klasyfikacja plików ---


def looks_binary(full_path: str) -> bool:
    """Sprawdza po pierwszych 8 KB, czy plik jest binarny: zawiera bajt zerowy i nie zaczyna się od znacznika BOM.
    Pliku, którego nie da się otworzyć, też nie traktujemy jak tekstu (zwraca True).

    Po co: rozstrzyga rolę plików, których typu nie zna ani technologia, ani wzorce z configu -
    plik binarny nie może trafić do modelu jako tekst. Znacznik BOM wyklucza fałszywy alarm
    dla tekstu w UTF-16 (np. requirements.txt z `pip freeze >` w Windows PowerShell), w którym
    bajty zerowe są normalne.
    """
    try:
        with open(full_path, "rb") as f:
            poczatek_pliku = f.read(8192)
    except OSError:
        return True
    ma_bom = poczatek_pliku.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
    jest_binarny = not ma_bom and b"\x00" in poczatek_pliku
    return jest_binarny


def role_from_patterns(name: str, role_patterns: dict[str, list[str]]) -> str:
    """Zwraca pierwszą rolę z scan.role_patterns, do której wzorców pasuje nazwa pliku; "" gdy żadna.

    Po co: role plików innych niż kod (config, docs, data, binary) definiujemy w configu,
    żeby zespół mógł je dopasować do swoich projektów bez zmian w kodzie. Kolejność ról
    z configu decyduje, która wygrywa, gdy plik pasuje do kilku.
    """
    znaleziona_rola = ""
    for role, patterns in role_patterns.items():
        if matches_any(name, patterns):
            znaleziona_rola = role
            break
    return znaleziona_rola


def classify_file(root: str, path: str, scan: ScanConfig, technology: Technology | None) -> str:
    """Zwraca rolę pliku: secret, source, rolę z scan.role_patterns, a dla pozostałych binary albo other.

    Po co: rola decyduje, co dalej dzieje się z plikiem - kod idzie do analityków, config i dane
    są opisywane, a sekret trafia do modelu wyłącznie jako metadane. Dlatego sekrety są
    sprawdzane jako pierwsze, a looks_binary (jedyne miejsce czytające treść) wywołujemy dopiero
    dla plików nieznanego typu. Argumenty: root - katalog projektu, path - ścieżka względna,
    technology - technologia projektu albo None, gdy nie rozpoznano żadnej.
    """
    name = os.path.basename(path)
    if matches_any(name, scan.secret_patterns):
        rola_pliku = "secret"
    elif technology is not None and technology.is_source(path):
        rola_pliku = "source"
    else:
        rola_pliku = role_from_patterns(name, scan.role_patterns)
        if rola_pliku == "" and looks_binary(os.path.join(root, path)):
            rola_pliku = "binary"
        elif rola_pliku == "":
            rola_pliku = "other"
    return rola_pliku


def framework_for_path(path: str, frameworks: dict[str, list[str]]) -> str:
    """Zwraca nazwę pierwszego frameworku z scan.frameworks, do którego wzorców pasuje ścieżka pliku; "" gdy żadnego.

    Po co: pliki frameworku skopiowanego do projektu nie są kodem robota - dokumentacja
    ma je opisać ogólnie (z bazy wiedzy), a analitycy skupić się na kodzie projektu.
    Słownik zamiast jednej listy, bo w projekcie może być kilka frameworków (lub kilka wersji).
    Argument path: ścieżka względna z separatorem "/".
    """
    nazwa_frameworku = ""
    for framework_name, patterns in frameworks.items():
        if matches_any(path, patterns):
            nazwa_frameworku = framework_name
            break
    return nazwa_frameworku


def build_file_entries(root: str, files: list[str], scan: ScanConfig, technology: Technology | None) -> list[FileEntry]:
    """Zwraca listę FileEntry (ścieżka, rola, rozmiar w bajtach, nazwa frameworku) dla podanych plików projektu.

    Po co: z tej listy powstaje mapa projektu (krok 19) - planner widzi wszystkie pliki
    z rolami, rozmiarami i przynależnością do frameworku, a kolejne etapy wiedzą,
    które pliki wolno czytać i które są kodem projektu.
    """
    root_abs = os.path.abspath(root)
    wpisy_plikow = []
    for path in files:
        rola_pliku = classify_file(root_abs, path, scan, technology)
        rozmiar_pliku = os.path.getsize(os.path.join(root_abs, path))
        nazwa_frameworku = framework_for_path(path, scan.frameworks)
        wpis = FileEntry(path=path, role=rola_pliku, size_bytes=rozmiar_pliku, framework_name=nazwa_frameworku)
        wpisy_plikow.append(wpis)
    return wpisy_plikow


# --- Mapa projektu ---


def build_code_units(entries: list[FileEntry]) -> list[CodeUnit]:
    """Zwraca jednostki kodu do analizy: po jednej na każdy niepusty plik źródłowy kodu projektu (bez plików frameworku).

    Po co: jednostka kodu to zadanie dla jednego analityka (agenta LLM). Pliki frameworku
    pomijamy, bo nie są kodem robota (opisze je baza wiedzy), a puste pliki (np. pusty
    __init__.py) - bo nie ma w nich czego analizować, a każde wywołanie modelu kosztuje.
    Jeden plik = jedna jednostka pasuje do Pythona; technologie, w których proces składa się
    z kilku plików (np. UiPath), mogą tu później wymagać własnego grupowania.
    """
    jednostki_kodu = []
    for entry in entries:
        if entry.role != "source":
            continue
        if entry.framework_name != "":
            continue
        if entry.size_bytes == 0:
            continue
        jednostka = CodeUnit(name=entry.path, files=[entry.path])
        jednostki_kodu.append(jednostka)
    return jednostki_kodu


def build_project_map(root: str, scan: ScanConfig) -> ProjectMap:
    """Skanuje katalog projektu i zwraca jego mapę: nazwa (nazwa katalogu), ścieżka bezwzględna, technologia,
    punkty wejścia, pliki z rolami i frameworkiem oraz jednostki kodu do analizy.

    Po co: mapa projektu to wejście dla plannera i zapis w katalogu runu (project_map.json) -
    cała wiedza o projekcie zebrana bez modelu językowego i bez czytania treści plików.
    Gdy żadna technologia nie rozpozna projektu, technology jest "", a punktów wejścia brak.
    """
    root_abs = os.path.abspath(root)
    files = list_files(root_abs, scan)
    technology = detect_technology(root_abs, files)
    entries = build_file_entries(root_abs, files, scan, technology)

    technology_name = ""
    entrypoints = []
    if technology is not None:
        technology_name = technology.name
        entrypoints = technology.find_entrypoints(root_abs, files)

    mapa_projektu = ProjectMap(
        project_name=os.path.basename(root_abs),
        root=root_abs,
        technology=technology_name,
        entrypoints=entrypoints,
        files=entries,
        code_units=build_code_units(entries),
    )
    return mapa_projektu


# --- Wyświetlanie ---


def print_file_table(project_map: ProjectMap) -> None:
    """Wypisuje katalog projektu, technologię, tabelę plików (ścieżka, rola, framework, rozmiar)
    i liczbę plików w każdej roli. Pusty framework (kod projektu) wypisuje jako "-".

    Po co: podgląd wyniku skanera przy uruchomieniu testowym - od razu widać, czy reguły
    pominęły to, co trzeba, czy role są nadane sensownie (np. certyfikat jako secret)
    i które pliki należą do frameworku.
    """
    entries = project_map.files
    technology_name = "(nie rozpoznano)"
    if project_map.technology != "":
        technology_name = project_map.technology
    path_width = len("Ścieżka")
    framework_width = len("Framework")
    for entry in entries:
        path_width = max(path_width, len(entry.path))
        framework_width = max(framework_width, len(entry.framework_name))

    print(f"Projekt:     {project_map.project_name} ({project_map.root})")
    print(f"Technologia: {technology_name}")
    print(f"Plików:      {len(entries)}\n")
    print(f"  {'Ścieżka':<{path_width}}  {'Rola':<7}  {'Framework':<{framework_width}}  {'Rozmiar':>10}")
    print(f"  {'-' * path_width}  {'-' * 7}  {'-' * framework_width}  {'-' * 10}")
    for entry in entries:
        rozmiar_kb = f"{entry.size_bytes / 1024:.1f} KB"
        framework_do_wypisania = "-"
        if entry.framework_name != "":
            framework_do_wypisania = entry.framework_name
        print(f"  {entry.path:<{path_width}}  {entry.role:<7}  {framework_do_wypisania:<{framework_width}}  {rozmiar_kb:>10}")

    role_counts = {}
    for entry in entries:
        role_counts[entry.role] = role_counts.get(entry.role, 0) + 1
    opisy_rol = []
    for role in sorted(role_counts):
        opisy_rol.append(f"{role} {role_counts[role]}")
    print("\nRole: " + ", ".join(opisy_rol))


def print_entrypoints_and_units(project_map: ProjectMap) -> None:
    """Wypisuje punkty wejścia i jednostki kodu do analizy z mapy projektu.

    Po co: przy uruchomieniu testowym widać, od czego projekt startuje i ile wywołań
    analityka (modelu) będzie potrzebnych - po jednym na jednostkę.
    """
    print("\nPunkty wejścia:")
    for path in project_map.entrypoints:
        print(f"  {path}")
    print(f"\nJednostki kodu do analizy: {len(project_map.code_units)}")
    for unit in project_map.code_units:
        print(f"  {unit.name}")


def print_map_json(project_map: ProjectMap) -> None:
    """Wypisuje mapę projektu jako JSON (z wcięciami).

    Po co: pokazuje dokładnie to, co trafi do pliku project_map.json w katalogu runu i do plannera.
    """
    print("\n=== project_map.json ===\n")
    print(project_map.model_dump_json(indent=2))


# --- Uruchomienie ---


def parse_args() -> str:
    """Zwraca katalog projektu z pierwszego argumentu wiersza poleceń; bez argumentu - bieżący katalog.

    Po co: uruchomienie testowe przyjmuje tylko jeden argument, więc wystarcza sys.argv
    bez argparse.
    """
    katalog_projektu = os.getcwd()
    if len(sys.argv) > 1:
        katalog_projektu = sys.argv[1]
    return katalog_projektu


def main() -> None:
    """Uruchomienie testowe: wczytuje config.yaml z katalogu repo, buduje mapę projektu z argumentu
    i wypisuje tabelę plików, punkty wejścia, jednostki kodu oraz mapę jako JSON.

    Po co: ręczne sprawdzenie skanera na prawdziwym projekcie bez uruchamiania całego narzędzia.
    """
    root = os.path.abspath(parse_args())
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    project_map = build_project_map(root, config.scan)

    print_file_table(project_map)
    print_entrypoints_and_units(project_map)
    print_map_json(project_map)


if __name__ == "__main__":
    main()
