# TraceCart — modalny checkout PayPal Sandbox z istniejących propozycji

Data: 2026-11-04. Zmiana dotyczy **wyłącznie stagingu i ścieżki Sandbox**.

## Zakres

W istniejącym widoku `/cart/status/<research-id>` proponowane produkty
mają przycisk **„Płacę z PayPal”** z widoczną etykietą **SANDBOX**.
Kliknięcie nie przenosi już użytkownika na osobną stronę:
otwiera modal w tym samym widoku nad interaktywnym grafem.

Modal pokazuje cztery etapy:
1. **Produkt** — serwer ponownie odczytuje proponowaną ofertę z aktualnej,
   utrwalonej analizy. Przeglądarka nie przesyła ceny ani sprzedawcy.
2. **Zgoda** — jawne potwierdzenie identycznej kwoty oraz formuły
   `I APPROVE SANDBOX DEMO`.
3. **PayPal** — odrębne kliknięcie tworzy **jedno** zamówienie w rzeczywistym
   PayPal Sandbox API. PayPal-hosted approval otwiera się w osobnym,
   ograniczonym rozmiarem oknie. Trwa obserwacja stanu przez read-only
   GET; gdy popup zostanie zablokowany, dostępny jest bezpośredni link.
4. **Wynik** — po odczytanym potwierdzeniu `APPROVED` modal pokazuje
   jednoznaczny wynik i oznacza kartę produktu jako zatwierdzoną
   **w Sandbox**, bez zmiany wyniku merytorycznego analizy.

Płynne przejścia realizuje `assets/paypal-checkout-modal.js`,
a osobny styl `assets/paypal-checkout-modal.css` nie zmienia
samego grafu. Dane utrwala istniejąca tabela SQLite
`offer_sandbox_orders`. API JSON jest opt-in (`Accept: application/json`);
wszystkie dotychczasowe formularze i adresy URL pozostają aktywne.
Po powrocie PayPal Script `assets/paypal-popup-return.js`
powiadamia okno macierzyste wyłącznie na tym samym origin.

## API i zabezpieczenia

- `POST /cart/status/<job>/paypal/select` — serwerowa selekcja
  zapisanej propozycji; zwraca JSON zamiast 303 tylko gdy przeglądarka
  żąda JSON.
- `POST /cart/sandbox/<quote>/approve` — zapis świadomej zgody.
- `POST /cart/sandbox/<quote>/create` — tylko jednorazowy POST
  do PayPal Sandbox Orders v2, po uprzedniej zgodzie.
- `GET /cart/sandbox/<quote>.json` — wyłącznie bezpieczny stan wyceny.
  Z `?verify=1` wykonywany jest odczyt `GET` istniejącego zamówienia
  w PayPal Sandbox, **nigdy ponowny create ani capture**.
- `/cart/sandbox/<quote>` nadal działa jako strona awaryjna;
  poprzednie zamówienia i zapisy są zachowane.
- Wycena ma 15-minutowy limit na zgodę. Po niepewnym POST stan
  `CREATE_UNCERTAIN` blokuje ponowny create; wyświetlana jest informacja
  o konieczności ręcznego uzgodnienia istniejącego zamówienia.
- Identyfikatory wycen służą do wznowienia modalnego procesu
  w obrębie jednej sesji przeglądarki, więc przypadkowe zamknięcie
  okna nie wywołuje nowego zamówienia.
- Żadne Client ID/Client Secret, idempotency token, sesja kupującego,
  PayerID ani wynik niezależnej analizy nie są zmieniane przez JS.

## Granice demonstracji

**To nie jest rzeczywisty zakup na Allegro, w TIM ani w Media Expert.**
Wybrana cena to cena z indeksu / obserwacji oferty, nie zweryfikowana
kwota końcowa sprzedawcy. PayPal Sandbox Business jest testowym
odbiorcą, a żadna płatność realna nie jest pobierana.

## Testy

- 18 dedykowanych testów Pythona z podwójnym bramkowym OAuth/PayPal
  (bez realnego tworzenia zamówień): PASS.
- Chromium, rzeczywiste dane Ryobi, `offer-1 = 132.60 PLN`:
  otwarcie modalu i zapis zgody: PASS.
- Chromium, całkowicie symulowany PayPal: wynik
  `VERIFIED_APPROVED`, końcowy ekran i paski etapów: PASS.
- PR wcześniejszy #93 dokumentuje **rzeczywiste** zatwierdzenie w
  PayPal Sandbox API, dokonane przed dodaniem niniejszego modalu.
  Nowa warstwa UI nie wymaga kolejnej rzeczywistej transakcji w API.
- Niezależny pełny zestaw testów badawczych może wciąż zawierać
  wcześniejsze awarie związane z timeoutami/asynchronicznością;
  nie przypisuj im automatycznie statusu PASS.
