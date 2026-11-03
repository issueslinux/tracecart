# TraceCart — Browser Companion w głównym grafie koszyka

**Wdrożenie badawcze, 3.11.2026. Nie jest wdrożeniem produkcyjnym.**

## Co zostało połączone

Po zaakceptowaniu wyniku przez **prawdziwe** lokalne API
`POST /api/browser-companion/result`, serwer utrwala ograniczony raport
`USER_BROWSER` w tabeli SQLite `cart_browser_observations`.
Nie zapisuje cookies, HTML strony, kont użytkowników ani tokenów sklepów.
Hash SHA-256 dotyczy **przefiltrowanej projekcji Product/Offer**, nie całej
strony sklepu. Potwierdzenie ceny końcowej pozostaje `false`.

Gdy badanie koszyka dotyczy tego samego **znormalizowanego adresu URL**,
`CartResearchJobs.read()` dobiera maksymalnie dwie ostatnie obserwacje.
Powiązanie jest po oryginalnym adresie produktu, a nie po nazwie sklepu,
podobnym tytule, cenie lub wyniku wyszukiwarki. Dane mogą zostać
zarejestrowane **przed** albo **po** utworzeniu badania koszyka.
Adresy z parametrami mogącymi oznaczać wariant (np.
`?variant=blue`, `?size=L`, `?attribute_pa_color=black`)
**nie są automatycznie łączone z adresem bez tych parametrów**.
Identyfikujący `offerId` musi być poprawny i pozostaje częścią klucza.
Dopuszczone są wyłącznie znane parametry śledzące `utm_*`,
`fbclid`, `gclid` itd.; inne parametry wyłączają automatyczne
powiązanie, aby uniknąć pomylenia wersji produktu. Obserwacja pozostaje
dostępna w osobnym rejestrze przeglądarkowym.

W centralnym grafie pojawiają się:
- węzeł **Browser Product/Offer projection** (`fetched_source`) z
  adresem, czasem odczytu i hashem przefiltrowanych pól;
- wyraźnie oznaczone **Browser declared ...** dla nazwy, marki,
  SKU, GTIN, sprzedawcy, dostępności i deklarowanej ceny;
- powiązania do wybranej oferty i dokumentu;
- odrębny problem weryfikacyjny, gdy istniejące SKU/GTIN są sprzeczne.
  W tym przypadku **cena przeglądarki nie jest przypisywana wariantowi**;
- gdy wcześniejsza cena wejściowa różni się od deklaracji przeglądarki,
  osobny węzeł rozbieżności cen.

Węzły i krawędzie są widoczne w SVG oraz JSON grafu. Lewa kolumna
**Sources** pokazuje zadanie `BROWSER / PAGE CAPTURED`.
Na dole grafu widoczna jest liczba deklaracji przeglądarkowych.
W głównym grafie znajduje się link **Browser capture**, który
automatycznie przenosi URL produktu do formularza kolejki.

**Nie wolno traktować** strony odczytanej przez przeglądarkę jako
niezależnego badania laboratoryjnego, gwarancji aktualnego SKU,
dostępności, dostawy czy potwierdzonej ceny koszyka.
`verified_checkout_prices=0`, `seller_verified=false`,
`checkout_verified=false` pozostają niezmienione.

## Trwałość i ograniczenia

SQLite zapisuje zakończone obserwacje osobno od istniejącej kolejki
`CompanionQueue`. Po restarcie aplikacji:
- zakończone dane oraz ich `Evidence JSON` pozostają widoczne w
  `/research/companion` oraz grafie koszyka;
- zadania oczekujące i będące w trakcie, przechowywane dotąd
  w pamięci RAM, **nie są wznawiane**;
- nie ma automatycznych prób ponawiania odczytu ani zakupów.

To jest celowe ograniczenie pierwszego etapu: brak ponawiania
osieroconych operacji bez ponownego upoważnienia.

## Szybki test na hexagony-01

Z osobnego repozytoryjnego worktree, po aktualizacji `main`:

```bash
python3 app.py --port 8808 --db /tmp/tracecart-browser-graph-20261103/demo.sqlite3
```

