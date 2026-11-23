"""Katalog wyników: miejsce na pliki, które narzędzie tworzy przy uruchomieniu - zawsze tylko z ostatniego uruchomienia.

Co robi: create_run_store() czyści katalog wyników output/ w katalogu repozytorium narzędzia
(stała lokalizacja, nie ustawia się jej w configu) i zwraca obiekt RunStore, przez który etapy zapisują i odczytują swoje wyniki: mapę projektu,
plan, notatki analityków, dokument końcowy. Każdy plik ma nazwę względną do katalogu wyników
(np. "project_map.json").

Po co: widać, co narzędzie wyprodukowało na każdym etapie (łatwiej szukać przyczyny słabego
dokumentu), a etap da się powtórzyć na zapisanych danych bez ponownego wywoływania modelu.
Katalog zawiera tylko ostatnie uruchomienie - wynik, który chcesz zachować, skopiuj w inne miejsce.

Pliki JSON zapisujemy i czytamy jako klasy Pydantic ze schemas.py (model_dump_json / model_validate_json),
wszystko w UTF-8. Katalog output/ jest w .gitignore.

Uruchomienie testowe z katalogu repo (buduje mapę projektu, zapisuje ją w katalogu wyników i czyta z powrotem):
    python -m doc_agents.output <katalog projektu>
"""

import os
import shutil
import sys

from pydantic import BaseModel

from doc_agents.config import load_config
from doc_agents.scanner import build_project_map
from doc_agents.schemas import ProjectMap


# --- Katalog wyników ---


class RunStore:
    """Dostęp do plików w katalogu wyników: zapis i odczyt JSON (klasy Pydantic) oraz tekstu, nazwy plików względne do katalogu."""

    def __init__(self, output_dir: str):
        """Zapamiętuje ścieżkę bezwzględną katalogu wyników (katalog musi już istnieć - zakłada go create_run_store).

        Po co: wszystkie metody budują ścieżki plików od tego katalogu, więc etapy narzędzia
        podają tylko nazwę pliku i nie muszą wiedzieć, gdzie leżą wyniki.
        """
        self.output_dir = output_dir

    def path(self, name: str) -> str:
        """Zwraca ścieżkę bezwzględną pliku o podanej nazwie w katalogu wyników.

        Po co: jedno miejsce składania ścieżek; przydaje się też do wypisania użytkownikowi,
        gdzie leży wynik.
        """
        sciezka_pliku = os.path.join(self.output_dir, name)
        return sciezka_pliku

    def save_text(self, name: str, text: str) -> str:
        """Zapisuje tekst do pliku w katalogu wyników (UTF-8, nadpisuje istniejący) i zwraca ścieżkę pliku.

        Po co: zapis wyników tekstowych, np. dokumentu Markdown albo promptu wysłanego do modelu.
        """
        sciezka_pliku = self.path(name)
        with open(sciezka_pliku, "w", encoding="utf-8") as f:
            f.write(text)
        return sciezka_pliku

    def save_json(self, name: str, model: BaseModel) -> str:
        """Zapisuje obiekt Pydantic jako JSON z wcięciami (UTF-8) i zwraca ścieżkę pliku.

        Po co: wyniki etapów (mapa projektu, plan, notatki) to klasy ze schemas.py - zapis
        w JSON pozwala je obejrzeć w edytorze i wczytać ponownie w kolejnym etapie.
        """
        tekst_json = model.model_dump_json(indent=2)
        sciezka_pliku = self.save_text(name, tekst_json)
        return sciezka_pliku

    def load_json(self, name: str, model_class: type[BaseModel]) -> BaseModel:
        """Wczytuje plik JSON z katalogu wyników jako obiekt podanej klasy Pydantic.

        Po co: kolejny etap (albo powtórzony etap) odczytuje wynik poprzedniego zamiast liczyć
        go od nowa. Plik niezgodny ze schematem kończy się błędem walidacji Pydantica.
        """
        with open(self.path(name), encoding="utf-8") as f:
            tekst_json = f.read()
        obiekt = model_class.model_validate_json(tekst_json)
        return obiekt


def create_run_store() -> RunStore:
    """Usuwa katalog output/ w katalogu repozytorium narzędzia razem z wynikami poprzedniego uruchomienia,
    zakłada go od nowa pusty i zwraca RunStore.

    Po co: w katalogu wyników są zawsze tylko pliki z ostatniego uruchomienia - nie zostają
    stare pliki, które mogłyby się pomylić z nowymi (np. notatka modułu usuniętego z projektu).
    Stała lokalizacja (a nie ścieżka z configu) wyklucza pomyłkę, po której czyszczenie
    skasowałoby inny katalog.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_abs = os.path.join(repo_dir, "output")
    if os.path.exists(output_abs):
        shutil.rmtree(output_abs)
    os.makedirs(output_abs)

    magazyn_wynikow = RunStore(output_abs)
    return magazyn_wynikow


# --- Wyświetlanie ---


def print_round_trip(saved_path: str, is_equal: bool) -> None:
    """Wypisuje ścieżkę zapisanego pliku i wynik porównania odczytu z oryginałem.

    Po co: czytelny wynik uruchomienia testowego.
    """
    print(f"Zapisano:                          {saved_path}")
    print(f"Odczyt z pliku zgodny z oryginałem: {is_equal}")


# --- Test ręczny ---


def manual_test() -> None:
    """Uruchomienie testowe: buduje mapę projektu z argumentu, zapisuje ją jako project_map.json
    w wyczyszczonym katalogu output/, wczytuje z powrotem i porównuje z oryginałem.

    Po co: ręczne sprawdzenie zapisu i odczytu wyników na prawdziwej mapie projektu.
    """
    root = os.getcwd()
    if len(sys.argv) > 1:
        root = sys.argv[1]
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    project_map = build_project_map(root, config.scan)
    run_store = create_run_store()
    saved_path = run_store.save_json("project_map.json", project_map)
    loaded_map = run_store.load_json("project_map.json", ProjectMap)

    print_round_trip(saved_path, loaded_map == project_map)


if __name__ == "__main__":
    manual_test()
