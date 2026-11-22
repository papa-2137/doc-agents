"""Diagnostyka profilu modelu z config.yaml.

Po co: zanim agenci zaczną korzystać z modelu, sprawdzamy, co dany model i endpoint naprawdę
obsługują. Różne modele (i różne bramki API) zachowują się inaczej - to, że jeden profil działa,
nie znaczy, że zadziała drugi. Skrypt uruchamiamy dla każdego profilu osobno, zawsze po zmianie
modelu, endpointu albo parametrów w profilu.

Uruchomienie z katalogu repo:
    python -m scripts.probe_llm --profile small

Co jest testowane (każdy test osobno; błąd jednego nie przerywa pozostałych):
    1. Proste wywołanie - czy jest połączenie, czy działają klucz, adres, nazwa modelu i params.
    2. Wiadomości system + user - czy model trzyma się instrukcji systemowej (tak działają agenci).
    3. Structured output - czy model potrafi zwrócić dane w ustalonym schemacie (obiekt Pydantic).
       Testowane są ZAWSZE wszystkie trzy metody, niezależnie od tego, co jest w configu:
         - function_calling - schemat podawany jako wymuszone wywołanie narzędzia,
         - json_schema      - schemat podawany w response_format,
         - json_mode        - model ma zwrócić dowolny poprawny JSON (bez wymuszania schematu).
       FAIL przy którejś metodzie nie jest błędem skryptu - to informacja, że ten model/endpoint
       jej nie obsługuje.
    4. Tool calling - czy model potrafi poprosić o wywołanie narzędzia (narzędzie nie jest uruchamiane).
    5. Zużycie tokenów - wypisywane przy każdym wywołaniu.

Wynik: na końcu skrypt podaje, które metody structured output działają, i rekomenduje wartość
structured_output_method, którą należy wpisać w config.yaml dla tego profilu (pierwsza działająca
w kolejności: function_calling, json_schema, json_mode). Sprawdza też, czy wartość obecnie
ustawiona w profilu jest wśród działających.
"""

import argparse
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from doc_agents.config import load_config
from doc_agents.llm import create_chat_model


# --- Schematy używane w testach ---


class Capital(BaseModel):
    """Stolica kraju."""

    country: str
    capital: str
    population_millions: float


class CountLegs(BaseModel):
    """Zwraca liczbę nóg podanego zwierzęcia."""

    animal: str


# --- Funkcje pomocnicze ---


def tokens(response) -> str:
    """Zużycie tokenów z odpowiedzi modelu w formie 'X in / Y out'."""
    usage = response.usage_metadata or {}
    komunikat_zuzycie_tokenow = f"{usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} out"
    return komunikat_zuzycie_tokenow


def check(func, *args) -> tuple[bool, float, str]:
    """Uruchamia jeden test i mierzy czas. Nic nie wypisuje.

    Zwraca (czy_ok, czas_s, opis): opis to wynik testu albo - przy błędzie - nazwa i treść wyjątku.
    """
    start = time.time()
    try:
        opis_wyniku = func(*args)
        czas_s = time.time() - start
        return True, czas_s, opis_wyniku
    except Exception as e:
        czas_s = time.time() - start
        tresc_bledu = str(e).strip().splitlines()[0][:300] if str(e).strip() else ""
        opis_bledu = f"{type(e).__name__}: {tresc_bledu}"
        return False, czas_s, opis_bledu


# --- Testy (każdy zwraca opis wyniku albo rzuca wyjątek) ---


def test_simple(model) -> str:
    response = model.invoke("Odpowiedz jednym słowem: test")
    opis_odpowiedzi = f"odpowiedź: {response.content!r}, tokeny: {tokens(response)}"
    return opis_odpowiedzi


def test_system_user(model) -> str:
    response = model.invoke([
        SystemMessage("Odpowiadasz wyłącznie WIELKIMI LITERAMI."),
        HumanMessage("Napisz słowo: kot"),
    ])
    text = str(response.content).strip()
    if not text.isupper():
        raise ValueError(f"model zignorował instrukcję systemową, odpowiedź: {text!r}")
    opis_odpowiedzi = f"odpowiedź: {text!r}, tokeny: {tokens(response)}"
    return opis_odpowiedzi


def test_structured(model, method: str) -> str:
    structured = model.with_structured_output(Capital, method=method, include_raw=True)
    result = structured.invoke(
        "Podaj stolicę Polski i przybliżoną liczbę mieszkańców tego miasta (samej stolicy) w milionach. "
        "Odpowiedz w formacie JSON z polami: country, capital, population_millions."
    )
    if result["parsing_error"]:
        raise result["parsing_error"]
    capital = result["parsed"]
    if capital is None:
        raise ValueError("model nie zwrócił danych w oczekiwanym formacie")
    opis_danych_ze_schematu = f"{capital.capital}, {capital.population_millions} mln, tokeny: {tokens(result['raw'])}"
    return opis_danych_ze_schematu


