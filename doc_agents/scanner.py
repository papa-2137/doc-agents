"""Skaner projektu: przejście po plikach katalogu projektu z pominięciem tego, czego nie dokumentujemy.

Co robi: zwraca posortowaną listę ścieżek względnych wszystkich plików projektu (separator "/"),
pomijając pliki i katalogi pasujące do wzorców z sekcji `scan.ignore` w config.yaml
(np. .git, __pycache__, *.pyc) oraz zawsze - środowiska wirtualne Pythona, rozpoznawane
po pliku pyvenv.cfg, a nie po nazwie (venv bywa nazwany dowolnie, np. test-venv).

Czego NIE robi: nie czyta treści plików i niczego nie uruchamia. Klasyfikacja plików (rola,
sekrety, framework) i budowa mapy projektu to kolejne funkcje tego modułu (kroki 17-19 planu).

Wzorce w `scan.ignore` są w stylu powłoki (fnmatch: *, ?, [abc]) i porównywane z samą nazwą
pliku lub katalogu, nie z całą ścieżką. Pasujący katalog jest pomijany razem z zawartością.

Uruchomienie testowe z katalogu repo (wypisuje listę plików projektu):
    python -m doc_agents.scanner <katalog projektu>
"""

import fnmatch
import os
import sys

from doc_agents.config import ScanConfig, load_config


# --- Reguły pomijania ---


def is_ignored(name: str, ignore_patterns: list[str]) -> bool:
    """Sprawdza, czy nazwa pliku lub katalogu pasuje do któregoś wzorca z listy ignore.

    Po co: jedno miejsce decyzji "pomijamy czy nie" dla plików i katalogów; reguły są w configu,
    żeby dało się je zmienić bez zmian w kodzie. Porównanie przez fnmatch, który w Windows
    nie rozróżnia wielkości liter (tak jak system plików).
    """
    pasuje_do_wzorca = any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns)
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
        # zmiana listy w miejscu mówi os.walk, do których podkatalogów nie wchodzić
        subdirectories[:] = [
            name for name in subdirectories
            if not is_ignored(name, scan.ignore) and not is_virtualenv(os.path.join(directory, name))
        ]
        for filename in filenames:
            if is_ignored(filename, scan.ignore):
                continue
            relative_path = os.path.relpath(os.path.join(directory, filename), root_abs)
            sciezki_plikow.append(relative_path.replace(os.sep, "/"))

    posortowane_sciezki = sorted(sciezki_plikow, key=str.lower)
    return posortowane_sciezki


# --- Wyświetlanie ---


def print_files(root: str, files: list[str]) -> None:
    """Wypisuje katalog projektu, liczbę plików i listę ścieżek.

    Po co: podgląd wyniku skanera przy uruchomieniu testowym - od razu widać, czy reguły
    pominęły to, co trzeba (np. __pycache__, venv), i nic ponad to.
    """
    print(f"Projekt: {os.path.abspath(root)}")
    print(f"Plików: {len(files)}\n")
    for path in files:
        print(f"  {path}")


# --- Uruchomienie ---


def parse_args() -> str:
    """Zwraca katalog projektu z pierwszego argumentu wiersza poleceń; bez argumentu - bieżący katalog.

    Po co: uruchomienie testowe przyjmuje tylko jeden argument, więc wystarcza sys.argv
    bez argparse.
    """
    katalog_projektu = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    return katalog_projektu


def main() -> None:
    """Uruchomienie testowe: wczytuje config.yaml z katalogu repo, skanuje projekt z argumentu i wypisuje listę plików.

    Po co: ręczne sprawdzenie skanera na prawdziwym projekcie bez uruchamiania całego narzędzia.
    """
    root = parse_args()
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    files = list_files(root, config.scan)
    print_files(root, files)


if __name__ == "__main__":
    main()
