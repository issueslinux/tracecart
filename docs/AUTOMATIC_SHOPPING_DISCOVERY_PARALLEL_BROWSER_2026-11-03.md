# TraceCart: automatyczne wykrywanie ofert → równoległa weryfikacja w Chromium

**Stan wdrożenia: 2026-11-03; badania i osobny serwer testowy, bez produkcji.**

## Jaki problem rozwiązujemy

Nowo dodany produkt, np. Ryobi R18PI-0, przechodził tylko
analizę katalogową, ponieważ serwer testowy nie miał skonfigurowanego
klucza `SERPAPI_API_KEY`. To nie jest sytuacja „na rynku nie ma ofert”.
Bez dostawcy wyszukiwania TraceCart **nie wykonał indeksowania sklepów**.

Browser Companion *nie jest wyszukiwarką*: otwiera już znalezione,
konkretne adresy sklepów po zezwoleniu użytkownika na daną domenę.
Oddzielamy więc dwie fazy:

1. **Discovery** — SerpAPI Google Shopping szuka dozwolonych kandydatów
   dla każdego **nowego** produktu. Karty Google Shopping i bezpośrednie
   adresy sprzedawców pozostają oddzielne. Rekord nie potwierdza ceny.
2. **Verification** — po jednorazowym włączeniu
   **Enable automatic seller checks** na `/research/companion`,
   TraceCart **sam** kolejkuje adres produktu wejściowego oraz
   znalezione bezpośrednie adresy sklepów (łącznie do 12). Nie jest
   wymagane osobne klikanie przy każdym nowym badaniu. Dla wcześniej
   utworzonych badań pozostaje przycisk ręcznego ponowienia.
   Rozszerzenie MV3 odwiedza do **trzech domenowych kart
   Chromium równocześnie**, pod warunkiem osobnego uprawnienia na host.
   Każdy odczyt zwraca własny status, cenę deklarowaną, SKU i źródło.
   Karty Google Shopping bez docelowego URL **nie są odwiedzane**.
3. **Graph update** — źródło Browser Companion podpinane jest do
   **tej konkretnej oferty indeksowej**, nie tylko do wejściowego
   produktu. Widać obok siebie: cenę starego indeksu, zadeklarowaną
   cenę nowego odczytu oraz ewentualną rozbieżność/konflikt wariantu.
   `checkout_verified=false` pozostaje obowiązkowo.
   CAPTCHA, 403, odrzucenie uprawnienia i zmiana URL tworzą jawne
   statusy, nie pozorne ceny.

   W przeglądarce analizowane są również **jawne teksty promocji z
   kodem** w widocznych, ograniczonych widgetach ceny produktu,
   niezależnie od ceny JSON-LD `Product/Offer`. Jeśli rozpoznano
   jednoznaczną niższą kwotę i jej kod, TraceCart zapisuje dwa pola:
   `listed_price` oraz `conditional_coupon_price` z kodem, datą
   ważności (jeśli jednoznaczna) i źródłem. Przykład testowy:
   `3499.99 PLN` standardowo oraz `2799.00 PLN` z kodem
   `BW1610-0112`. To **generyczna reguła**, bez wpisywania domen,
   cen ani kodów konkretnego sklepu do logiki ekstrakcji.
   Nie sprawdza zastosowania kuponu przy kasie, więc oba pola
   pozostają `checkout_verified=false`. Niejednoznaczne lub
   ukryte komunikaty promocyjne są odrzucane.

## Wyszukiwarka dla nowych produktów

**http://127.0.0.1:8810/research/shopping** — testowo na
`hexagony-01`; w innych instalacjach użyj portu aplikacji.

**Ważne — wykorzystujemy już istniejący klucz użytkownika.**
Na hexagony-01 klucz jest w
`/home/daniel/.config/tracecart/serpapi.env`, uprawnienia `0600`.
TraceCart sam czyta `SERPAPI_API_KEY=...` z tego pliku — **nie trzeba**
wcześniej wykonywać `source` ani ponownie wprowadzać klucza.
Kolejność źródeł: proces `SERPAPI_API_KEY`, lokalny plik
`<DB>.serpapi.key`, następnie plik
`~/.config/tracecart/serpapi.env`. Nie uruchamiamy powłoki
do odczytania konfiguracji. Uprawnienia i właściciel pliku są
sprawdzane; rzeczywisty klucz nie trafia do HTML, rozszerzenia,
Git ani logów aplikacji. Można wyłączyć dostawcę osobno dla
testowej bazy bez modyfikowania współdzielonego pliku.

Formularz pozwala również ręcznie zapisać **inny** klucz do
lokalnego pliku `<DB>.serpapi.key` (0600), jeżeli zachodzi taka potrzeba.
Klucz z otoczenia procesu ma pierwszeństwo.

