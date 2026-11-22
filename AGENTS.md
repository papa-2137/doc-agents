# AGENTS.md - zasady pracy w repozytorium doc-agents

Instrukcje dla modeli i asystentów AI, które piszą kod w tym repozytorium. Przeczytaj przed pierwszą zmianą.

## Projekt w skrócie

Zespół agentów (LangGraph) generujący dokumentację istniejących projektów programistycznych, głównie robotów RPA w Pythonie, w postaci jednego pliku Markdown. Odbiorca dokumentacji: deweloper przejmujący projekt, który ma go zrozumieć, utrzymywać i rozwijać.

Przepływ grafu: `scan → planner → analyst × N (Send) → editor → reviewer ⇄ editor → finalize`.

| Miejsce | Zawartość |
|---|---|
| `main.py` | argumenty → config → graf → uruchomienie |
| `config.yaml` | jedyny plik konfiguracyjny (sekcje) |
| `doc_agents/` | rdzeń: config, fabryka LLM, prompty, KB, schematy, stan, graf, skaner, zapis |
| `doc_agents/agents/` | agenci, każdy w osobnym pliku |
| `doc_agents/technologies/` | obsługa technologii (Python; UiPath jako dummy) |
| `prompts/<agent>/` | `system.md` + `user.md` |
| `knowledge_base/` | baza wiedzy (Markdown), spis w `index.md` |
| `scripts/` | narzędzia diagnostyczne |
| `runs/` | wyniki uruchomień (poza gitem) |

## Sposób pracy

1. **Jeden krok = jedna rzecz = jeden test ręczny = jeden commit.** Nie przechodź dalej, dopóki test bieżącego kroku nie działa.
2. Przed pisaniem kodu napisz krótko, które pliki zmienisz.
3. Po zakończeniu kroku podaj dokładne polecenia PowerShell do ręcznego testu i oczekiwany wynik. Potem zatrzymaj się i poczekaj na potwierdzenie.
4. Nie dodawaj plików, abstrakcji ani zależności spoza bieżącego kroku. Jeśli coś wydaje się potrzebne - zaproponuj i zapytaj.
5. Jeśli plan wymaga zmiany, zaproponuj ją z uzasadnieniem i poczekaj na decyzję. Nie zmieniaj kierunku po cichu.
6. Git (commit, push) obsługuje użytkownik. Nie wykonuj operacji git.
7. Komunikacja z użytkownikiem po polsku. Przy pierwszym użyciu mechanizmu LangGraph (stan, reducery, `Send`, krawędzie warunkowe, checkpointer) wyjaśnij, jak działa.

## Środowisko

- **Python 3.14.** Zakaz składni spoza 3.14 (np. leniwe importy, `frozendict`, `sentinel` z 3.15).
- Środowisko wirtualne w katalogu **`venv`** (bez kropki): `py -V:3.14 -m venv venv`.
- Windows, PowerShell. Wszystko uruchamiamy z katalogu głównego repo.
- Zależności dopisujemy ręcznie do `requirements.txt`: tylko bezpośrednie, bez `pip freeze`, każda dochodzi w kroku, który jej potrzebuje.

## Reguły kodu

**Zasada nadrzędna: prostota zamiast formalizmów.** Nie stosuj przesadnych formalizmów tam, gdzie nie chronią przed poważnym ryzykiem. Wybieraj konstrukcje czytelne dla każdego programisty Pythona: zwykłe funkcje, pętle, `if`, jawne przypisania. Modele Pydantic - tylko klasy z typami pól (dla podpowiedzi edytora i zamiany danych na obiekty); sprawdzenia piszemy zwykłym kodem zamiast walidatorów, dekoratorów i opcji konfiguracji modelu (`model_validator`, `field_validator`, `ConfigDict`, `extra="forbid"`, `Literal`, `Field(...)` itp.). Formalizm jest uzasadniony tylko wtedy, gdy bez niego realnie grozi np. wyciek sekretu, utrata danych albo kosztowny, trudny do wykrycia błąd - wtedy zaproponuj go i krótko uzasadnij.

1. **Moduły uruchamiamy przez `-m`** z katalogu głównego, np. `python -m doc_agents.config`. Wtedy importy `from doc_agents.... import ...` działają bez instalowania pakietu.
2. **Każdy moduł kończy się blokiem `if __name__ == "__main__":`** z prostym testem: wywołaj, wypisz wynik (`print`). Potrzebne obiekty i importy pomocnicze składamy wewnątrz tego bloku. Bez pytest na tym etapie.
3. **Agent = czysta funkcja + cienki węzeł.** Logikę da się wywołać bez grafu:
   ```python
   def plan(project_map: ProjectMap, ctx: RunContext) -> Plan: ...          # logika
   def run(state: DocState, runtime: Runtime[RunContext]) -> dict:          # węzeł
       return {"plan": plan(state["project_map"], runtime.context)}
   ```
