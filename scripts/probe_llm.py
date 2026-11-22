"""Diagnostyka profilu modelu: połączenie, system + user, structured output, tool calling, tokeny.

Uruchomienie z katalogu repo:  python -m scripts.probe_llm --profile small
"""

import argparse
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from doc_agents.config import load_config
from doc_agents.llm import create_chat_model


class Capital(BaseModel):
    """Stolica kraju."""

    country: str
    capital: str
    population_millions: float


class CountLegs(BaseModel):
    """Zwraca liczbę nóg podanego zwierzęcia."""

    animal: str


def tokens(response) -> str:
    """Zużycie tokenów z odpowiedzi modelu w formie 'X in / Y out'."""
    usage = response.usage_metadata or {}
    return f"{usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} out"


def check(name: str, func, *args) -> bool:
    """Uruchamia jeden test, mierzy czas i wypisuje OK/FAIL. Zwraca True, gdy test przeszedł."""
    start = time.time()
    try:
        details = func(*args)
        print(f"  OK    {name} ({time.time() - start:.1f} s) - {details}")
        return True
    except Exception as e:
        message = str(e).strip().splitlines()[0][:300] if str(e).strip() else ""
        print(f"  FAIL  {name} ({time.time() - start:.1f} s) - {type(e).__name__}: {message}")
        return False


def test_simple(model) -> str:
    response = model.invoke("Odpowiedz jednym słowem: test")
    return f"odpowiedź: {response.content!r}, tokeny: {tokens(response)}"


def test_system_user(model) -> str:
    response = model.invoke([
        SystemMessage("Odpowiadasz wyłącznie WIELKIMI LITERAMI."),
        HumanMessage("Napisz słowo: kot"),
    ])
    text = str(response.content).strip()
    if not text.isupper():
        raise ValueError(f"model zignorował instrukcję systemową, odpowiedź: {text!r}")
    return f"odpowiedź: {text!r}, tokeny: {tokens(response)}"


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
    return f"{capital.capital}, {capital.population_millions} mln, tokeny: {tokens(result['raw'])}"


def test_tools(model) -> str:
    response = model.bind_tools([CountLegs]).invoke("Ile nóg ma stonoga? Użyj narzędzia.")
    if not response.tool_calls:
        raise ValueError(f"model nie wywołał narzędzia, odpowiedź: {str(response.content)[:100]!r}")
    call = response.tool_calls[0]
    return f"{call['name']}({call['args']}), tokeny: {tokens(response)}"


def main():
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    parser = argparse.ArgumentParser(description="Diagnostyka profilu modelu z config.yaml.")
    parser.add_argument("--profile", required=True, help="nazwa profilu z sekcji llm.profiles")
    parser.add_argument("--config", default=default_config, help="ścieżka do config.yaml (domyślnie: config.yaml w katalogu repo)")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.profile not in config.llm.profiles:
        raise SystemExit(f"Nie ma profilu '{args.profile}'. Dostępne profile: {list(config.llm.profiles)}")
    profile = config.llm.profiles[args.profile]

    print(f"Profil: {args.profile}")
    print(f"  model:    {profile.model} ({profile.provider})")
    print(f"  endpoint: zmienna {profile.base_url_env}, klucz: zmienna {profile.api_key_env}")
    print(f"  params:   {profile.params}")
    print(f"  structured_output_method w configu: {profile.structured_output_method}")

    model = create_chat_model(profile)

    print("\n1. Proste wywołanie")
    simple_ok = check("invoke", test_simple, model)

    print("\n2. Wiadomości system + user")
    check("system + user", test_system_user, model)

    print("\n3. Structured output")
    structured_ok = {}
    for method in ["function_calling", "json_schema", "json_mode"]:
        structured_ok[method] = check(method, test_structured, model, method)

    print("\n4. Tool calling")
    check("bind_tools", test_tools, model)

    print("\nDiagnoza")
    if not simple_ok:
        print("  Brak podstawowego połączenia - sprawdź zmienne środowiskowe, nazwę modelu i params (patrz błąd w punkcie 1).")
        return

    working = [method for method, ok in structured_ok.items() if ok]
    if not working:
        print("  Żadna metoda structured output nie działa - agenci nie będą mogli zwracać obiektów.")
        return

    recommended = working[0]  # kolejność preferencji: function_calling, json_schema, json_mode
    print(f"  Działające metody structured output: {', '.join(working)}")
    print(f"  Rekomendacja: structured_output_method: {recommended}")
    if profile.structured_output_method == recommended:
        print("  Config już ma tę wartość.")
    elif profile.structured_output_method in working:
        print(f"  Obecna wartość ({profile.structured_output_method}) też działa - zmiana nie jest konieczna.")
    else:
        print(f"  Obecna wartość ({profile.structured_output_method}) NIE działa - zmień ją w config.yaml.")


if __name__ == "__main__":
    main()
