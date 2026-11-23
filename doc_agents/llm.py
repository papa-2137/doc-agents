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

Uruchomienie testowe z katalogu repo (jedno krótkie wywołanie modelu agenta `planner`):
    python -m doc_agents.llm
"""

import os
import time

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

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
