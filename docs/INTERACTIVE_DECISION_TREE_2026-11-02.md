> **Historical document:** The former click-through buyer questionnaire was replaced by the [English autonomous evidence path](AUTONOMOUS_EVIDENCE_2026-11-02.md).

# TraceCart — interaktywne drzewo decyzji (2 listopada 2026)

## Diagnoza zadania Lenovo

W badanym istniejącym zadaniu użytkownika (Lenovo IdeaPad Slim 3,
Snapdragon X1-26-100, 16 GB, 512 GB, OLED, adres x-kom) końcowy stary
raport pokazywał niepokojące zera. Te liczniki dotyczą różnych źródeł:

| Źródło danych | Faktyczny wynik |
|---|---:|
| Katalog Open Products Facts (catalog_alternatives_found) | 0 |
| Karty produktów Google Shopping | **12** |
| Indeksowane odnośniki do konkretnych sklepów | **3** |
| Wszystkie zaindeksowane rekordy (3 + 12) | **15** |
| Wstępnie porównywalne konfiguracje laptopów | **4** |
| Skrajnie niskie / warunkowe ceny w indeksie względem grupy | **3** |
| Potwierdzone aktualne ceny zakupu w sklepach | **0** |
| Cena produktu na źródłowej stronie x-kom | **nieodczytana** |

Pierwsze zero jest prawdziwe **wyłącznie dla katalogu OPF**. Nie
oznacza braku ofert w Google Shopping. Pierwotna strona x-kom nie
została przetworzona, ponieważ jej odpowiedź przekroczyła limit
rozmiaru publicznego czytnika (SOURCE_TOO_LARGE). None jest poprawne;
0,00 PLN byłoby błędną informacją. cost_per_wash nie dotyczy laptopa.

Poza numerami modeli i cenami trzeba rozróżnić Snapdragon ARM od
Intel/AMD x86, pamięć, dysk i ekran OLED/IPS. Ocena techniczna jest
oceną zgodności deklaracji z tytułów, **nie testem jakości**.

Źródła z pomiaru, bez kluczy API:
[surowa zredukowana próbka Lenovo](../examples/live_lenovo_ideapad_index_evidence_2026-11-02.json)
oraz
[odtworzona projekcja decyzji](../examples/live_lenovo_ideapad_decision_projection_2026-11-02.json).

## Nowe zachowanie interfejsu

**/cart** — nowa jasna, minimalistyczna strona wejściowa. Jeden adres
HTTPS wystarcza. Po kliknięciu przycisku formularz używa POST/Redirect/GET
(status HTTP 303), co kieruje od razu na indywidualny wynik bez drugiego
kliknięcia i bez duplikowania zadania przy odświeżeniu.

**/cart/status/{id}** — domyślnie dostępny jest dynamicznie rysowany
schemat ze statystykami źródeł i pytaniami. Interfejs automatycznie
odczytuje status zadania; przy PENDING/RUNNING wykonuje tylko odczyt
statusu bez ponownego wyszukiwania, a po READY pokazuje pierwszy węzeł
drzewa. Kliknięcie odpowiedzi rozwija następną gałąź. Można poprawić
poprzednią odpowiedź, co usuwa późniejsze gałęzie i wylicza nowy wynik.

**/cart/status/{id}.decision.json** — mała projekcja danych odczytana
z utrwalonego raportu, bez zmieniania jego SHA-256. Używana przez
interfejs. Rozróżnia OPF, karty Google Shopping, ceny indeksowane i
rzeczywiście zweryfikowane.

**/cart/status/{id}/audit** — zachowany kompletny techniczny raport
z oryginalnym drzewem dowodów i jawnym wyjaśnieniem liczników.
**/cart/status/{id}.json** — niezmieniony utrwalony plik JSON.

## Pytania i decyzje

