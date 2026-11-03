# Test TraceCart teraz: rzeczywista przeglądarka i produkty w interfejsie

**Wykonany test 2026-11-03** na maszynie `hexagony-01`.
Przetestowano aktualny `main` po PR #74:
`1d1413e9845c48b19daa77e5df73db3fd0505b76`.

## Już uruchomione środowisko na hexagony-01

Otwórz bezpośrednio na tej maszynie:

**http://127.0.0.1:8807/research/companion**

Serwer testowy jest podpięty do:

- worktree: `/mnt/nvme_fast/tracecart-quicktest-20261103`
- port: `8807`, **wyłącznie loopback**
- baza: `/tmp/tracecart-quicktest-20261103/demo.sqlite3`
- log: `/tmp/tracecart-quicktest-20261103/server.log`

Działa osobno od portu 8781. Nie korzysta z płatnych wyszukiwarek,
nie wdraża niczego na produkcję i nie zmienia profilu przeglądarki
użytkownika.

W panelu umieszczono **dwa rzeczywiste wyniki przez rzeczywisty
Chromium MV3 service worker**, który użył testowego, tymczasowego
zezwolenia wyłącznie dla odpowiedniej domeny, w jednorazowym profilu:

| Sklep | Produkt | Cena zadeklarowana przez sklep | Metoda |
| --- | --- | --- | --- |
| Adafruit | ADS1015, produkt 1083 | 9.95 USD | DIRECT_OFFER_PRICE |
| Maxpronet | Persil Color 75 prań, 4,5 kg | 78.90 PLN | EXPLICIT_SALE_PRICE_SPECIFICATION |

Oba wyniki mają `USER_BROWSER`, pole `seller_verified=false`,
`checkout_verified=false`, i odsyłacz **Evidence JSON** w tabeli.

**Uwaga:** te ceny nie są zweryfikowaną ceną koszyka, obejmującą
transport, płatności, promocje użytkownika czy dostępność.

## Szybki własny test z dowolnym dozwolonym sklepem

1. W Chromium przejdź do `chrome://extensions`, włącz tryb
   dewelopera, **Load unpacked**, wybierz:
   `/mnt/nvme_fast/tracecart-quicktest-20261103/browser-extension`
2. W panelu `/research/companion` odczytaj lokalny port `8807`
   oraz token parowania. Token **nie jest** przeznaczony do
   przekazywania sklepom, zrzutów ekranu ani commitowania.
3. W panelu rozszerzenia wpisz port i token, kliknij
   **Save local pairing**. Następnie podaj URL konkretnego sklepu,
   kliknij **Grant access to this shop** i zatwierdź jego
   uprawnienie w Chromium. Zaznacz **Enable queued, automatic research**
   i kliknij **Apply / check queue**.
4. Na stronie `/research/companion` wklej jeden lub kilka
   adresów HTTPS (maksymalnie 12) i kliknij
   **Queue selected research pages**. Odśwież panel, a po wykonaniu
   zadania otwórz **Evidence JSON**.

Aby zakończyć: wyłącz kolejkę w rozszerzeniu i/lub użyj
**Revoke access to this shop**. Cofnięcie uprawnienia blokuje
dalszy odczyt danej domeny. Nie kasuje wcześniejszych dowodów.

Odmowa dostępu, CAPTCHA, brak indywidualnej oferty lub niezgodne
dane zwracają jawne statusy. Nie ma obejścia ograniczeń serwisów.

## Odtworzenie testu bez instalowania rozszerzenia w swoim profilu

Jeśli instancja testowa nie działa, można uruchomić ją z repozytorium:

```bash
cd /mnt/nvme_fast/tracecart-quicktest-20261103
TRACECART_SOURCE_SEARCH_ENABLED=0 TRACECART_GRAPHICAL_BROWSER_FALLBACK=0 \
  python3 app.py --port 8807 \
  --db /tmp/tracecart-quicktest-20261103/demo.sqlite3
```

W osobnym terminalu, po uruchomieniu serwera:

```bash
cd /mnt/nvme_fast/tracecart-quicktest-20261103
python3 benchmarks/browser_companion_running_app_demo.py \
  --port 8807 \
  --db /tmp/tracecart-quicktest-20261103/demo.sqlite3 \
  --sites adafruit maxpronet
```

Ten skrypt:

- wymaga **jawnego podania wybranych sklepów**, nie skanuje internetu;
- najpierw sprawdza `robots.txt` i dostępność bezpiecznego HTTPS;
- uruchamia rzeczywiste Chromium i niezmodyfikowaną logikę rozszerzenia,
  w **kopii z testową zgodą na pojedynczą domenę**, nie w profilu
  użytkownika;
- zleca pracę do **aktualnie działającego serwera TraceCart**,
  a nie do fałszywego lub zamockowanego serwera testowego;
- zapisuje otrzymane wyniki do **rzeczywistej kolejki aplikacji**,
  następnie sprawdza je w tym samym panelu HTTP;
- nigdy nie łączy się z produkcyjnym portem 8781.

Kolejka Browser Companion jest aktualnie **w pamięci procesu**.
Po restarcie serwera wyniki tej kolejki znikną; zapisany plik
SQLite pozostaje osobny. Utrwalanie audytu jest kolejnym zadaniem.

## Test i zakres

Test z Adafruit i Maxpronet: **2/2 PASS**, rzeczywisty Chromium MV3,
rzeczywisty serwer TraceCart na `8807`, wyniki widoczne w UI.
Niezależny parser statycznego HTML zgodził się co do cen deklarowanych.
To dwa konkretne publiczne sklepy, nie pomiar skuteczności na
dowolnej stronie.

**Nie uruchamiaj tego skryptu na działającej instancji produkcyjnej**.