**Wynik rzeczywistej próby na Ryobi (2026-11-03):**
Istniejące badanie `JaG4WH8LPnEyDMIrNg7Et48Z` na porcie `8810`
po ponownym uruchomieniu serwera i odczytaniu dotychczasowego klucza
przeszło ponowną fazę Shopping discovery: **2 rzeczywiste
wywołania SerpAPI, 4 bezpośrednie oferty sklepowe oraz 12 kart
Google Shopping**. Ceny indeksowe: Allegro 197,90 PLN, Media
Expert 243,71 PLN, RYOBI 249,99 PLN, JULA 259,00 PLN.
Badanie ma teraz **17 ofert w grafie** łącznie z wejściową.
Wyniki indeksowe są niezweryfikowane w koszyku. Nie użyto
fikcyjnych kandydatów ani nie zmodyfikowano produkcji.

Po włączeniu i dodaniu kolejnego produktu wyszukiwanie wystartuje
**automatycznie** w tle. Maksymalnie **2 wywołania SerpAPI na produkt**,
z ograniczeniem do **24 zarezerwowanych wywołań dziennie** na bazę.
Wynik indeksu nadal nie stanowi dowodu ceny checkout. Limity
mogą wyczerpać pulę w posiadanym planie API — sprawdź rozliczenie
dostawcy przed włączeniem. TraceCart nigdy nie wywołuje płatnego
API bez podanego klucza.

Dla produktu dodanego wcześniej, np. Ryobi R18PI-0, pojawił się
przycisk **Search / refresh alternative offers**. Po skonfigurowaniu
dostawcy uruchamia samą fazę wyszukiwania na zapisanym produkcie;
nie powtarza całej wcześniejszej analizy LLM ani importu katalogu.
Wyniki są zapisane w tym samym badaniu, a stary werdykt jest
oznaczony jako nieaktualny względem nowych ofert.
Jeśli dostawca nie jest skonfigurowany, graf jawnie pokazuje
**No competitor search was performed**, a przycisk wskazuje konfigurację.

## Test na zapisanych danych Lenovo

Osobna instancja testowa (produkcyjny port 8781 nietknięty):

`http://127.0.0.1:8810/cart/status/w8MOeW8uE7pCqDYKf48-lXxy`

Wczytano **kopię zapisanych wyników indeksu**, nie wykonując
nowego wywołania SerpAPI:
- 3 bezpośrednie sklepy: Media Expert, Electro.pl, eLenovo.pl.
- 12 kart Google Shopping **bez** bezpośrednich URL.
- 3 konkretne oferty trafiły do rzeczywistej lokalnej kolejki
  po kliknięciu przycisku, a nie na stronę Google Shopping.

Testy integracyjne HTTP sprawdziły pobranie z kolejki, aktualizację
statusów, cenę starego indeksu kontra dane źródła, utrwalenie
zakończonych obserwacji, konflikt wariantów, odmowę dostępu i
ręczną ponowną próbę nieudanych stron. Test Node zweryfikował
rzeczywiste równoczesne otwarcie maksymalnie trzech kart w workerze,
bez dodatkowych uprawnień do sklepów.

Zewnętrzny zwykły HTTP dla tych trzech adresów zwrócił dwa
`ACCESS_DENIED` oraz jeden konflikt tożsamości. To nie jest
dowód, że Chrom(ium) da radę odczytać strony. Nie próbujemy
omijać ograniczeń ani CAPTCHA.

## Krytyczne zastrzeżenia

- Bez źródła `discovery` nie będzie automatycznych alternatyw
  dla **nowego** produktu. Nie myl „nie szukano” z „nie znaleziono”.
- Wyszukiwanie oferuje kandydatów, ale **samo nie potwierdza wariantu**.
  Google Shopping może pokazać ratę, miesięczną opłatę, inny
  procesor/pojemność lub wyprzedaż. Przeglądarka ma skonfrontować
  ofertę z rzeczywistą stroną, a przy konflikcie zatrzymać przypisanie
  ceny do wariantu.
- Nowe wyszukiwanie jest automatyczne po konfiguracji klucza.
  Browser-verification również jest automatyczne dla **kolejnych nowych
  badań** po jednorazowym włączeniu opcji w `/research/companion`.
  Nie wolno automatycznie udzielać rozszerzeniu uprawnień do nowych
  domen: Chromium wymaga jawnej zgody na każdą domenę. Brak zgody
  skutkuje `SITE_PERMISSION_REQUIRED`, a nie obejściem blokady.
- Czasowe limity/przestoje dostawcy nie mogą wymazywać wcześniejszych
  wyników. Stan zadania jest zapisany; nie ma automatycznego
  ponawiania płatnych wywołań.
- Brak potwierdzenia ceny końcowej, dostawy, magazynu lub płatności.
- Instalacja testowa nie jest produkcją. NIE restartować ani nie
  zmieniać produkcyjnego portu 8781.

## Weryfikacja

```bash
cd /mnt/nvme_fast/tracecart
# Podczas regresji jawnie wyłącz rzeczywistą konfigurację klucza,
# żeby testy nie mogły przypadkowo wykonać płatnych zapytań:
TRACECART_SERPAPI_CONFIG_FILE=/nonexistent/tracecart-test-serpapi.env \
 PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_*.py' -q
node --test browser-extension/*.test.mjs
```

Trwały mechanizm „znajdź → zweryfikuj” jest gotowy do testów
na serwerze lokalnym po skonfigurowaniu dostawcy.