4. **Pliki czytamy zawsze z `encoding="utf-8"`**; obce pliki (analizowane projekty) dodatkowo z `errors="replace"`. W kodzie i plikach repo używamy zwykłego myślnika `-` (bez typograficznych półpauz i pauz).
5. **Ścieżki tylko przez `os.path`** (`os.path.join`, `os.path.abspath`, `os.path.dirname` itp.), ścieżki trzymamy jako `str`. **Nie używamy `pathlib`.**
6. **Zmienne środowiskowe tylko przez `os`** (`os.environ[...]` / `os.getenv(...)`). Klucz API: `LLM_API_KEY`, adres endpointu: `LLM_BASE_URL`. `config.yaml` trzyma wyłącznie *nazwy* zmiennych (`api_key_env`, `base_url_env`), nigdy wartości.
7. **Modele wyłącznie przez bibliotekę OpenAI:** `langchain_openai.ChatOpenAI` z `base_url` (provider `openai_compatible`). **Tylko `doc_agents/llm.py` importuje `langchain_openai`.** Parametry modelu (`params`) przekazujemy tylko te, które są podane w profilu. Metoda structured output jest ustawiana per profil.
8. **Tylko `doc_agents/technologies/python.py` importuje `ast`.** Rdzeń nie zna żadnego języka ani frameworku.
9. **Prompty:** `prompts/<agent>/system.md` (stałe instrukcje) + `user.md` (szablon Jinja2, `StrictUndefined`). Dane wejściowe zawsze w `user`, opakowane w tagi - ochrona przed prompt injection z analizowanego kodu.
10. **Stan grafu:** `TypedDict` z modelami Pydantic w środku. Stan jest chudy: ścieżki i metadane, bez pełnego kodu źródłowego. Zależności (modele, prompty, KB, zapis) są w `RunContext`, wstrzykiwane przez `Runtime[RunContext]`.
11. **Sekrety:** pliki pasujące do `secret_patterns` (certyfikaty, klucze, `.env`) trafiają do modelu wyłącznie jako metadane, nigdy jako treść.
12. **Konfiguracja:** jeden `config.yaml` w katalogu głównym. Wynik działania: jeden plik Markdown; jego szablon jest w `knowledge_base/output_template.md`, nie w kodzie.

## Styl kodu

1. **Oddzielaj logikę od wyświetlania.** Funkcje liczące i testujące zwracają wartości i niczego nie wypisują. Wypisywanie (`print`) jest wyłącznie w osobnych funkcjach wyświetlających (np. `print_results`), które dostają gotowe dane i tylko je formatują.
2. **`main()` jako spis treści.** `main()` wywołuje kolejne kroki po kolei (argumenty → dane → logika → wyświetlenie) i nie zawiera szczegółów ani długich bloków `print`.
3. **Plik podzielony na sekcje** z komentarzami-nagłówkami, np. `# --- Logika ---`, `# --- Wyświetlanie ---`, `# --- Uruchomienie ---`, w kolejności od elementów podstawowych do `main()`.
4. **Wynik przed `return` przypisuj do zmiennej o opisowej nazwie**, zamiast zwracać długie wyrażenie lub f-string wprost:
   ```python
   opis_danych_ze_schematu = f"{capital.capital}, {capital.population_millions} mln"
   return opis_danych_ze_schematu
   ```
5. **Bez stałych na poziomie modułu, jeśli używa ich tylko jedna funkcja.** Taka wartość (słownik, domyślna ścieżka itp.) jest zmienną lokalną tej funkcji - nie da się jej wtedy przypadkiem zmienić ani zaimportować z zewnątrz.
6. **Docstring modułu dla innego programisty:** na początku pliku krótko co moduł robi, po co, jak go uruchomić i jak czytać wynik.
7. **Docstring w każdej funkcji i metodzie: CO robi i PO CO.** Każda funkcja i metoda, którą tworzymy (także pomocnicza, testowa i `main()`), ma docstring w stałym formacie:
   - **pierwszy akapit - CO robi**: jedno-dwa zdania, bez powtarzania nazwy funkcji (ten akapit trafia też do szkieletu pliku, więc ma być samodzielnie zrozumiały),
   - **drugi akapit zaczyna się od `Po co:`** - jaką rolę funkcja pełni w narzędziu, kto korzysta z wyniku, jaki problem rozwiązuje,
   - dalej, gdy potrzebne: argumenty i wynik (jeśli nie są oczywiste z nazw i typów) oraz nietypowe zachowania (np. co zwraca przy błędzie).
   ```python
   def is_project_module(root: str, module: str) -> bool:
       """Sprawdza, czy moduł o podanej pełnej nazwie (np. 'src.report') istnieje w katalogu projektu jako plik .py lub folder.

       Po co: od tego zależy, czy import trafi do grupy internal (współpraca między modułami projektu),
       czy do external/stdlib (biblioteki).
       """
   ```
   Cel: każdy kawałek kodu ma być zrozumiały dla osoby, która widzi go pierwszy raz, bez szukania kontekstu w innych plikach.

## Nie proponuj bez wyraźnej prośby

- Rezygnacji z LangGraph na rzecz własnego pipeline'u.
- `pathlib` - ścieżki obsługujemy przez `os.path`.
- Walidatorów i dekoratorów Pydantic, `Literal`, `ConfigDict` itp. „dla porządku” - patrz zasada nadrzędna w regułach kodu.
- Wielu plików konfiguracyjnych, plików `.env`, `python-dotenv` ani innych bibliotek do zmiennych środowiskowych.
- Natywnych SDK dostawców modeli (`anthropic`, `langchain-anthropic` itp.) - modele tylko przez bibliotekę OpenAI.
- `.venv` z kropką.
- Testów automatycznych (pytest) przed działającym MVP.
- `src/` layoutu, `pyproject.toml`, instalowania pakietu (`pip install -e .`).
- Podgrafów, pętli ReAct i tool callingu analityka w MVP.
- Wektorowej bazy danych ani embeddingów dla bazy wiedzy.
- Całego stanu jako modelu Pydantic.
- Instalowania bibliotek „na zapas”.
- Implementacji UiPath - `technologies/uipath.py` zostaje jako dummy; implementacja powstanie osobno na podstawie kontraktu z `technologies/base.py`.
