"""Baza wiedzy: spis plików wiedzy (index.md) i bezpieczny odczyt ich treści.

Co robi:
    - load_index() wczytuje knowledge_base/knowledge/index.md i zwraca listę wpisów KBEntry
      (nazwa pliku, „Kiedy użyć”, tagi) - na tej podstawie planner wybiera pliki dla projektu,
    - read_kb_file() zwraca treść wybranego pliku wiedzy - tylko pliku leżącego w katalogu
      knowledge_base/knowledge/ (nazwa od modelu nie może wskazać pliku spoza bazy wiedzy).

Format index.md (zwykły tekst, łatwy do dopisywania): blok na plik, bloki oddzielone pustą linią:
    nazwa_pliku.md
    Kiedy użyć: ...
    Tagi: tag1, tag2
Blok bez linii „Kiedy użyć:” (np. nagłówek i instrukcja na początku pliku) jest pomijany.

Szablony dokumentu (knowledge_base/templates/) nie są częścią spisu. Planner dostaje z nich:
    - load_fixed_sections() - stałe rozdziały części opisowej (tytuł i instrukcja) z descriptive_template.yaml,
    - load_formal_field_titles() - tytuły pól części formalnej z formal_template.yaml (żeby nie
      proponował rozdziałów, które je powtarzają).
Redaktor dostaje pełny opis pól części formalnej przez load_formal_fields().

Test ręczny z katalogu repo (wypisuje wpisy spisu, stałe rozdziały, pola części formalnej i treść jednego pliku,
sprawdza blokadę ścieżki spoza bazy):
    python -m doc_agents.knowledge
    python -m doc_agents.knowledge <nazwa pliku wiedzy>
"""

import os
import sys

import yaml
from pydantic import BaseModel

from doc_agents.config import load_config
from doc_agents.schemas import DescriptiveSection


# --- Spis bazy wiedzy ---


class KBEntry(BaseModel):
    """Jeden wpis spisu bazy wiedzy."""

    filename: str  # nazwa pliku w knowledge_base/knowledge/
    when_to_use: str  # opis dla plannera: kiedy plik się przyda
    tags: list[str]


def parse_entry(block_lines: list[str]) -> KBEntry | None:
    """Zamienia jeden blok spisu (linie bez pustych) na KBEntry; zwraca None, gdy blok nie ma linii „Kiedy użyć:”.

    Po co: odróżnia wpisy od nagłówka i instrukcji na początku index.md bez osobnych znaczników.
    Pierwsza linia bloku to nazwa pliku; linia „Tagi:” jest opcjonalna, tagi oddzielone przecinkami.
    """
    when_to_use = ""
    tags = []
    for line in block_lines[1:]:
        if line.startswith("Kiedy użyć:"):
            when_to_use = line[len("Kiedy użyć:"):].strip()
        elif line.startswith("Tagi:"):
            for tag in line[len("Tagi:"):].split(","):
                if tag.strip() != "":
                    tags.append(tag.strip())

    wpis = None
    if when_to_use != "":
        wpis = KBEntry(filename=block_lines[0].strip(), when_to_use=when_to_use, tags=tags)
    return wpis


def parse_index(text: str) -> list[KBEntry]:
    """Dzieli tekst index.md na bloki oddzielone pustymi liniami i zwraca wpisy z bloków, które je opisują.

    Po co: spis jest zwykłym tekstem, żeby zespół mógł łatwo dopisywać pliki - tu zamieniamy go
    na dane, z których korzysta planner.
    """
    wpisy = []
    block_lines = []
    for line in text.splitlines() + [""]:
        if line.strip() == "":
            if block_lines:
                wpis = parse_entry(block_lines)
                if wpis is not None:
                    wpisy.append(wpis)
            block_lines = []
        else:
            block_lines.append(line.strip())
    return wpisy


def load_index(knowledge_base_dir: str) -> list[KBEntry]:
    """Wczytuje knowledge/index.md z katalogu bazy wiedzy (UTF-8) i zwraca listę wpisów.

    Po co: jedno wejście do spisu bazy wiedzy dla plannera. Argument: config.paths.knowledge_base.
    """
    index_path = os.path.join(knowledge_base_dir, "knowledge", "index.md")
    with open(index_path, encoding="utf-8") as f:
        tekst_spisu = f.read()
    wpisy = parse_index(tekst_spisu)
    return wpisy


# --- Treść plików wiedzy ---


def read_kb_file(knowledge_base_dir: str, filename: str) -> str:
    """Zwraca treść pliku z katalogu knowledge_base/knowledge/ (UTF-8). Nazwa wskazująca poza ten katalog
    (np. "../../config.yaml" albo ścieżka bezwzględna) kończy się ValueError.

    Po co: nazwy plików do przeczytania wybiera model (planner) - bez tej kontroli błędna albo
    podsunięta nazwa mogłaby odczytać dowolny plik z dysku i wysłać go do modelu.
    """
    knowledge_dir = os.path.abspath(os.path.join(knowledge_base_dir, "knowledge"))
    file_path = os.path.abspath(os.path.join(knowledge_dir, filename))
    if not os.path.normcase(file_path).startswith(os.path.normcase(knowledge_dir) + os.sep):
        komunikat_bledu = f"Plik spoza bazy wiedzy: {filename}"
        raise ValueError(komunikat_bledu)

    with open(file_path, encoding="utf-8") as f:
        tresc_pliku = f.read()
    return tresc_pliku


# --- Szablony dokumentu ---


