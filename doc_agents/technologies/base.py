"""Klasa bazowa obsługi technologii (Python, UiPath, ...).

Co to jest: kontrakt, który musi spełnić obsługa każdej technologii. Reszta narzędzia (skaner,
analitycy) korzysta wyłącznie z metod tej klasy i nie wie, jaki język lub framework jest pod spodem.
Rdzeń narzędzia nie zna żadnej technologii - cała wiedza o niej siedzi w podklasie.

Jak dodać nową technologię:
    1. Utwórz plik doc_agents/technologies/<nazwa>.py z podklasą Technology.
    2. Ustaw atrybut `name` i zaimplementuj wszystkie metody opisane niżej.
    3. Dopisz technologię do słownika w doc_agents/technologies/__init__.py.

Umowy wspólne dla wszystkich metod:
    - `root` to ścieżka bezwzględna katalogu dokumentowanego projektu,
    - `files` i `path` to ścieżki WZGLĘDNE do `root` (tak jak w FileEntry.path),
    - metody nie wypisują niczego - tylko zwracają wartości,
    - pliki czytamy z encoding="utf-8" i errors="replace" (analizowany kod bywa w różnych kodowaniach).

Uruchomienie testowe z katalogu repo (minimalna podklasa demonstracyjna):
    python -m doc_agents.technologies.base
"""


class Technology:
    """Obsługa jednej technologii. Podklasa musi ustawić `name` i zaimplementować wszystkie metody."""

    name = ""  # krótka nazwa technologii, np. "python"; trafia do ProjectMap.technology

    def detect(self, root: str, files: list[str]) -> bool:
        """Sprawdza, czy projekt jest napisany w tej technologii.

        Po co: na tej podstawie narzędzie wybiera obsługę technologii dla całego projektu
        (ProjectMap.technology) - od niej zależy, które pliki są kodem i jak je analizować.

        Args:
            root: katalog projektu (bezwzględny).
            files: wszystkie pliki projektu (względne do root), już po odfiltrowaniu ignorowanych.

        Returns:
            True, jeśli to ta technologia (np. są pliki .py, project.json UiPatha itp.).
        """
        raise NotImplementedError(f"{type(self).__name__}.detect() - do implementacji")

    def is_source(self, path: str) -> bool:
        """Sprawdza, czy plik jest kodem źródłowym tej technologii (kandydatem do analizy).

        Po co: skaner nadaje plikom role (source, config, data...), a tylko pliki z rolą source trafiają
        do analityków jako jednostki kodu - reszta jest opisywana wyłącznie metadanymi.

        Args:
            path: ścieżka względna pliku.

        Returns:
            True dla plików kodu (np. .py, .xaml); False dla configów, danych, binarek itp.
        """
        raise NotImplementedError(f"{type(self).__name__}.is_source() - do implementacji")

    def find_entrypoints(self, root: str, files: list[str]) -> list[str]:
        """Znajduje pliki, od których startuje projekt (punkty wejścia).

        Po co: planner i redaktor zaczynają opis projektu od miejsca uruchomienia - punkt wejścia
        pokazuje, jak robot jest startowany i od którego modułu zaczyna się przepływ.

        Args:
            root: katalog projektu (bezwzględny).
            files: wszystkie pliki projektu (względne do root).

        Returns:
            Ścieżki względne punktów wejścia, np. ["main.py"] albo ["Main.xaml"]; pusta lista, gdy brak.
        """
        raise NotImplementedError(f"{type(self).__name__}.find_entrypoints() - do implementacji")

    def outline(self, root: str, path: str) -> str:
        """Buduje szkielet pliku dla modelu językowego - strukturę bez pełnej treści.
        Np. docstring modułu, klasy, metody, funkcje, ich sygnatury i opisy (Python)
        albo lista aktywności i argumentów (UiPath).

        Po co: analityk szybko widzi strukturę pliku przed lekturą całego kodu, a przy dużych plikach
        szkielet pomaga modelowi się zorientować bez czytania wszystkiego.

        Args:
            root: katalog projektu (bezwzględny).
            path: ścieżka względna pliku źródłowego.

        Returns:
            Czytelny tekst (wiele linii); pusty string, gdy nie da się zbudować szkieletu.
        """
        raise NotImplementedError(f"{type(self).__name__}.outline() - do implementacji")

    def imports(self, root: str, path: str) -> dict[str, list[str]]:
        """Zwraca zależności pliku w trzech grupach: z projektu, zewnętrzne i standardowe.

        Po co: analityk widzi, z którymi modułami projektu współpracuje plik i co automatyzuje
        (np. biblioteka do przeglądarki czy Excela), planner buduje z tego obraz powiązań między modułami,
        a dokumentacja dostaje sekcję zależności - także frameworków spoza plików projektu.

        Args:
            root: katalog projektu (bezwzględny).
            path: ścieżka względna pliku źródłowego.

        Returns:
            Słownik z trzema kluczami (wartości: pełne nazwy, bez powtórzeń, posortowane):
                "internal" - moduły/pliki z tego projektu (np. "src.report"),
                "external" - biblioteki i frameworki do zainstalowania, spoza projektu
                             (np. "selenium.webdriver.common.by", "roboforge.launcher"),
                "stdlib"   - elementy standardowo dostępne w technologii (w Pythonie biblioteka
                             standardowa, np. "os", "time"); pusta lista, jeśli w danej technologii
                             takie rozróżnienie nie ma sensu.
        """
        raise NotImplementedError(f"{type(self).__name__}.imports() - do implementacji")


