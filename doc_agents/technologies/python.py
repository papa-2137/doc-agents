"""Obsługa technologii Python (podklasa Technology).

Co robi: implementuje kontrakt z doc_agents/technologies/base.py dla projektów w Pythonie.
Szkielet (outline) pokazuje strukturę także kodu „spaghetti”: rozmiar pliku, zakresy linii
definicji, zmienne modułu i opis kodu wykonywanego poza funkcjami.
Kod analizowanego projektu jest tylko CZYTANY i parsowany modułem `ast` (parser Pythona
z biblioteki standardowej) - nigdy nie jest importowany ani uruchamiany.

Jedyne miejsce w projekcie, które importuje `ast` (reguła z AGENTS.md).

Stan implementacji:
    - outline()        - gotowe (krok 12),
    - imports()        - gotowe (krok 13),
    - detect(), is_source(), find_entrypoints() - krok 14.

Uruchomienie testowe z katalogu repo (szkielet i importy wskazanego pliku):
    python -m doc_agents.technologies.python <katalog projektu> <ścieżka pliku względna do katalogu>
    np. python -m doc_agents.technologies.python ..\\..\\tests\\01_rpa_challange_roboforge src\\parabank_page.py
Bez argumentów pokazuje szkielet i importy pliku doc_agents/technologies/base.py z tego repo.
"""

import ast
import os
import sys

from doc_agents.technologies.base import Technology


# --- Funkcje pomocnicze do budowy szkieletu ---


def first_paragraph(docstring: str | None, max_length: int = 200) -> str:
    """Zwraca pierwszy akapit docstringu (linie do pierwszej pustej), sklejony w jedną linię i przycięty do max_length.

    Po co: w szkielecie pliku przy każdej klasie i funkcji pokazujemy krótki opis; pierwsza linia
    często urywa się w pół zdania, a pełny docstring bywa bardzo długi (np. tutoriale) - akapit to kompromis.
    """
    if not docstring:
        return ""
    paragraph_lines = []
    for line in docstring.strip().splitlines():
        if not line.strip():
            break
        paragraph_lines.append(line.strip())
    akapit = " ".join(paragraph_lines)
    if len(akapit) > max_length:
        akapit = akapit[:max_length].rstrip() + "..."
    return akapit


def constant_names(body: list) -> list[str]:
    """Zwraca nazwy stałych (przypisań do nazw pisanych WIELKIMI LITERAMI) w ciele modułu lub klasy.

    Po co: w kodzie RPA stałe często niosą kluczową informację (selektory, adresy, statusy) -
    same nazwy w szkielecie mówią analitykowi, czym operuje moduł, bez wydłużania szkieletu o wartości.
    """
    names = []
    for node in body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                names.append(target.id)
    return names


def line_range(node) -> str:
    """Zwraca zakres linii definicji w postaci '[linie 40-310, razem 271]'.

    Po co: w szkielecie od razu widać bardzo długie funkcje i klasy, których sam opis nie odda -
    to sygnał dla analityka (i dla nas przy optymalizacji), gdzie jest najwięcej logiki.
    """
    count = node.end_lineno - node.lineno + 1
    zakres_linii = f"[linie {node.lineno}-{node.end_lineno}, razem {count}]"
    return zakres_linii


def module_level_segments(tree: ast.Module) -> list[list]:
    """Zbiera kod wykonywany na poziomie modułu (poza importami, definicjami i docstringiem)
    i grupuje go w odcinki kolejnych instrukcji - np. stałe na górze pliku i blok `if __name__` na dole.

    Po co: w kodzie „spaghetti” cała logika siedzi poza funkcjami i bez tego szkielet byłby pusty;
    podział na odcinki pokazuje, gdzie dokładnie ten kod leży, zamiast jednego mylącego zakresu na cały plik.
    """
    definitions = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    segments = []
    current = []
    for index, node in enumerate(tree.body):
        is_docstring = index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if isinstance(node, definitions) or is_docstring:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(node)
    if current:
        segments.append(current)
    return segments


def variable_names(statements: list) -> list[str]:
    """Zwraca nazwy zmiennych przypisywanych w podanych instrukcjach (bez stałych pisanych WIELKIMI LITERAMI), bez powtórzeń.

    Po co: w skryptach bez konwencji nazewnictwa zmienne modułu są jedynym śladem tego,
    czym skrypt operuje (np. workbook, driver przeglądarki).
    """
    names = []
    for statement in statements:
        for node in ast.walk(statement):
            is_assigned_name = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            if is_assigned_name and not node.id.isupper() and node.id not in names:
                names.append(node.id)
    return names


