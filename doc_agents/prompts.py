"""Prompty agentów: wczytanie z plików prompts/<agent>/ i wstawienie danych do szablonu.

Co robi: render_prompt() zwraca dla wskazanego agenta (planner, analyst, editor, reviewer)
gotową parę tekstów (system, user):
    - system.md - stałe instrukcje agenta, zwracane bez zmian (nie jest szablonem),
    - user.md   - szablon Jinja2 z miejscami na dane, np. {{ project_map }}; kod wstawia tam
                  dane konkretnego projektu przy każdym wywołaniu modelu.

Po co:
    - prompty poprawia się w plikach Markdown, bez zmian w kodzie - to nimi stroi się jakość dokumentacji,
    - dane (w tym analizowany kod) trafiają zawsze do części user, opakowane w tagi - ochrona przed
      prompt injection z analizowanego projektu; stały system prompt może być cache'owany przez dostawcę,
    - brak zmiennej w danych kończy się błędem z nazwą zmiennej i pliku (StrictUndefined),
      a nie pustym miejscem w poleceniu, za które zapłacilibyśmy słabą odpowiedzią modelu.

Zmienne podane w danych, a nieużyte w szablonie, nie powodują błędu.

Uruchomienie testowe z katalogu repo (renderuje prompt plannera z przykładowymi danymi,
potem pokazuje błąd przy brakującej zmiennej):
    python -m doc_agents.prompts
"""

import os

from jinja2 import Environment, StrictUndefined, UndefinedError

from doc_agents.config import load_config


# --- Prompty ---


def read_prompt_file(prompts_dir: str, agent: str, filename: str) -> str:
    """Zwraca treść pliku prompts_dir/<agent>/<filename> (UTF-8).

    Po co: jedno miejsce odczytu plików promptów; brak pliku kończy się FileNotFoundError
    ze ścieżką, więc od razu widać, którego promptu brakuje.
    """
    sciezka_pliku = os.path.join(prompts_dir, agent, filename)
    with open(sciezka_pliku, encoding="utf-8") as f:
        tresc_pliku = f.read()
    return tresc_pliku


def render_prompt(prompts_dir: str, agent: str, variables: dict) -> tuple[str, str]:
    """Zwraca parę (system, user) dla agenta: system.md bez zmian i user.md z wstawionymi zmiennymi.
    Brak zmiennej użytej w user.md kończy się ValueError z nazwą agenta i zmiennej.

    Po co: każdy agent przed wywołaniem modelu potrzebuje obu tekstów naraz - jedna funkcja
    zamiast osobnego wczytywania i renderowania. Argumenty: prompts_dir - katalog promptów
    (config.paths.prompts), agent - nazwa podkatalogu, variables - dane do wstawienia w szablon.
    """
    system_text = read_prompt_file(prompts_dir, agent, "system.md")
    user_template_text = read_prompt_file(prompts_dir, agent, "user.md")

    srodowisko = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    szablon_user = srodowisko.from_string(user_template_text)
    try:
        user_text = szablon_user.render(variables)
    except UndefinedError as blad:
        komunikat_bledu = f"Prompt {agent}/user.md: brak zmiennej w danych - {blad}"
        raise ValueError(komunikat_bledu) from blad

    prompt = (system_text, user_text)
    return prompt


# --- Wyświetlanie ---


def print_prompt(agent: str, system_text: str, user_text: str) -> None:
    """Wypisuje oba teksty promptu agenta z nagłówkami.

    Po co: przy uruchomieniu testowym widać dokładnie to, co dostanie model.
    """
    print(f"=== {agent} / system ===\n")
    print(system_text)
    print(f"=== {agent} / user ===\n")
    print(user_text)


def print_missing_variable(error_message: str) -> None:
    """Wypisuje komunikat błędu o brakującej zmiennej.

    Po co: uruchomienie testowe pokazuje, że brak zmiennej jest wychwytywany, a nie przemilczany.
    """
    print("=== test brakującej zmiennej ===\n")
    print(f"Błąd (oczekiwany): {error_message}")


# --- Test ręczny ---


def manual_test() -> None:
    """Uruchomienie testowe: renderuje prompt plannera z przykładowymi danymi, potem ponownie bez zmiennej kb_index.

    Po co: ręczne sprawdzenie wczytywania promptów, wstawiania zmiennych i wykrywania braków.
    Dane są przykładowe - prawdziwe przygotuje planner w kroku 27.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))

    przykladowe_dane = {
        "project_name": "przykladowy_robot",
        "project_map": '{"technology": "python", "entrypoints": ["main.py"], "code_units": ["main.py", "src/report.py"]}',
        "kb_index": "rpa_framework.md\nKiedy użyć: projekt oparty na frameworku RPA.\nTagi: rpa, framework",
        "fixed_sections": "- Schemat przepływu (wymagany): narysuj przepływ robota znakami ASCII.",
    }
    system_text, user_text = render_prompt(config.paths.prompts, "planner", przykladowe_dane)
    print_prompt("planner", system_text, user_text)

    dane_bez_indeksu = dict(przykladowe_dane)
    del dane_bez_indeksu["kb_index"]
    try:
        render_prompt(config.paths.prompts, "planner", dane_bez_indeksu)
    except ValueError as blad:
        print_missing_variable(str(blad))


if __name__ == "__main__":
    manual_test()