if __name__ == "__main__":

    class DemoTechnology(Technology):
        """Minimalna podklasa tylko do testu: 'kodem' są pliki .demo."""

        name = "demo"

        def detect(self, root, files):
            """Uznaje projekt za 'demo', gdy jest w nim choć jeden plik .demo.

            Po co: pokazuje w teście, jak podklasa realizuje kontrakt detect() - bez prawdziwej technologii.
            """
            czy_sa_pliki_demo = any(f.endswith(".demo") for f in files)
            return czy_sa_pliki_demo

        def is_source(self, path):
            """Traktuje jako kod tylko pliki .demo.

            Po co: pokazuje w teście, jak podklasa odróżnia kod od pozostałych plików projektu.
            """
            czy_plik_demo = path.endswith(".demo")
            return czy_plik_demo

        def find_entrypoints(self, root, files):
            """Zwraca plik start.demo jako jedyny punkt wejścia, jeśli istnieje.

            Po co: pokazuje w teście format wyniku find_entrypoints() - lista ścieżek względnych.
            """
            punkty_wejscia = [f for f in files if f == "start.demo"]
            return punkty_wejscia

        def outline(self, root, path):
            """Zwraca stały, przykładowy szkielet pliku.

            Po co: pokazuje w teście, że outline() zwraca zwykły tekst dla modelu językowego.
            """
            szkielet = f"plik {path}: (demo - brak struktury)"
            return szkielet

        def imports(self, root, path):
            """Zwraca stałe, przykładowe zależności w trzech grupach.

            Po co: pokazuje w teście wymagany kształt wyniku imports() - słownik z kluczami internal, external, stdlib.
            """
            zaleznosci = {"internal": ["helpers.demo"], "external": ["biblioteka_x"], "stdlib": []}
            return zaleznosci

    root = r"C:\projekt_demo"
    files = ["start.demo", "helpers.demo", "config.yml", "dane.xlsx"]
    demo = DemoTechnology()

    print(f"name:             {demo.name}")
    print(f"detect:           {demo.detect(root, files)}")
    print(f"is_source:        {[(f, demo.is_source(f)) for f in files]}")
    print(f"find_entrypoints: {demo.find_entrypoints(root, files)}")
    print(f"outline:          {demo.outline(root, 'start.demo')}")
    print(f"imports:          {demo.imports(root, 'start.demo')}")

    try:
        Technology().detect(root, files)
    except NotImplementedError as e:
        print(f"\nKlasa bazowa bez implementacji: NotImplementedError: {e}")
