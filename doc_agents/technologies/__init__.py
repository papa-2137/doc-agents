"""Rejestr technologii: lista obsługiwanych technologii i wybór technologii dla projektu.

Co zawiera: available_technologies() - wszystkie technologie w kolejności sprawdzania,
detect_technology(root, files) - pierwsza technologia, która rozpoznaje projekt,
oraz get_technology(name) - technologia o nazwie zapisanej w mapie projektu (ProjectMap.technology).

Jak dodać technologię: utwórz podklasę Technology w osobnym pliku (wzór: python.py,
kontrakt: base.py) i dopisz jej instancję do listy w available_technologies().

Test ręczny z katalogu repo (moduł __init__ nie uruchamia się przez -m, dlatego python -c):
    python -c "from doc_agents.technologies import manual_test; manual_test()"
"""

from doc_agents.technologies.base import Technology


def available_technologies() -> list[Technology]:
    """Zwraca instancje wszystkich obsługiwanych technologii w kolejności, w jakiej są sprawdzane.

    Po co: jedno miejsce, w którym wpisuje się nową technologię. Kolejność ma znaczenie -
    najpierw technologie bardziej specyficzne (UiPath rozpoznawany po project.json), na końcu Python,
    bo projekt UiPath może zawierać pomocnicze skrypty .py i nie może zostać uznany za pythonowy.

    Importy technologii są wewnątrz funkcji, a nie na górze pliku: dzięki temu uruchomienie
    testowe pojedynczej technologii (python -m doc_agents.technologies.python) nie ładuje jej
    dwa razy i nie wypisuje ostrzeżenia RuntimeWarning.
    """
    from doc_agents.technologies.python import PythonTechnology
    from doc_agents.technologies.uipath import UiPathTechnology

    technologie = [
        UiPathTechnology(),  # pusta klasa - detect() zwraca False do czasu implementacji
        PythonTechnology(),
    ]
    return technologie


def detect_technology(root: str, files: list[str]) -> Technology | None:
    """Zwraca pierwszą technologię, której detect() rozpoznaje projekt; None, gdy żadna nie pasuje.

    Po co: skaner wybiera tu obsługę technologii dla całego projektu (ProjectMap.technology) -
    od niej zależy, które pliki są kodem, jak budować szkielety i jak czytać importy.

    Args:
        root: katalog projektu (bezwzględny lub względny).
        files: wszystkie pliki projektu (ścieżki względne do root), po odfiltrowaniu ignorowanych.
    """
    for technology in available_technologies():
        if technology.detect(root, files):
            return technology
    return None


def get_technology(name: str) -> Technology | None:
    """Zwraca technologię o podanej nazwie (atrybut name, np. "python"); None, gdy żadna nie pasuje
    albo nazwa jest pusta (projekt nierozpoznany).

    Po co: mapa projektu przechowuje tylko nazwę technologii (ProjectMap.technology), a analityk
    potrzebuje obiektu technologii, żeby budować szkielety plików (outline).
    """
    for technology in available_technologies():
        if name != "" and technology.name == name:
            return technology
    return None


# --- Test ręczny ---


def manual_test() -> None:
    """Test ręczny: sprawdza wybór technologii dla kilku przykładowych list plików i wypisuje wynik.

    Po co: szybkie sprawdzenie rejestru (kolejność technologii, None dla nierozpoznanego projektu).
    """
    przyklady = [["main.py", "src/report.py"], ["project.json", "Main.xaml"], ["dane.xlsx"]]
    for files in przyklady:
        technology = detect_technology(".", files)
        nazwa_technologii = "None"
        if technology is not None:
            nazwa_technologii = technology.name
        print(f"{files} -> {nazwa_technologii}")
