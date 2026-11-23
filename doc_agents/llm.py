"""Fabryka modeli: profil z config.yaml -> gotowy model czatu LangChain.

Co robi: na podstawie profilu (provider, nazwa modelu, nazwy zmiennych środowiskowych, params)
tworzy obiekt modelu, którego używają agenci. Klucz API i adres endpointu odczytuje ze
zmiennych środowiskowych, których NAZWY są w profilu (np. LLM_API_KEY, LLM_BASE_URL).

Po co osobny moduł: to jedyne miejsce w projekcie, które importuje langchain_openai i wie,
jak tworzyć modele. Zmiana modelu, endpointu albo parametrów to zmiana w config.yaml,
nie w kodzie. Nowy dostawca (inny protokół niż OpenAI) = nowa funkcja create_... w tym pliku
i jeden wpis w słowniku `providers` w create_chat_model().

Do modelu przekazujemy tylko parametry podane w profilu (`params`) - część modeli odrzuca
np. temperature. Co dany model obsługuje, sprawdza scripts/probe_llm.py.

invoke_structured() to wspólny sposób wywołania modelu ze schematem odpowiedzi (Pydantic) dla
wszystkich agentów: gdy model nie zwróci odpowiedzi zgodnej ze schematem, rzuca błąd z przyczyną
(np. finish_reason=length - odpowiedź ucięta na limicie max_tokens z profilu).

Uruchomienie testowe z katalogu repo (jedno krótkie wywołanie modelu agenta `planner`):
    python -m doc_agents.llm
"""

import os
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from doc_agents.config import AppConfig, LLMProfile, load_config


# --- Zmienne środowiskowe ---


def read_env(name: str) -> str:
    """Zwraca wartość zmiennej środowiskowej o podanej nazwie; gdy jej brak lub jest pusta, rzuca RuntimeError z nazwą zmiennej.

    Po co: klucze i adresy endpointów nie mogą być zapisane w repo ani w configu, więc czytamy je
    ze zmiennych środowiskowych; czytelny błąd z nazwą zmiennej mówi od razu, co trzeba ustawić.
    """
    value = os.environ.get(name)
    if not value:
        komunikat_bledu = (
            f"Brak zmiennej środowiskowej '{name}'. "
            f"Ustaw ją jako zmienną użytkownika i otwórz nowe okno terminala."
        )
        raise RuntimeError(komunikat_bledu)
    return value


# --- Tworzenie modeli ---


def create_openai_compatible(profile: LLMProfile) -> BaseChatModel:
    """Tworzy model ChatOpenAI dla profilu: nazwa modelu z profilu, klucz i adres endpointu ze zmiennych
    środowiskowych wskazanych w profilu, plus tylko te parametry, które podano w params.

    Po co: zarówno publiczne API, jak i firmowe bramki mówią protokołem OpenAI Chat Completions,
    więc jedna funkcja obsługuje wszystkie te endpointy - zmienia się tylko config, nie kod.
    """
    model = ChatOpenAI(
        model=profile.model,
        api_key=read_env(profile.api_key_env),
        base_url=read_env(profile.base_url_env),
        **profile.params,  # tylko parametry podane w profilu
    )
    return model


def create_chat_model(profile: LLMProfile) -> BaseChatModel:
    """Tworzy model dla profilu, wybierając funkcję tworzącą według pola provider (słownik providers).
    Nieznany provider -> ValueError z listą obsługiwanych.

    Po co: jedno miejsce decydujące o tym, jak powstaje model; dodanie nowego dostawcy (innego protokołu)
    to nowa funkcja create_... i jeden wpis w słowniku, bez zmian w reszcie projektu.
    """
    # Dostawcy: nazwa z configu -> funkcja tworząca model. Nowy dostawca = nowa funkcja powyżej + wpis tutaj.
    providers = {
        "openai_compatible": create_openai_compatible,
    }
    if profile.provider not in providers:
        raise ValueError(f"Nieznany provider '{profile.provider}'. Obsługiwane: {list(providers)}")
    model = providers[profile.provider](profile)
    return model


