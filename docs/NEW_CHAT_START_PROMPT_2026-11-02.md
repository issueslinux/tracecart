# TraceCart — polecenie do rozpoczęcia nowego czatu

Poniższy tekst skopiuj **w całości** jako pierwszą wiadomość. Dokument
jest częścią obu repozytoriów i wskazuje trwałą dokumentację projektu.

---

Kontynuuj **samodzielnie** rozwój TraceCart dla PayPal AI Hackathon 2026.

**Repozytoria:** https://github.com/issueslinux/tracecart (główne, publiczne)
oraz https://github.com/issueslinux/hunter (kopia projektu w katalogu
competitions/paypal_ai_2026/tracecart/). Nie zgaduj stanu repozytoriów:
najpierw sprawdź najnowszą gałąź main, PR-y i rzeczywiste pliki.

**Obowiązkowo przeczytaj przed rozpoczęciem:**

1. README.md
2. docs/PROJECT_HANDOFF_2026-11-02.md
3. docs/INTERACTIVE_DECISION_TREE_2026-11-02.md
4. docs/SIMILAR_PRODUCT_TIER_2026-11-02.md
5. examples/live_lenovo_ideapad_index_evidence_2026-11-02.json
6. Otwarte issues TraceCart #38, #43 i #2 oraz Hunter #55.

**Stan na koniec poprzedniego chata:** TraceCart PR #47 i Hunter
PR #144 zostały scalone. Nowy jasny frontend działa jako dynamiczne
drzewo decyzji: produkt → pytania → zmieniające się gałęzie →
**warunkowa** rekomendacja lub wskazanie braku danych. Na hostie
hexagony-01 aktualnie działa
http://127.0.0.1:8781/cart.

Konkretny historyczny wynik użytkownika:
http://127.0.0.1:8781/cart/status/w8MOeW8uE7pCqDYKf48-lXxy.
Dotyczy Lenovo IdeaPad Slim 3 ze Snapdragonem. W oryginalnym raporcie
catalog_alternatives_found = 0 oznacza **zero produktów z katalogu OPF**,
ale faktycznie znaleziono **12 kart Google Shopping, 3 indeksowane
linki do sklepów i 4 wstępnie porównywalne alternatywy**.
Ceny konkurencji potwierdzone u sprzedawców = 0; źródłowej ceny
x-kom nie odczytano, bo HTML przekroczył limit (SOURCE_TOO_LARGE).
Interaktywne drzewo i pełny audyt (/audit) poprawnie rozróżniają
te fakty. Nie traktuj cen 124,95/169,95/399 zł jako rzeczywistych
okazji bez dalszego sprawdzenia.

**Główny kierunek następnych prac:** konkretny, merytoryczny efekt
zakupowo-badawczy, nie nowa kosmetyka frontendu. Zacznij od
**prawdziwych źródeł jakości, zgodności i specyfikacji laptopów**:
porównaj konkretny Lenovo Snapdragon ARM z użyteczną alternatywą
Intel x86. Znajdź wiarygodną dokumentację producenta (rzeczywisty
wariant CPU, RAM, SSD, matryca), a potem **niezależne** testy lub
recenzje dotyczące kompatybilności programów, wydajności, termiki,
baterii i jakości. Nie wymyślaj testów, pomiarów, EAN ani ocen
nieobecnych w źródłach. Dla każdego wyniku zapisz URL, wydawcę,
datę, model/konfigurację, pochodzenie faktu, ograniczenia i konflikty.
Jeśli nie ma niezależnych danych, zachowaj stan NIEZWERYFIKOWANE.

**Ważne:** porównujemy produkty z **podobnej półki funkcjonalnej
i cenowej**, nie tylko identyczny model, ale różnice ARM/x86, OLED/IPS,
akumulatorów, stanu używanego i gwarancji są istotne.
Allegro i Google Shopping mają być uwzględnione poprzez dozwolone
wyszukiwanie i API, także gdy bezpośrednie strony Allegro zwracają
HTTP 403. Nie obchodź zabezpieczeń witryn, nie omijaj robots.txt.
Ceny z indeksu są wskazówkami, nie zatwierdzonymi cenami koszyka.
Odrzucaj podejrzane anomalie i oferty abonamentowe.

**Pilne równoległe kryterium konkursowe:** sprawdź rzeczywisty stan
integracji PayPal Sandbox i wymagania/termin Devpost.
README podaje termin 12 listopada 2026, 21:00 CET; zweryfikuj
regulamin. Jeżeli brak potwierdzonego OAuth, sandbox-order, filmu
lub zgłoszenia, zaplanuj działania z uwzględnieniem tej blokady.
Nie oznaczaj zgłoszenia jako ukończonego bez dowodu, nie uruchamiaj
płatności produkcyjnych i nie automatyzuj zgody kupującego.

**Sposób pracy:** sam wybierz kolejny najwyżej wartościowy etap,
potem analiza → implementacja → testy → prawdziwa weryfikacja →
commit i PR → merge. Preferuj GitHub, **bez GitHub Actions**;
Desktop Commander użyj wyłącznie, gdy potrzebna jest lokalna
weryfikacja. Nie pytaj mnie o potwierdzenie każdego działania.
Nie twórz pustej pętli „mielenia testów”; priorytetem są realne
źródła, porównania i użytkowa jakość decyzji.

**Środowisko:** hexagony-01, Python 3.8.10; checkout kodu
/mnt/nvme_fast/hunter/competitions/paypal_ai_2026/tracecart.
Testy: python3 -m unittest discover -s tests -q
oraz node --test tests/test_decision_flow_logic.cjs;
ostatnio przeszło **369/369 Python, 9/9 Node** plus test Chromium
z przełączaniem gałęzi ARM/x86. Nie powtarzaj kosztownych zapytań
SerpApi bez potrzeby, używaj zapisanych snapshotów. Klucz jest
prywatny w ~/.config/tracecart/serpapi.env — **nie wypisuj ani
nie commituj go**. Nie dotykaj nieśledzonego katalogu
/mnt/nvme_fast/hunter/data/solver-demos/.

**Wynik oczekiwany w tym czacie:** rzeczywisty nowy efekt
merytoryczny w TraceCart, testowany na konkretnym produkcie,
plus zsynchronizowane PR-y i merge w obu repozytoriach oraz
zaktualizowana dokumentacja. Wskaż, co jest potwierdzone, co
pozostaje niepewne, czego jeszcze brak przed konkursem. Raportuj
konkretnie po polsku, nie obiecuj pracy w tle bez uruchomionej
automatyzacji.

---