def describe_module_code(segments: list[list]) -> str:
    """Buduje jedną linię opisu kodu poza funkcjami: liczba instrukcji, odcinki linii, liczba pętli i bloków try.

    Po co: od razu widać, czy plik jest skryptem z logiką „luzem” (pętle, obsługa błędów),
    czy biblioteką funkcji z kilkoma stałymi.
    """
    statements = [statement for segment in segments for statement in segment]
    ranges = ", ".join(f"{segment[0].lineno}-{segment[-1].end_lineno}" for segment in segments)
    loops = 0
    tries = 0
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                loops += 1
            elif isinstance(node, ast.Try):
                tries += 1
    opis_kodu = f"Kod poza funkcjami: instrukcje {len(statements)}, linie {ranges}"
    if loops or tries:
        opis_kodu += f" - pętle: {loops}, try: {tries}"
    return opis_kodu


def format_function(node, indent: str) -> list[str]:
    """Buduje linie szkieletu jednej funkcji lub metody: dekoratory, sygnatura z zakresem linii, pierwszy akapit docstringu.

    Po co: sygnatura z typami i opisem to minimum, żeby analityk wiedział, co funkcja przyjmuje,
    co zwraca i do czego służy - bez czytania jej ciała.
    """
    lines = [f"{indent}@{ast.unparse(decorator)}" for decorator in node.decorator_list]

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    lines.append(f"{indent}{prefix} {node.name}({ast.unparse(node.args)}){returns}  {line_range(node)}")

    doc = first_paragraph(ast.get_docstring(node))
    if doc:
        lines.append(f"{indent}    {doc}")
    return lines


def format_class(node: ast.ClassDef, indent: str) -> list[str]:
    """Buduje linie szkieletu klasy: nagłówek z klasami bazowymi i zakresem linii, docstring, stałe, metody, klasy zagnieżdżone.

    Po co: klasy bazowe pokazują zależność od frameworku (np. dziedziczenie po klasie workera),
    a lista metod - jakie kroki procesu klasa realizuje.
    """
    lines = [f"{indent}@{ast.unparse(decorator)}" for decorator in node.decorator_list]

    bases = ", ".join(ast.unparse(base) for base in node.bases)
    header = f"{indent}class {node.name}({bases})" if bases else f"{indent}class {node.name}"
    lines.append(f"{header}  {line_range(node)}")

    doc = first_paragraph(ast.get_docstring(node))
    if doc:
        lines.append(f"{indent}    {doc}")

    constants = constant_names(node.body)
    if constants:
        lines.append(f"{indent}    Stałe: {', '.join(constants)}")

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.extend(format_function(child, indent + "    "))
        elif isinstance(child, ast.ClassDef):
            lines.extend(format_class(child, indent + "    "))
    return lines


def build_outline(tree: ast.Module, line_count: int) -> str:
    """Składa szkielet całego modułu: liczba linii, docstring, stałe, zmienne, kod poza funkcjami, klasy i funkcje.

    Po co: to wynik metody outline() - jeden czytelny tekst, który analityk dostaje razem z kodem pliku.
    """
    lines = [f"Liczba linii: {line_count}"]

    doc = first_paragraph(ast.get_docstring(tree))
    if doc:
        lines.append(f"Moduł: {doc}")

    constants = constant_names(tree.body)
    if constants:
        lines.append(f"Stałe: {', '.join(constants)}")

    segments = module_level_segments(tree)
    variables = variable_names([statement for segment in segments for statement in segment])
    if variables:
        lines.append(f"Zmienne modułu: {', '.join(variables)}")
    if segments:
        lines.append(describe_module_code(segments))

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            lines.append("")
            lines.extend(format_class(node, ""))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append("")
            lines.extend(format_function(node, ""))

    szkielet = "\n".join(lines).strip()
    return szkielet


# --- Funkcje pomocnicze do analizy importów ---


def is_project_module(root: str, module: str) -> bool:
    """Sprawdza, czy moduł o podanej pełnej nazwie (np. 'src.report') istnieje w katalogu projektu jako plik .py lub folder.

    Po co: od tego zależy, czy import trafi do grupy internal (współpraca między modułami projektu),
    czy do external/stdlib (biblioteki).
    """
    base_path = os.path.join(root, *module.split("."))
    czy_istnieje = os.path.isfile(base_path + ".py") or os.path.isdir(base_path)
    return czy_istnieje


def resolve_relative(path: str, level: int, module: str | None) -> str:
    """Zamienia import względny na pełną nazwę modułu, np. w src/x.py: 'from .report import y' -> 'src.report'.

    Po co: w wyniku imports() chcemy jednolitych, pełnych nazw modułów, niezależnie od tego,
    czy autor kodu pisał importy względne, czy bezwzględne.
    """
    package_parts = os.path.dirname(path).replace("\\", "/").split("/") if os.path.dirname(path) else []
    if level > 1:
        package_parts = package_parts[: len(package_parts) - (level - 1)]
    if module:
        package_parts = package_parts + module.split(".")
    pelna_nazwa = ".".join(part for part in package_parts if part)
    return pelna_nazwa


