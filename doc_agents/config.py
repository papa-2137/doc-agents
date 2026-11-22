"""Konfiguracja aplikacji: opis config.yaml jako klasy Pydantic i funkcja load_config().

Co robi: wczytuje config.yaml, zamienia go na obiekty Pythona (podpowiedzi w edytorze,
dostęp przez atrybuty, np. config.llm.profiles["small"].model), sprawdza, czy każdy agent
wskazuje istniejący profil modelu, i zamienia ścieżki z sekcji `paths` na bezwzględne.

Czego NIE robi: nie czyta kluczy ani adresów endpointów - config trzyma tylko NAZWY
zmiennych środowiskowych (np. LLM_API_KEY). Wartości odczytuje dopiero doc_agents/llm.py.

Uruchomienie testowe z katalogu repo (wypisuje wczytany config jako JSON):
    python -m doc_agents.config
"""

import os

import yaml
from pydantic import BaseModel


# --- Modele configu ---


class LLMProfile(BaseModel):
    """Profil modelu: dostawca, nazwa modelu, nazwy zmiennych środowiskowych i parametry wywołania."""

    provider: str
    model: str
    api_key_env: str
    base_url_env: str
    structured_output_method: str = "function_calling"  # json_schema | function_calling | json_mode (ustala probe_llm)
    params: dict = {}  # do modelu przekazujemy tylko to, co tu podano


class LLMConfig(BaseModel):
    """Sekcja `llm`: nazwane profile modeli i przypisanie agent -> profil."""

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


# --- Sprawdzenia i przetwarzanie ---


def check_agent_profiles(config: AppConfig) -> None:
    """Sprawdza, czy każdy agent z sekcji llm.agents wskazuje profil istniejący w llm.profiles.
    Przy błędzie rzuca ValueError z nazwą agenta, błędnym profilem i listą dostępnych profili.

    Po co: literówka w nazwie profilu wyszłaby inaczej dopiero przy tworzeniu modelu dla agenta,
    czyli w środku runu (po zużyciu tokenów przez wcześniejsze etapy); tak wychodzi od razu przy starcie.
    """
    for agent, profile in config.llm.agents.items():
        if profile not in config.llm.profiles:
            komunikat_bledu = (
                f"Agent '{agent}' wskazuje nieistniejący profil '{profile}'. "
                f"Dostępne profile: {list(config.llm.profiles)}"
            )
            raise ValueError(komunikat_bledu)


def resolve_paths(paths: PathsConfig, config_dir: str) -> None:
    """Zamienia ścieżki z sekcji paths na bezwzględne: względne liczy od katalogu configu, bezwzględne zostawia.

    Po co: reszta programu dostaje jednoznaczne ścieżki i działa tak samo bez względu na to,
    z którego katalogu uruchomiono program ani gdzie leży config.
    """
    paths.prompts = os.path.abspath(os.path.join(config_dir, paths.prompts))
    paths.knowledge_base = os.path.abspath(os.path.join(config_dir, paths.knowledge_base))
    paths.runs = os.path.abspath(os.path.join(config_dir, paths.runs))


# --- Wczytywanie ---


def load_config(path: str) -> AppConfig:
    """Wczytuje config.yaml, zamienia go na obiekty AppConfig, sprawdza przypisania agentów i rozwiązuje ścieżki.

    Po co: jedyne wejście do konfiguracji dla całego narzędzia - każdy moduł dostaje już sprawdzony,
    typowany config (podpowiedzi w edytorze, dostęp przez atrybuty) zamiast surowego słownika z YAML-a.
    """
    config_path = os.path.abspath(path)
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    config = AppConfig(**raw)
    check_agent_profiles(config)
    resolve_paths(config.paths, os.path.dirname(config_path))
    return config


if __name__ == "__main__":
    config = load_config("config.yaml")
    print(config.model_dump_json(indent=2))
