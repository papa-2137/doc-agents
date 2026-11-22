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

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from doc_agents.config import AppConfig, LLMProfile


# --- Zmienne środowiskowe ---


def read_env(name: str) -> str:
    """Zwraca wartość zmiennej środowiskowej albo rzuca błąd z jej nazwą."""
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
    """Model mówiący protokołem OpenAI Chat Completions pod adresem ze zmiennej base_url_env."""
    model = ChatOpenAI(
        model=profile.model,
        api_key=read_env(profile.api_key_env),
        base_url=read_env(profile.base_url_env),
        **profile.params,  # tylko parametry podane w profilu
    )
    return model


def create_chat_model(profile: LLMProfile) -> BaseChatModel:
    """Tworzy model dla podanego profilu."""
    # Dostawcy: nazwa z configu -> funkcja tworząca model. Nowy dostawca = nowa funkcja powyżej + wpis tutaj.
    providers = {
        "openai_compatible": create_openai_compatible,
    }
    if profile.provider not in providers:
        raise ValueError(f"Nieznany provider '{profile.provider}'. Obsługiwane: {list(providers)}")
    model = providers[profile.provider](profile)
    return model


def get_model_for_agent(config: AppConfig, agent: str) -> BaseChatModel:
    """Tworzy model z profilu przypisanego agentowi w configu."""
    if agent not in config.llm.agents:
        raise ValueError(f"Agent '{agent}' nie ma przypisanego profilu. Agenci w configu: {list(config.llm.agents)}")
    profile = config.llm.profiles[config.llm.agents[agent]]
    model = create_chat_model(profile)
    return model


if __name__ == "__main__":
    import time

    from doc_agents.config import load_config

    config = load_config("config.yaml")
    model = get_model_for_agent(config, "planner")
    print(f"Model: {model.model_name}")

    start = time.time()
    response = model.invoke("Powiedz: test")
    print(f"Odpowiedź: {response.content}")
    print(f"Czas: {time.time() - start:.1f} s")
    print(f"Tokeny: {response.usage_metadata}")
