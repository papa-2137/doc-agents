"""Konfiguracja aplikacji: modele Pydantic opisujące config.yaml i funkcja load_config()."""

import os

import yaml
from pydantic import BaseModel


class LLMProfile(BaseModel):
    """Profil modelu: dostawca, nazwa modelu, nazwy zmiennych środowiskowych i parametry wywołania."""

    provider: str
    model: str
    api_key_env: str
    base_url_env: str
    structured_output_method: str = "function_calling"  # json_schema | function_calling | json_mode
    params: dict = {}  # do modelu przekazujemy tylko to, co tu podano


class LLMConfig(BaseModel):
    """Sekcja `llm`: nazwane profile modeli i przypisanie agent → profil."""

    profiles: dict[str, LLMProfile]
    agents: dict[str, str]


class PathsConfig(BaseModel):
    """Sekcja `paths`: katalogi projektu."""

    prompts: str
    knowledge_base: str
    runs: str


class AppConfig(BaseModel):
    """Cały config.yaml."""

    llm: LLMConfig
    paths: PathsConfig


def load_config(path: str) -> AppConfig:
    """Wczytuje config.yaml, sprawdza przypisania agentów i zamienia ścieżki na bezwzględne."""
    config_path = os.path.abspath(path)
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    config = AppConfig(**raw)

    # Każdy agent musi wskazywać istniejący profil.
    for agent, profile in config.llm.agents.items():
        if profile not in config.llm.profiles:
            raise ValueError(
                f"Agent '{agent}' wskazuje nieistniejący profil '{profile}'. "
                f"Dostępne profile: {list(config.llm.profiles)}"
            )

    # Ścieżki względne liczymy od katalogu, w którym leży config (bezwzględne zostają bez zmian).
    config_dir = os.path.dirname(config_path)
    config.paths.prompts = os.path.abspath(os.path.join(config_dir, config.paths.prompts))
    config.paths.knowledge_base = os.path.abspath(os.path.join(config_dir, config.paths.knowledge_base))
    config.paths.runs = os.path.abspath(os.path.join(config_dir, config.paths.runs))

    return config


if __name__ == "__main__":
    config = load_config("config.yaml")
    print(config.model_dump_json(indent=2))
