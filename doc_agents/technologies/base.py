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
        """Czy projekt jest napisany w tej technologii?

        Args:
            root: katalog projektu (bezwzględny).
            files: wszystkie pliki projektu (względne do root), już po odfiltrowaniu ignorowanych.

        Returns:
            True, jeśli to ta technologia (np. są pliki .py, project.json UiPatha itp.).
        """
        raise NotImplementedError(f"{type(self).__name__}.detect() - do implementacji")

    def is_source(self, path: str) -> bool:
        """Czy plik jest kodem źródłowym tej technologii (kandydatem do analizy)?

        Args:
            path: ścieżka względna pliku.

        Returns:
            True dla plików kodu (np. .py, .xaml); False dla configów, danych, binarek itp.
        """
        raise NotImplementedError(f"{type(self).__name__}.is_source() - do implementacji")

    def find_entrypoints(self, root: str, files: list[str]) -> list[str]:
        """Pliki, od których startuje projekt (punkty wejścia).

        Args:
            root: katalog projektu (bezwzględny).
            files: wszystkie pliki projektu (względne do root).

        Returns:
            Ścieżki względne punktów wejścia, np. ["main.py"] albo ["Main.xaml"]; pusta lista, gdy brak.
        """
        raise NotImplementedError(f"{type(self).__name__}.find_entrypoints() - do implementacji")

    def outline(self, root: str, path: str) -> str:
        """Szkielet pliku dla modelu językowego - struktura bez pełnej treści.

        Ma pomóc analitykowi szybko zrozumieć plik: np. docstring modułu, klasy, metody, funkcje,
        ich sygnatury i pierwsze linie docstringów (Python) albo lista aktywności i argumentów (UiPath).

        Args:
            root: katalog projektu (bezwzględny).
            path: ścieżka względna pliku źródłowego.

        Returns:
            Czytelny tekst (wiele linii); pusty string, gdy nie da się zbudować szkieletu.
        """
        raise NotImplementedError(f"{type(self).__name__}.outline() - do implementacji")

    def imports(self, root: str, path: str) -> dict[str, list[str]]:
        """Zależności pliku z podziałem na wewnętrzne (z projektu) i zewnętrzne.

        Args:
            root: katalog projektu (bezwzględny).
            path: ścieżka względna pliku źródłowego.

        Returns:
            Słownik z dwoma kluczami:
                "internal" - moduły/pliki z tego projektu (np. "src.report"),
                "external" - biblioteki i frameworki spoza projektu (np. "selenium", "roboforge").
        """
        raise NotImplementedError(f"{type(self).__name__}.imports() - do implementacji")


if __name__ == "__main__":

    class DemoTechnology(Technology):
        """Minimalna podklasa tylko do testu: 'kodem' są pliki .demo."""

        name = "demo"

        def detect(self, root, files):
            czy_sa_pliki_demo = any(f.endswith(".demo") for f in files)
            return czy_sa_pliki_demo

        def is_source(self, path):
            czy_plik_demo = path.endswith(".demo")
            return czy_plik_demo

        def find_entrypoints(self, root, files):
            punkty_wejscia = [f for f in files if f == "start.demo"]
            return punkty_wejscia

        def outline(self, root, path):
            szkielet = f"plik {path}: (demo - brak struktury)"
            return szkielet

        def imports(self, root, path):
            zaleznosci = {"internal": ["helpers.demo"], "external": ["biblioteka_x"]}
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
