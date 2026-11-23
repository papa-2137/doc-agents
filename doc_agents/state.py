"""Stan grafu (DocState): dane, które węzły grafu czytają i uzupełniają w trakcie przebiegu.

Co zawiera: na tym etapie ścieżkę dokumentowanego projektu (wejście grafu) i mapę projektu
(wynik węzła scan). Kolejne kroki dopiszą tu plan, notatki analityków, dokument i uwagi recenzenta.

Jak działa stan w LangGraph: graf zaczyna od słownika podanego w invoke() (tu: tylko project_path).
Każdy węzeł zwraca słownik TYLKO z polami, które zmienia (częściowa aktualizacja), a LangGraph
scala go ze stanem. Pole, którego żaden węzeł jeszcze nie ustawił, po prostu nie występuje w słowniku.

Po co TypedDict, a nie klasa Pydantic: TypedDict to zwykły słownik z opisem pól - podpowiedzi
w edytorze bez walidacji przy każdej aktualizacji; dane od modelu i tak walidują klasy Pydantic
ze schemas.py, które leżą w polach stanu. Stan jest chudy: ścieżki i metadane, bez treści plików.

Moduł zawiera tylko opis typu - nie ma czego testować osobno; stan sprawdza test grafu
(python -m doc_agents.graph).
"""

from typing import TypedDict

from doc_agents.schemas import ProjectMap


class DocState(TypedDict):
    """Stan przebiegu grafu dokumentacji."""

    project_path: str  # ścieżka bezwzględna dokumentowanego projektu (wejście grafu)
    project_map: ProjectMap  # mapa projektu - wynik węzła scan
