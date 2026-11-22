"""Skaner projektu: lista plików dokumentowanego projektu, rola każdego pliku i przynależność do frameworku.

Co robi:
    1. list_files() - przechodzi po katalogu projektu i zwraca posortowane ścieżki względne
       (separator "/"), pomijając pliki i katalogi pasujące do `scan.ignore` w config.yaml
       (np. .git, __pycache__, *.pyc) oraz zawsze - środowiska wirtualne Pythona, rozpoznawane
       po pliku pyvenv.cfg, a nie po nazwie (venv bywa nazwany dowolnie, np. test-venv).
    2. build_file_entries() - nadaje każdemu plikowi rolę (source, config, data, secret,
       binary, docs, other), rozmiar i nazwę frameworku, jeśli plik do niego należy;
       wynik to lista FileEntry do mapy projektu.

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
uruchamia. Budowa całej mapy projektu to kolejna funkcja tego modułu (krok 19 planu).

Uruchomienie testowe z katalogu repo (wypisuje tabelę: ścieżka, rola, framework, rozmiar):
    python -m doc_agents.scanner <katalog projektu>
"""

import fnmatch
import os
import sys

from doc_agents.config import ScanConfig, load_config
from doc_agents.schemas import FileEntry
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


# --- Wyświetlanie ---


def print_file_table(root: str, technology: Technology | None, entries: list[FileEntry]) -> None:
    """Wypisuje katalog projektu, rozpoznaną technologię, tabelę plików (ścieżka, rola, framework, rozmiar)
    i liczbę plików w każdej roli. Pusty framework (kod projektu) wypisuje jako "-".

    Po co: podgląd wyniku skanera przy uruchomieniu testowym - od razu widać, czy reguły
    pominęły to, co trzeba, czy role są nadane sensownie (np. certyfikat jako secret)
    i które pliki należą do frameworku.
    """
    technology_name = "(nie rozpoznano)"
    if technology is not None:
        technology_name = technology.name
    path_width = len("Ścieżka")
    framework_width = len("Framework")
    for entry in entries:
        path_width = max(path_width, len(entry.path))
        framework_width = max(framework_width, len(entry.framework_name))

    print(f"Projekt:     {os.path.abspath(root)}")
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
    """Uruchomienie testowe: wczytuje config.yaml z katalogu repo, skanuje projekt z argumentu,
    rozpoznaje technologię, nadaje role plikom i wypisuje tabelę.

    Po co: ręczne sprawdzenie skanera na prawdziwym projekcie bez uruchamiania całego narzędzia.
    """
    root = os.path.abspath(parse_args())
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    files = list_files(root, config.scan)
    technology = detect_technology(root, files)
    entries = build_file_entries(root, files, config.scan, technology)

    print_file_table(root, technology, entries)


if __name__ == "__main__":
    main()