def test_tools(model) -> str:
    response = model.bind_tools([CountLegs]).invoke("Ile nóg ma stonoga? Użyj narzędzia.")
    if not response.tool_calls:
        raise ValueError(f"model nie wywołał narzędzia, odpowiedź: {str(response.content)[:100]!r}")
    call = response.tool_calls[0]
    opis_wywolania_narzedzia = f"{call['name']}({call['args']}), tokeny: {tokens(response)}"
    return opis_wywolania_narzedzia


# --- Logika: uruchomienie testów i diagnoza (bez wypisywania) ---


def run_tests(model) -> dict:
    """Uruchamia wszystkie testy. Zwraca słownik: nazwa testu -> (czy_ok, czas_s, opis)."""
    wyniki = {
        "invoke": check(test_simple, model),
        "system + user": check(test_system_user, model),
        "function_calling": check(test_structured, model, "function_calling"),
        "json_schema": check(test_structured, model, "json_schema"),
        "json_mode": check(test_structured, model, "json_mode"),
        "bind_tools": check(test_tools, model),
    }
    return wyniki


def diagnose(wyniki: dict, obecna_metoda: str) -> dict:
    """Na podstawie wyników ustala działające metody structured output i rekomendację dla configu."""
    # Kolejność preferencji: function_calling, json_schema, json_mode.
    dzialajace_metody = [m for m in ["function_calling", "json_schema", "json_mode"] if wyniki[m][0]]
    rekomendowana = dzialajace_metody[0] if dzialajace_metody else None
    diagnoza = {
        "polaczenie_ok": wyniki["invoke"][0],
        "dzialajace_metody": dzialajace_metody,
        "rekomendowana": rekomendowana,
        "obecna": obecna_metoda,
        "obecna_dziala": obecna_metoda in dzialajace_metody,
    }
    return diagnoza


# --- Wyświetlanie (tylko print, bez logiki) ---


def print_header(nazwa_profilu: str, profile) -> None:
    print(f"Profil: {nazwa_profilu}")
    print(f"  model:    {profile.model} ({profile.provider})")
    print(f"  endpoint: zmienna {profile.base_url_env}, klucz: zmienna {profile.api_key_env}")
    print(f"  params:   {profile.params}")
    print(f"  structured_output_method w configu: {profile.structured_output_method}")
    print("\nTestuję (kilka-kilkanaście sekund)...")


def print_results(wyniki: dict) -> None:
    sekcje = [
        ("1. Proste wywołanie", ["invoke"]),
        ("2. Wiadomości system + user", ["system + user"]),
        ("3. Structured output (zawsze wszystkie trzy metody)", ["function_calling", "json_schema", "json_mode"]),
        ("4. Tool calling", ["bind_tools"]),
    ]
    for tytul, nazwy_testow in sekcje:
        print(f"\n{tytul}")
        for nazwa in nazwy_testow:
            czy_ok, czas_s, opis = wyniki[nazwa]
            status = "OK  " if czy_ok else "FAIL"
            print(f"  {status}  {nazwa} ({czas_s:.1f} s) - {opis}")


def print_diagnosis(diagnoza: dict) -> None:
    print("\nDiagnoza")
    if not diagnoza["polaczenie_ok"]:
        print("  Brak podstawowego połączenia - sprawdź zmienne środowiskowe, nazwę modelu i params (patrz błąd w punkcie 1).")
        return
    if not diagnoza["dzialajace_metody"]:
        print("  Żadna metoda structured output nie działa - agenci nie będą mogli zwracać obiektów.")
        return

    obecna = diagnoza["obecna"]
    print(f"  Działające metody structured output: {', '.join(diagnoza['dzialajace_metody'])}")
    print(f"  Rekomendacja: structured_output_method: {diagnoza['rekomendowana']}")
    if obecna == diagnoza["rekomendowana"]:
        print("  Config już ma tę wartość.")
    elif diagnoza["obecna_dziala"]:
        print(f"  Obecna wartość ({obecna}) też działa - zmiana nie jest konieczna.")
    else:
        print(f"  Obecna wartość ({obecna}) NIE działa - zmień ją w config.yaml.")


# --- Uruchomienie ---


def parse_args():
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    parser = argparse.ArgumentParser(description="Diagnostyka profilu modelu z config.yaml.")
    parser.add_argument("--profile", required=True, help="nazwa profilu z sekcji llm.profiles")
    parser.add_argument("--config", default=default_config, help="ścieżka do config.yaml (domyślnie: config.yaml w katalogu repo)")
    return parser.parse_args()


def load_profile(config_path: str, nazwa_profilu: str):
    """Wczytuje config i zwraca wskazany profil; przy złej nazwie kończy program z listą dostępnych."""
    config = load_config(config_path)
    if nazwa_profilu not in config.llm.profiles:
        raise SystemExit(f"Nie ma profilu '{nazwa_profilu}'. Dostępne profile: {list(config.llm.profiles)}")
    return config.llm.profiles[nazwa_profilu]


def main():
    args = parse_args()
    profile = load_profile(args.config, args.profile)
    print_header(args.profile, profile)

    model = create_chat_model(profile)
    wyniki = run_tests(model)
    diagnoza = diagnose(wyniki, profile.structured_output_method)

    print_results(wyniki)
    print_diagnosis(diagnoza)


if __name__ == "__main__":
    main()