def load_fixed_sections(knowledge_base_dir: str) -> list[DescriptiveSection]:
    """Wczytuje templates/descriptive_template.yaml z katalogu bazy wiedzy i zwraca stałe rozdziały
    (tytuł i instrukcja) w kolejności z pliku.

    Po co: stałe rozdziały konfiguruje zespół w YAML, a planner musi je dostać, żeby wpisać je do planu.
    Pole required z YAML nie jest tu zwracane - planner dostaje wszystkie rozdziały; wymagane sprawdzi
    recenzent. Argument: config.paths.knowledge_base.
    """
    template_path = os.path.join(knowledge_base_dir, "templates", "descriptive_template.yaml")
    with open(template_path, encoding="utf-8") as f:
        dane_szablonu = yaml.safe_load(f)

    stale_rozdzialy = []
    for section_data in dane_szablonu["sections"]:
        stale_rozdzialy.append(
            DescriptiveSection(title=section_data["title"], instruction=section_data["instruction"].strip())
        )
    return stale_rozdzialy


def load_formal_fields(knowledge_base_dir: str) -> list[dict]:
    """Wczytuje templates/formal_template.yaml z katalogu bazy wiedzy i zwraca listę pól części formalnej
    (słowniki z kluczami z YAML: name, title, type, required, source oraz scanner albo instruction)
    w kolejności z pliku.

    Po co: jedno miejsce odczytu szablonu części formalnej - redaktor wypełnia i składa pola według niego,
    planner bierze z niego tytuły. Pola zostają słownikami: zespół może dopisywać klucze bez zmian w kodzie.
    Argument: config.paths.knowledge_base.
    """
    template_path = os.path.join(knowledge_base_dir, "templates", "formal_template.yaml")
    with open(template_path, encoding="utf-8") as f:
        dane_szablonu = yaml.safe_load(f)

    pola = dane_szablonu["fields"]
    return pola


def load_formal_field_titles(knowledge_base_dir: str) -> list[str]:
    """Zwraca tytuły pól części formalnej z templates/formal_template.yaml w kolejności z pliku.

    Po co: planner musi wiedzieć, co będzie w części formalnej, żeby nie proponować rozdziałów opisowych,
    które powtarzają te same informacje. Same tytuły wystarczą - instrukcje pól są dla redaktora.
    Argument: config.paths.knowledge_base.
    """
    tytuly_pol = []
    for field_data in load_formal_fields(knowledge_base_dir):
        tytuly_pol.append(field_data["title"])
    return tytuly_pol


# --- Wyświetlanie ---


def print_entries(entries: list[KBEntry]) -> None:
    """Wypisuje wpisy spisu bazy wiedzy: nazwa pliku, „Kiedy użyć”, tagi.

    Po co: przy teście ręcznym widać, czy index.md został poprawnie odczytany.
    """
    print(f"=== Spis bazy wiedzy: {len(entries)} wpisy ===\n")
    for entry in entries:
        print(entry.filename)
        print(f"  Kiedy użyć: {entry.when_to_use}")
        print(f"  Tagi: {', '.join(entry.tags)}")


def print_fixed_sections(sections: list[DescriptiveSection]) -> None:
    """Wypisuje stałe rozdziały części opisowej: tytuł i instrukcję.

    Po co: przy teście ręcznym widać, czy descriptive_template.yaml został poprawnie odczytany.
    """
    print(f"\n=== Stałe rozdziały części opisowej: {len(sections)} ===\n")
    for section in sections:
        print(section.title)
        print(f"  {section.instruction}")


def print_formal_field_titles(titles: list[str]) -> None:
    """Wypisuje tytuły pól części formalnej.

    Po co: przy teście ręcznym widać, czy formal_template.yaml został poprawnie odczytany.
    """
    print(f"\n=== Pola części formalnej: {len(titles)} ===\n")
    for title in titles:
        print(title)


def print_file(filename: str, content: str) -> None:
    """Wypisuje nazwę i treść pliku wiedzy.

    Po co: przy teście ręcznym widać, czy plik wiedzy się czyta i co trafi do agentów.
    """
    print(f"\n=== {filename} ===\n")
    print(content)


def print_blocked_path(error_message: str) -> None:
    """Wypisuje komunikat blokady pliku spoza bazy wiedzy.

    Po co: test ręczny pokazuje, że ochrona przed odczytem dowolnego pliku działa.
    """
    print("=== test pliku spoza bazy wiedzy ===\n")
    print(f"Błąd (oczekiwany): {error_message}")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: wypisuje spis bazy wiedzy, stałe rozdziały części opisowej, tytuły pól części formalnej,
    treść pliku z argumentu (domyślnie pierwszego ze spisu)
    i próbuje odczytać plik spoza bazy (../../config.yaml), co ma się skończyć błędem.

    Po co: sprawdzenie parsera index.md i bezpiecznego odczytu na prawdziwej bazie wiedzy.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    knowledge_base_dir = config.paths.knowledge_base

    entries = load_index(knowledge_base_dir)
    print_entries(entries)
    print_fixed_sections(load_fixed_sections(knowledge_base_dir))
    print_formal_field_titles(load_formal_field_titles(knowledge_base_dir))

    filename = entries[0].filename
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    print_file(filename, read_kb_file(knowledge_base_dir, filename))

    try:
        read_kb_file(knowledge_base_dir, "../../config.yaml")
    except ValueError as blad:
        print_blocked_path(str(blad))


if __name__ == "__main__":
    manual_test()
