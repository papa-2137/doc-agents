# Zasady pisania dokumentacji

> Pierwsza wersja - do uzupełnienia przez zespół (standard dokumentacji, przykłady dobrych dokumentów).

## Dla kogo piszemy
- Osoba, która przejmuje robota w utrzymanie albo ma go rozbudować - zna Pythona i podstawy RPA, ale nie zna tego projektu.
- Model językowy, który w przyszłości będzie czytał dokumentację, żeby pomóc w zmianach - dlatego nazwy plików, funkcji i parametrów podajemy dokładnie.

## Ton i styl
- Po polsku, rzeczowo, krótkimi zdaniami. Bez marketingu i ogólników („robot usprawnia procesy”).
- Konkret zamiast opisu ogólnego: nazwa pliku, funkcji, parametru konfiguracji, ścieżka.
- Gdy czegoś nie da się ustalić z kodu, piszemy to wprost („nie wynika z kodu”), zamiast zgadywać.

## Poziom szczegółów
- Część formalna: krótko, tylko fakty potrzebne do uruchomienia i utrzymania.
- Część opisowa: tyle szczegółów, ile trzeba, żeby znaleźć przyczynę błędu i bezpiecznie wprowadzić zmianę. Nie przepisujemy kodu - wskazujemy, gdzie co jest.

## Ścieżki procesu (obowiązkowe)
- Każdy dokument opisuje krok po kroku wszystkie ścieżki robota: główną i alternatywne (błąd biznesowy, błąd techniczny, inne rozgałęzienia).
- Kroki to numerowane zdania w języku naturalnym, w kolejności wykonania, z konkretami z kodu: aplikacja, adres strony, przycisk, pole formularza, plik, decyzja, pętla. Np. „3. Robot klika przycisk Start.”

## Wskazówki utrzymaniowe i rozszerzeniowe
- Gdzie robot jest kruchy: selektory elementów na stronach, zależność od wyglądu aplikacji, stałe ścieżki, założenia o formacie danych.
- Co sprawdzić najpierw przy awarii i gdzie są logi.
- Jak dodać nowy krok procesu albo nowy typ danych wejściowych - od którego pliku zacząć.

## Czego nie robimy
- Nie podajemy wartości sekretów (haseł, kluczy, certyfikatów) - tylko nazwy plików i zmiennych środowiskowych.
- Nie opisujemy szczegółowo kodu frameworku - wystarczy, które metody robota framework wywołuje i kiedy.
