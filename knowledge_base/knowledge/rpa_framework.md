# Frameworki RPA - jak je rozpoznać i opisać

> Pierwsza wersja - opis na podstawie robota testowego (Roboforge) i ogólnej wiedzy o REFramework. Do uzupełnienia przez zespół.

## Ukryty przepływ sterowania
Robot oparty na frameworku nie ma pętli głównej we własnym kodzie. Framework sam wywołuje metody robota w ustalonej kolejności.
Dokumentacja musi to powiedzieć wprost - inaczej czytelnik nie znajdzie miejsca, w którym „wszystko się zaczyna”.

## Roboforge (Python)
- Rozpoznanie: importy `roboforge.*`, klasa robota dziedziczy po `_Worker` (`roboforge.processing._worker`), w `main.py` uruchamiany jest `Launcher`.
- Instalowany zwykle jako pakiet (pip) - wtedy jego kodu nie ma w projekcie, widać go tylko w importach (grupa external).
- Metody robota wywoływane przez framework (nie przez kod robota):
  - `initialization()` - raz na początku: logowanie, otwarcie aplikacji, przygotowanie zasobów,
  - `get_data()` - zwraca elementy do przetworzenia (transakcje),
  - `automation_process(transaction_item)` - przetworzenie jednego elementu, wołane dla każdego elementu,
  - `on_error(transaction_item, error_instance)` - reakcja na błąd przy elemencie,
  - `end_process(transaction_data)` - raz na końcu: raport, zamknięcie aplikacji.
- `BusinessRuleException` (`roboforge.processing.exceptions`) oznacza błąd biznesowy - element jest pomijany, robot działa dalej.
- Konfiguracja przez `get_config` (`roboforge.processing.utilities`), zwykle z pliku `config.yml`.

## REFramework (UiPath)
- Rozpoznanie: `Main.xaml` z maszyną stanów, katalog `Framework/` (np. `InitAllSettings.xaml`, `GetTransactionData.xaml`, `SetTransactionStatus.xaml`), konfiguracja w `Data/Config.xlsx`.
- Stany: Init -> Get Transaction Data -> Process Transaction -> End Process; kod procesu jest zwykle w `Process.xaml`.
- Pliki z `Framework/` to szablon - opisujemy tylko zmiany względem szablonu, jeśli są.

## Co analityk ma wskazać
- Które metody lub pliki robota wywołuje framework i w jakiej kolejności.
- Gdzie robot rozróżnia błąd biznesowy od technicznego.
- Czy framework jest pakietem, czy skopiowanym katalogiem (wtedy jego pliki są oznaczone w mapie projektu i nie wymagają analizy).
