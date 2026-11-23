"""Kontekst uruchomienia (RunContext): zależności wspólne dla wszystkich węzłów grafu.

Co zawiera: config, katalog wyników (RunStore), modele językowe dla każdego agenta
i spis bazy wiedzy. Prompty i pliki bazy wiedzy czyta się przez ścieżki z config.paths
(render_prompt z prompts.py, read_kb_file z knowledge.py).

Po co osobno od stanu grafu: stan (state.py) przechowuje DANE przebiegu - to, co węzły
produkują i przekazują dalej. RunContext to NARZĘDZIA - tworzone raz na początku i takie same
przez cały przebieg. LangGraph podaje je każdemu węzłowi przez runtime.context
(parametr runtime: Runtime[RunContext]); w stanie by przeszkadzały - stan jest zapisywany
i porównywany, a modeli i połączeń nie da się sensownie zapisać.

Uwaga: create_run_context() tworzy modele (potrzebne zmienne LLM_API_KEY i LLM_BASE_URL -
bez wywoływania modelu) i domyślnie czyści katalog output/ (clear_output=False go zostawia).

Test ręczny z katalogu repo (tworzy kontekst i wypisuje jego zawartość):
    python -m doc_agents.context
"""

import os
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from doc_agents.config import AppConfig, load_config
from doc_agents.knowledge import KBEntry, load_index
from doc_agents.llm import get_model_for_agent
from doc_agents.output import RunStore, create_run_store


# --- Kontekst ---


@dataclass
class RunContext:
    """Zależności przebiegu wstrzykiwane do węzłów grafu przez Runtime[RunContext]."""

    config: AppConfig  # cały config, w tym ścieżki: config.paths.prompts, config.paths.knowledge_base
    run_store: RunStore  # zapis i odczyt wyników w output/
    models: dict[str, BaseChatModel]  # agent (planner, analyst, editor, reviewer) -> model z jego profilu
    kb_index: list[KBEntry]  # spis bazy wiedzy z knowledge_base/knowledge/index.md


def create_models(config: AppConfig) -> dict[str, BaseChatModel]:
    """Tworzy model językowy dla każdego agenta z config.llm.agents i zwraca słownik agent -> model.

    Po co: każdy agent dostaje model swojego profilu (np. tańszy dla analityków), a obiekty
    tworzymy raz na przebieg zamiast przy każdym wywołaniu. Samo utworzenie modelu nie wysyła
    zapytania - wymaga tylko zmiennych środowiskowych z kluczem i adresem.
    """
    modele_agentow = {}
    for agent in config.llm.agents:
        modele_agentow[agent] = get_model_for_agent(config, agent)
    return modele_agentow


def create_run_context(config: AppConfig, clear_output: bool = True) -> RunContext:
    """Składa RunContext: czyści katalog wyników (z clear_output=False zostawia go bez zmian),
    tworzy modele agentów i wczytuje spis bazy wiedzy.

    Po co: jedno miejsce przygotowania wszystkich zależności przebiegu - main.py i testy
    tworzą kontekst tą funkcją i przekazują go do grafu. Testy agentów podają clear_output=False,
    żeby pracować na wynikach poprzedniego uruchomienia bez ponownego wywoływania wcześniejszych agentów.
    """
    kontekst = RunContext(
        config=config,
        run_store=create_run_store(clear_output),
        models=create_models(config),
        kb_index=load_index(config.paths.knowledge_base),
    )
    return kontekst


# --- Wyświetlanie ---


def print_context(context: RunContext) -> None:
    """Wypisuje zawartość kontekstu: katalog wyników, model każdego agenta i pliki ze spisu bazy wiedzy.

    Po co: przy teście ręcznym widać, że wszystkie zależności się utworzyły i skąd pochodzą.
    """
    print(f"Katalog wyników: {context.run_store.output_dir}")
    print(f"Prompty:         {context.config.paths.prompts}")
    print("Modele agentów:")
    for agent, model in context.models.items():
        print(f"  {agent}: {model.model_name}")
    print(f"Baza wiedzy - pliki w spisie: {len(context.kb_index)}")
    for entry in context.kb_index:
        print(f"  {entry.filename}")


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: wczytuje config.yaml z katalogu repo, tworzy RunContext i wypisuje jego zawartość.

    Po co: sprawdzenie, że kontekst da się zbudować (config, modele, spis bazy wiedzy, katalog wyników)
    zanim użyje go graf.
    """
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(repo_dir, "config.yaml"))
    context = create_run_context(config)
    print_context(context)


if __name__ == "__main__":
    manual_test()
