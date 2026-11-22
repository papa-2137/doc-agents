"""Fabryka modeli: profil z configu → model czatu LangChain.

Jedyne miejsce w projekcie, które importuje langchain_openai i wie, jak tworzyć modele.
"""

import os

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from doc_agents.config import AppConfig, LLMProfile


def read_env(name: str) -> str:
    """Zwraca wartość zmiennej środowiskowej albo rzuca błąd z jej nazwą."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Brak zmiennej środowiskowej '{name}'. "
            f"Ustaw ją jako zmienną użytkownika i otwórz nowe okno terminala."
        )
    return value


def create_openai_compatible(profile: LLMProfile) -> BaseChatModel:
    """Model mówiący protokołem OpenAI Chat Completions pod adresem z LLM_BASE_URL."""
    return ChatOpenAI(
        model=profile.model,
        api_key=read_env(profile.api_key_env),
        base_url=read_env(profile.base_url_env),
        **profile.params,  # tylko parametry podane w profilu
    )


def create_chat_model(profile: LLMProfile) -> BaseChatModel:
    """Tworzy model dla podanego profilu."""
    # Dostawcy: nazwa z configu → funkcja tworząca model. Nowy dostawca = nowa funkcja powyżej + wpis tutaj.
    providers = {
        "openai_compatible": create_openai_compatible,
    }
    if profile.provider not in providers:
        raise ValueError(f"Nieznany provider '{profile.provider}'. Obsługiwane: {list(providers)}")
    return providers[profile.provider](profile)


def get_model_for_agent(config: AppConfig, agent: str) -> BaseChatModel:
    """Tworzy model z profilu przypisanego agentowi w configu."""
    if agent not in config.llm.agents:
        raise ValueError(f"Agent '{agent}' nie ma przypisanego profilu. Agenci w configu: {list(config.llm.agents)}")
    profile = config.llm.profiles[config.llm.agents[agent]]
    return create_chat_model(profile)


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