def collect_imported_modules(tree: ast.Module, root: str, path: str) -> list[tuple[str, bool]]:
    """Zbiera wszystkie importy pliku (także wewnątrz funkcji i try/except) jako pary (pełna nazwa modułu, czy względny).
    Przy 'from pakiet import nazwa' dokłada '.nazwa' tylko wtedy, gdy to podmoduł istniejący w projekcie
    (np. 'from src import report' -> 'src.report'); funkcji i klas z importu nie traktuje jak modułów.

    Po co: starszy kod RPA często importuje wewnątrz funkcji lub warunkowo - przejście po całym drzewie
    składni łapie te importy, a sprawdzenie podmodułów daje dokładne nazwy plików projektu.
    """
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((alias.name, False))
        elif isinstance(node, ast.ImportFrom):
            is_relative = node.level > 0
            base = resolve_relative(path, node.level, node.module) if is_relative else (node.module or "")
            submodules = [f"{base}.{alias.name}" if base else alias.name for alias in node.names]
            project_submodules = [name for name in submodules if is_project_module(root, name)]
            if project_submodules:
                modules.extend((name, is_relative) for name in project_submodules)
            elif base:
                modules.append((base, is_relative))
    return modules


def classify_module(root: str, module: str, is_relative: bool) -> str:
    """Przypisuje moduł do grupy: internal (z projektu), stdlib (biblioteka standardowa) albo external (reszta).
    Kolejność ma znaczenie: plik projektu o nazwie modułu standardowego (np. własny logging.py)
    przesłania moduł standardowy, więc najpierw sprawdzamy projekt.

    Po co: podział oddziela prawdziwe zależności do zainstalowania (external) od szumu biblioteki
    standardowej i od współpracy między modułami projektu - to bezpośrednio trafia do dokumentacji.
    """
    top_package = module.split(".")[0]
    if is_relative or is_project_module(root, top_package):
        return "internal"
    if top_package in sys.stdlib_module_names:
        return "stdlib"
    return "external"


# --- Technologia ---


class PythonTechnology(Technology):
    """Projekty w Pythonie."""

    name = "python"

    def outline(self, root: str, path: str) -> str:
        """Czyta plik .py (z pominięciem BOM) i zwraca jego szkielet; pusty string, gdy pliku nie da się sparsować.

        Po co: implementacja kontraktu Technology.outline() dla Pythona - kod jest tylko parsowany,
        nigdy uruchamiany, więc analiza jest bezpieczna także dla kodu, który wymaga środowiska robota.
        """
        full_path = os.path.join(root, path)
        # utf-8-sig: jak utf-8, ale pomija ewentualny znacznik BOM na początku pliku
        with open(full_path, encoding="utf-8-sig", errors="replace") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ""
        szkielet = build_outline(tree, len(source.splitlines()))
        return szkielet

    def imports(self, root: str, path: str) -> dict[str, list[str]]:
        """Czyta plik .py i zwraca jego importy w trzech grupach (internal, external, stdlib),
        jako pełne nazwy modułów, bez powtórzeń, posortowane. Przy błędzie składni zwraca puste grupy.
        Nie wykrywa importów dynamicznych (importlib.import_module, __import__) - ich nazwy znane są
        dopiero po uruchomieniu kodu.

        Po co: implementacja kontraktu Technology.imports() dla Pythona - zależności pliku dla analityka,
        plannera i sekcji zależności w dokumentacji.
        """
        groups = {"internal": [], "external": [], "stdlib": []}
        full_path = os.path.join(root, path)
        with open(full_path, encoding="utf-8-sig", errors="replace") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return groups

        for module, is_relative in collect_imported_modules(tree, root, path):
            group = classify_module(root, module, is_relative)
            if module not in groups[group]:
                groups[group].append(module)

        importy_w_grupach = {name: sorted(modules) for name, modules in groups.items()}
        return importy_w_grupach


if __name__ == "__main__":
    if len(sys.argv) == 3:
        root, path = sys.argv[1], sys.argv[2]
    else:
        root, path = os.getcwd(), os.path.join("doc_agents", "technologies", "base.py")

    technology = PythonTechnology()
    print(f"Plik: {os.path.join(os.path.abspath(root), path)}")

    print("\n=== Szkielet ===\n")
    print(technology.outline(root, path))

    print("\n=== Importy ===\n")
    for group, modules in technology.imports(root, path).items():
        print(f"{group}: {', '.join(modules) if modules else '(brak)'}")
