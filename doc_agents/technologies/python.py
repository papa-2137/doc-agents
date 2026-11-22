"""Obsługa technologii Python (podklasa Technology).

Co robi: implementuje kontrakt z doc_agents/technologies/base.py dla projektów w Pythonie.
Szkielet (outline) pokazuje strukturę także kodu „spaghetti”: rozmiar pliku, zakresy linii
definicji, zmienne modułu i opis kodu wykonywanego poza funkcjami.
Kod analizowanego projektu jest tylko CZYTANY i parsowany modułem `ast` (parser Pythona
z biblioteki standardowej) - nigdy nie jest importowany ani uruchamiany.

Jedyne miejsce w projekcie, które importuje `ast` (reguła z AGENTS.md).

Stan implementacji:
    - outline()        - gotowe (krok 12),
    - imports()        - krok 13,
    - detect(), is_source(), find_entrypoints() - krok 14.

Uruchomienie testowe z katalogu repo (szkielet wskazanego pliku):
    python -m doc_agents.technologies.python <katalog projektu> <ścieżka pliku względna do katalogu>
    np. python -m doc_agents.technologies.python ..\\..\\tests\\01_rpa_challange_roboforge src\\parabank_page.py
Bez argumentów pokazuje szkielet pliku doc_agents/technologies/base.py z tego repo.
"""

import ast
import os

from doc_agents.technologies.base import Technology


# --- Funkcje pomocnicze do budowy szkieletu ---


def first_paragraph(docstring: str | None, max_length: int = 200) -> str:
    """Pierwszy akapit docstringu (linie do pierwszej pustej) sklejony w jedną linię i przycięty do max_length."""
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
    """Nazwy stałych (przypisania do nazw pisanych WIELKIMI LITERAMI) w ciele modułu lub klasy."""
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
    """Zakres linii definicji, np. '[linie 40-310, razem 271]' - od razu widać bardzo długie funkcje."""
    count = node.end_lineno - node.lineno + 1
    zakres_linii = f"[linie {node.lineno}-{node.end_lineno}, razem {count}]"
    return zakres_linii


def module_level_segments(tree: ast.Module) -> list[list]:
    """Kod wykonywany na poziomie modułu (poza importami, definicjami i docstringiem),
    pogrupowany w odcinki kolejnych instrukcji - np. stałe na górze pliku i blok `if __name__` na dole.
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
    """Nazwy zmiennych przypisywanych w podanych instrukcjach (bez stałych pisanych WIELKIMI LITERAMI)."""
    names = []
    for statement in statements:
        for node in ast.walk(statement):
            is_assigned_name = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            if is_assigned_name and not node.id.isupper() and node.id not in names:
                names.append(node.id)
    return names


def describe_module_code(segments: list[list]) -> str:
    """Opis kodu poza funkcjami, np. 'Kod poza funkcjami: instrukcje 13, linie 5-30 - pętle: 1, try: 1'."""
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
    """Linie szkieletu jednej funkcji lub metody: dekoratory, sygnatura, pierwszy akapit docstringu."""
    lines = [f"{indent}@{ast.unparse(decorator)}" for decorator in node.decorator_list]

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    lines.append(f"{indent}{prefix} {node.name}({ast.unparse(node.args)}){returns}  {line_range(node)}")

    doc = first_paragraph(ast.get_docstring(node))
    if doc:
        lines.append(f"{indent}    {doc}")
    return lines


def format_class(node: ast.ClassDef, indent: str) -> list[str]:
    """Linie szkieletu klasy: nagłówek z klasami bazowymi, docstring, stałe, metody, klasy zagnieżdżone."""
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
    """Szkielet całego modułu: rozmiar, docstring, stałe, zmienne, kod poza funkcjami, klasy i funkcje."""
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


# --- Technologia ---


class PythonTechnology(Technology):
    """Projekty w Pythonie."""

    name = "python"

    def outline(self, root: str, path: str) -> str:
        """Szkielet pliku .py; pusty string, gdy pliku nie da się sparsować (np. błąd składni)."""
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


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3:
        root, path = sys.argv[1], sys.argv[2]
    else:
        root, path = os.getcwd(), os.path.join("doc_agents", "technologies", "base.py")

    print(f"Szkielet: {os.path.join(os.path.abspath(root), path)}\n")
    print(PythonTechnology().outline(root, path))