def get_model_for_agent(config: AppConfig, agent: str) -> BaseChatModel:
    """Tworzy model z profilu przypisanego w configu wskazanemu agentowi (np. planner -> small).

    Po co: agenci nie znają nazw modeli ani profili - proszą o model po swojej nazwie, a przełączenie
    agenta na inny model to zmiana jednej linii w sekcji llm.agents w config.yaml.
    """
    if agent not in config.llm.agents:
        raise ValueError(f"Agent '{agent}' nie ma przypisanego profilu. Agenci w configu: {list(config.llm.agents)}")
    profile = config.llm.profiles[config.llm.agents[agent]]
    model = create_chat_model(profile)
    return model


def get_structured_output_method(config: AppConfig, agent: str) -> str:
    """Zwraca metodę structured output (np. function_calling, json_schema) z profilu przypisanego agentowi.

    Po co: agent prosi model o odpowiedź zgodną ze schematem (with_structured_output), a obsługiwana
    metoda zależy od modelu - ustala ją probe_llm i zapisuje się ją w profilu, nie w kodzie agenta.
    """
    profile = config.llm.profiles[config.llm.agents[agent]]
    metoda = profile.structured_output_method
    return metoda


# --- Wywołanie ze schematem odpowiedzi ---


def invoke_structured(model: BaseChatModel, schema: type[BaseModel], method: str, messages: list[BaseMessage]) -> BaseModel:
    """Wywołuje model z wiadomościami i schematem odpowiedzi (with_structured_output) i zwraca odpowiedź
    jako obiekt schematu. Gdy model nie zwróci odpowiedzi zgodnej ze schematem, rzuca RuntimeError
    z nazwą schematu, powodem zakończenia odpowiedzi (finish_reason), zużyciem tokenów i błędem parsowania.

    Po co: bez tego LangChain zwraca po cichu None (np. gdy odpowiedź została ucięta na limicie
    max_tokens), a błąd wychodzi dopiero dalej, bez przyczyny. include_raw=True daje dostęp do surowej
    odpowiedzi modelu, z której odczytujemy przyczynę. Jedno miejsce dla wszystkich agentów.
    Argumenty: method - metoda structured output z profilu (get_structured_output_method).
    """
    model_ze_schematem = model.with_structured_output(schema, method=method, include_raw=True)
    wynik = model_ze_schematem.invoke(messages)

    if wynik["parsed"] is None:
        surowa_odpowiedz = wynik["raw"]
        komunikat_bledu = (
            f"Model nie zwrócił odpowiedzi zgodnej ze schematem {schema.__name__}. "
            f"finish_reason={surowa_odpowiedz.response_metadata.get('finish_reason')}, "
            f"tokeny={surowa_odpowiedz.usage_metadata}, "
            f"błąd parsowania={wynik['parsing_error']}. "
            f"Przy finish_reason=length zwiększ max_tokens w profilu modelu w config.yaml."
        )
        raise RuntimeError(komunikat_bledu)

    odpowiedz = wynik["parsed"]
    return odpowiedz


# --- Test ręczny ---


def ask_test_question(model: BaseChatModel) -> tuple[str, float, dict]:
    """Wysyła do modelu krótkie polecenie „Powiedz: test” i zwraca (odpowiedź, czas w sekundach, zużycie tokenów).

    Po co: najprostsze sprawdzenie, że klucz, adres i nazwa modelu z configu działają.
    """
    start = time.time()
    response = model.invoke("Powiedz: test")
    czas_s = time.time() - start
    wynik_wywolania = (response.content, czas_s, response.usage_metadata)
    return wynik_wywolania


def print_test_answer(model_name: str, answer: str, seconds: float, usage: dict) -> None:
    """Wypisuje nazwę modelu, odpowiedź, czas i zużycie tokenów.

    Po co: czytelny wynik testu ręcznego połączenia z modelem.
    """
    print(f"Model: {model_name}")
    print(f"Odpowiedź: {answer}")
    print(f"Czas: {seconds:.1f} s")
    print(f"Tokeny: {usage}")


def manual_test() -> None:
    """Test ręczny: tworzy model agenta planner z configu, wysyła jedno krótkie polecenie i wypisuje wynik.

    Po co: sprawdzenie dostępu do modelu (zmienne środowiskowe, profil, endpoint) bez uruchamiania całego narzędzia.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    model = get_model_for_agent(config, "planner")
    answer, seconds, usage = ask_test_question(model)
    print_test_answer(model.model_name, answer, seconds, usage)


if __name__ == "__main__":
    manual_test()
