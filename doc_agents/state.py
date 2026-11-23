"""Stan grafu (DocState): dane, które węzły grafu czytają i uzupełniają w trakcie przebiegu.

Co zawiera: na tym etapie ścieżkę dokumentowanego projektu (wejście grafu), mapę projektu
(wynik węzła scan), plan (wynik węzła plan), notatki analityków (wynik węzłów analyze), dokument
i listę braków (wynik węzła edit) oraz wynik ostatniej recenzji, licznik recenzji i decyzję, czy pętla
recenzji się zakończyła (wynik węzła review). W pierwszej rundzie redakcji pól recenzji jeszcze nie ma.

Pole notes ma reducer operator.add (zapis Annotated[..., operator.add]): analitycy działają
równolegle i każdy zwraca {"notes": [swoja_notatka]}. Bez reducera kolejne wyniki nadpisywałyby
pole; z reducerem LangGraph dokleja listy do siebie, więc po etapie analizy w notes są wszystkie notatki.

AnalystInput to dane jednego analityka: węzeł analyze nie dostaje całego stanu, tylko słownik
przekazany w Send (krok 30, graph.py) - zadanie z planu, mapę projektu i plan.

Jak działa stan w LangGraph: graf zaczyna od słownika podanego w invoke() (tu: tylko project_path).
Każdy węzeł zwraca słownik TYLKO z polami, które zmienia (częściowa aktualizacja), a LangGraph
scala go ze stanem. Pole, którego żaden węzeł jeszcze nie ustawił, po prostu nie występuje w słowniku.

Po co TypedDict, a nie klasa Pydantic: TypedDict to zwykły słownik z opisem pól - podpowiedzi
w edytorze bez walidacji przy każdej aktualizacji; dane od modelu i tak walidują klasy Pydantic
ze schemas.py, które leżą w polach stanu. Stan jest chudy: ścieżki i metadane, bez treści plików.

Moduł zawiera tylko opis typu - nie ma czego testować osobno; stan sprawdza test grafu
(python -m doc_agents.graph).
"""

import operator
from typing import Annotated, TypedDict

from doc_agents.schemas import AnalysisTask, ModuleNote, Plan, ProjectMap, ReviewResult


class DocState(TypedDict):
    """Stan przebiegu grafu dokumentacji."""

    project_path: str  # ścieżka bezwzględna dokumentowanego projektu (wejście grafu)
    project_map: ProjectMap  # mapa projektu - wynik węzła scan
    plan: Plan  # plan pracy zespołu - wynik węzła plan (agent planner)
    notes: Annotated[list[ModuleNote], operator.add]  # notatki analityków - doklejane z równoległych węzłów analyze
    document: str  # cały dokument w Markdown - wynik węzła edit
    missing: list[str]  # brakujące pola formalne (nazwy) i rozdziały wymagane (tytuły) - wynik węzła edit
    review: ReviewResult  # wynik ostatniej recenzji - wynik węzła review
    review_round: int  # liczba wykonanych recenzji (1, 2, ...) - wynik węzła review
    review_done: bool  # True: dokument zaakceptowany albo osiągnięto limit recenzji - idziemy do finalize


class AnalystInput(TypedDict):
    """Dane jednego analityka, przekazywane do węzła analyze przez Send."""

    task: AnalysisTask  # zadanie z planu: jednostka kodu i wskazówka
    project_map: ProjectMap
    plan: Plan
