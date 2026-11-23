# Konwencje projektów RPA w Pythonie

> Pierwsza wersja - ogólne dobre praktyki. Do zastąpienia konwencjami zespołu.

## Struktura projektu
- Punkt wejścia w `main.py` w katalogu głównym; logika w pakiecie (np. `src/`), podzielona na moduły według odpowiedzialności: obsługa stron lub aplikacji, odczyt danych, raport, logowanie.
- Obsługa każdej strony lub aplikacji w osobnym module lub klasie (wzorzec page object) - selektory w jednym miejscu.
- Konfiguracja w pliku (`config.yml`, `.json`), nie w kodzie; dane wejściowe i wyniki w osobnych katalogach (np. `resources/in`, `resources/out`).

## Konfiguracja i sekrety
- Hasła i klucze tylko w zmiennych środowiskowych albo magazynie poświadczeń; w configu sama nazwa zmiennej (np. `password_env`).
- Odstępstwo do opisania: hasło wpisane w kod lub w config, certyfikat w repozytorium.

## Logowanie i obsługa błędów
- Logowanie przez moduł `logging` (albo logger frameworku) - z informacją, który element jest przetwarzany.
- Rozróżnienie błędów biznesowych (zły element danych - pomijamy i raportujemy) od technicznych (awaria systemu - ponowienie lub zatrzymanie).
- Odstępstwo do opisania: puste `except`, połykanie wyjątków, brak logu przy błędzie.

## Co analityk ma wskazać
- Gdzie projekt trzyma się tych zasad, a gdzie od nich odstępuje - odstępstwa to ważne wskazówki utrzymaniowe.
- Stałe ścieżki, opóźnienia na sztywno (`time.sleep`), selektory zależne od wyglądu strony.