Dla laptopów drzewo pyta kolejno o zastosowanie (codzienna praca,
programowanie, wymagające aplikacje/gry), priorytet (cena, równowaga,
ekran), potrzebę zgodności x86 vs akceptację ARM oraz deklarację
samodzielnej weryfikacji warunków zakupu.

Odpowiedź ma realny wpływ na wybór:

- Przy wymaganiu x86 alternatywy Snapdragon/ARM nie są rekomendowane
  jako zamienniki. Brak dowodów wydajności GPU powoduje wstrzymanie
  rekomendacji do weryfikacji.
- Priorytet OLED nie może zakończyć się „OLED potwierdzone”, gdy tytuł
  wskazuje IPS lub nie określa technologii ekranu.
- Skrajnie niskie indeksowane ceny i oferty abonamentowe nie zostają
  automatycznym zwycięzcą.
- Brak porównywalnych ofert kończy się jawnym wstrzymaniem decyzji, nie
  wygenerowaniem wymyślonego produktu.
- Odpowiedź „sam sprawdziłem cenę” pozostaje deklaracją użytkownika;
  nie jest źródłową weryfikacją TraceCart.
- **Każda ścieżka kończy się warunkowym wnioskiem lub wstrzymaniem
  zakupu. Żadna nie zleca płatności.**

Nie są to obietnice najniższej ceny. Indeks Google Shopping może
zawierać nieaktualne ceny, raty albo pomyłki. Dla Lenovo z indeksu
pojawiły się m.in. 124,95 PLN i 169,95 PLN oraz 399 PLN przy ofercie
abonamentowej. Bez niezależnego sprawdzenia nie są cenami końcowymi.

## Test na dokładnie istniejącym zadaniu

Przed wdrożeniem wykonano test Chromium 156 na izolowanej kopii
dotychczasowego zadania użytkownika w lokalnej bazie.

1. Ekran startowy wyświetlił nowy formularz i identyfikator zadania.
2. Na stronie wyniku automatycznie pojawił się pierwszy węzeł, liczniki
   **12 / 3 / 0 / 4** i ostrzeżenia o cenach oraz URL-only.
3. Ścieżka programowanie → równowaga → x86 → cena niesprawdzona
   zakończyła się warunkowym kandydatem Intel z indeksu Ceneo,
   **3167 PLN**. Aplikacja wstrzymała rekomendację zakupu.
4. Zmiana odpowiedzi architektury na „ARM akceptowalny” zmieniła
   kandydata na Snapdragon z indeksu Allegro, **2849 PLN**. Zaznaczone
   ręczne sprawdzenie ceny nie zmieniło statusu źródłowego na
   zweryfikowany.
5. Cofnięcie odpowiedzi usunęło następne węzły. Reset przywrócił
   pierwsze pytanie. W przeglądarce nie wystąpiły błędy JavaScript.
6. W żadnej ścieżce nie uruchomiono wyszukiwania ponownie, płatności
   ani modyfikacji raportu historycznego.

Środki bezpieczeństwa: CSS i JS dostępne tylko z własnego origin,
restrykcyjny CSP bez inline JavaScript, brak zewnętrznych bibliotek,
renderowanie danych przez textContent, ograniczenie do bezpiecznych
odnośników HTTPS, brak śledzenia i brak automatycznej autoryzacji.
Dla wyłączonego JavaScript dostępna jest pełna wersja audytu.

Dalszy potrzebny rozwój: niezależne testy urządzeń, wiarygodne parametry
producentów i aktualne ceny sklepów. Nie są udawane w tym module.

## Przekazanie prac

Pełny aktualny status, polecenia uruchamiania, realne blokady
i priorytety: [PROJECT_HANDOFF_2026-11-02](PROJECT_HANDOFF_2026-11-02.md).
Gotowa pierwsza wiadomość nowego czatu:
[NEW_CHAT_START_PROMPT_2026-11-02](NEW_CHAT_START_PROMPT_2026-11-02.md).