Otwórz **http://127.0.0.1:8808/cart** i wprowadź publiczny HTTPS URL
produktu, np. `https://www.adafruit.com/product/1083`.
W grafie kliknij **Browser capture**, co wypełni pole kolejki tym samym URL.

Dalsze kroki dla **ręcznego** rozszerzenia Chromium:
`chrome://extensions` → **Load unpacked**
→ katalog `browser-extension/` aktualnego worktree → lokalne parowanie
na porcie **8808** → **Grant access to this shop** → uruchomienie
kolejki. Źródło powinno pojawić się w grafie i w
`/research/companion`.

Do testów automatycznych nie potrzeba logowania do sklepów. Osobny
skrypt z PR #75 może zlecić odczyt dwóch jawnie wybranych publicznych
sklepów w jednorazowym testowym profilu, bez uprawnień w zwykłym
Chromium. **Nie należy go uruchamiać na produkcyjnym porcie 8781.**

## Przetestowano także na działającym TraceCart

Uruchomiona **osobna instancja badawcza** na hexagony-01:

**http://127.0.0.1:8808**

Źródła zostały ponownie, faktycznie przechwycone przez
rozszerzenie Manifest V3 w izolowanym Chromium, z jawną testową zgodą
tylko na dozwoloną domenę. Wysłano dane przez prawdziwy lokalny HTTP
do bazy i grafu, bez sztucznego dopisywania danych do diagramu.

Działające linki do grafów:

- **Adafruit ADS1015, 9.95 USD:** `http://127.0.0.1:8808/cart/status/0YEozV84jJRfeOYxK-VuD30R`
- **Maxpronet Persil Color 75 prań, 78.90 PLN:** `http://127.0.0.1:8808/cart/status/gAGHnc3ovN_SJUTpHfYRacCM`
- Wyniki z przeglądarki: `http://127.0.0.1:8808/research/companion`.

Wynik HTTP: **2/2 PASS**. Występują węzły źródeł
`USER_BROWSER_FILTERED_PROJECTION`, węzły ceny z metodą deklaracji,
hashe i powiązania do oferty nr 1.
`verified_checkout_prices=0` w obu przypadkach.

Weryfikacja **realnego Chromium i DOM**:
- Adafruit: **17 widocznych węzłów, 30 połączeń**.
- Persil: **14 widocznych węzłów, 24 połączenia**.
- Oba przypadki pokazały `browser declarations (unverified)`,
  źródłowe węzły przeglądarki i poprawny link **Browser capture**.

**Test restartu: 2/2 PASS.** Po zatrzymaniu i ponownym uruchomieniu
badawczego serwera 8808 wykonane obserwacje i węzły grafu
pozostały w SQLite i można je ponownie odczytać. Bez ponownych
zapytań do sklepów.

Skrypt do powtórzenia testu widoku bez logowania do sklepów:

```bash
python3 benchmarks/browser_companion_cart_graph_ui_smoke.py   --port 8808 --cart-job 0YEozV84jJRfeOYxK-VuD30R
python3 benchmarks/browser_companion_cart_graph_ui_smoke.py   --port 8808 --cart-job gAGHnc3ovN_SJUTpHfYRacCM
```

Skrypt wykonuje jedynie odczyty **lokalnego** serwera, w tym
prawdziwe renderowanie grafu JavaScript w jednorazowym profilu
Chromium. Nie łączy się z produkcją na porcie 8781.
Nie należy utożsamiać 2 przykładów z miarą pokrycia dowolnych
sklepów.

## Testy

```bash
PYTHONPATH=. python3 -m unittest tests.test_browser_cart_graph tests.test_browser_companion_http -v
PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_*.py' -q
node --test browser-extension/*.test.mjs
```

Kluczowe kontrakty: brak przypisania do innego produktu z tej samej
domeny, brak promocji ceny do potwierdzonego checkout, blokada ceny
przy konflikcie SKU/GTIN, sygnalizacja aktualizacji aktywnego grafu,
trwałość SQLite i odczyt wyników po wyzerowaniu kolejki.

Następne zadania: więcej rzeczywistych sklepów w benchmarku,
trwała kolejka ze stanami `INTERRUPTED` i audytem zgód,
weryfikacja konkretnego wariantu przez dodatkowe identyfikatory,
wycena dostawy i dopiero potem ewentualna integracja checkout.
