# Nowe funkcje — Infinity Arcade (fork `soulafein83/infinity-arcade`)

> Kontynuacja po `plan.md` (§1–8 wykonane). Dokument **propozycji**; §1
> jest już zrealizowany, pozostałe punkty oczekują na wdrożenie.
>
> Zasady forka bez zmian: aplikacja nie startuje Lemonade Servera, nie pobiera
> modeli; komunikacja z własnym serwerem (`LEMONADE_URL`, domyślnie
> `127.0.0.1:13305`). Każda funkcja: implementacja + testy jednostkowe +
> aktualizacja `README.md` (jeśli user-facing) + commit + push na `fork main`.
>
> Prioritety: 🔴 wysokie (duża wartość „wow" / stabilność), 🟡 średnie (UX),
> 🟢 niskie (porządek, przyszłość).

---

## 1. Podgląd gry: zrzuty ekranu (thumbnails) 🔴 ✅

**Problem:** karta gry w UI to tylko tytuł + tekst — nie widać, jak gra
wygląda. Użytkownik musi ją uruchomić, żeby sprawdzić, czy model nie
„narysował” czarnego ekranu.

**Propozycja:**
- Prompty `create`/`remix`/`debug` otrzymują nową, obowiązkową sekcję:
  gra musi obsłuwać argument CLI `--screenshot <sekundy>` — w tym trybie gra
  uruchamia się headless (`SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`),
  gra podaną liczbę sekund i wychodzi kodem 0. Zero iniekcji kodu w plik
  gry — to czysta zmiana promptu (model sam dodaje ten blok), więc auto-fix
  i remixy działają tak jak dziś.
- `game_launcher.py`: nowa metoda `capture_screenshot(game_id, seconds=3)` —
  start procesu z dummy driverem + `--screenshot`, po zakończeniu wywołuje
  hook zapisu: plik gry otrzymuje jeszcze argument `--screenshot-file <path>`,
  a gra zapisuje `pygame.image.save(screen, path)` na wyjściu (też prompt).
- Po każdym skutecznym `create`/`remix`/auto-fix launcher sam generuje
  `~/.infinity-arcade/previews/{game_id}.png` (1-2 klatki).
- UI: karta gry pokazuje miniaturkę; kliknięcie otwiera pełny podgląd w
  modalu (jak viewer kodu).
- Degradacja: jeśli gra nie ma wsparcia `--screenshot` (np. stare gry z
  przed-wdrożeniem), karta pokazuje placeholder — funkcja nigdy nie blokuje
  generowania.

**Zależności:** tylko `pygame` (już wymagany). Bez nowych pakietów.

**Testy:**
- jednostkowe: `capture_screenshot` z mockowanym procesem (kody 0/niestandardowe,
  timeout); parse argumentów CLI;
- integracyjny (lokalnie, poza CI): wygenerowana gra z `--screenshot 3`
  faktycznie tworzy PNG.

**Env:** `INFINITY_ARCADE_SCREESHOT_SECONDS` (domyślnie 3),
`INFINITY_ARCADE_SCREESHOTS=0/1` (wyłącznik, domyślnie 1).

**Wykonanie:**
- `SCREENSHOT_MODE_INSTRUCTION` (`llm_service.py`) — obowiązkowy blok
  `--screenshot <sekundy>` + `--screenshot-file <path>` doklejony do
  promptów `create` i `remix`; prompt `debug` dostał tylko regułę 5
  („zachowaj obsługę `--screenshot`, jeśli jest”), więc auto-fix nie psuje
  wsparcia. Zero iniekcji kodu — czysta zmiana promptu.
- `GameLauncher.capture_screenshot(game_file, dest_path, seconds) ->
  (bool, str)` (`game_launcher.py`) — `subprocess.run` z dummy driverami
  (`SDL_VIDEODRIVER`/`SDL_AUDIODRIVER=dummy`), timeout `max(seconds, 1) + 60`,
  `--screenshot-file` wskazuje docelową ścieżkę; porażka (timeout, exit ≠ 0,
  brak PNG) → `(False, message)`. `get_preview_path(game_id)` →
  `~/.infinity-arcade/previews/{game_id}.png`.
- `GameOrchestrator.launch_game_with_auto_fix_streaming(...,
  capture_preview=...)` — po sukcesie startu (create/remix/auto-fix)
  przechwycenie zrzutu w `asyncio.to_thread` (pętla zdarzeń nie blokowana);
  sukces → `metadata["has_preview"] = True` + `save_metadata()`; nieudane
  przechwycenie nigdy nie blokuje flow. Obie flusy (create i remix) wywołują
  z `capture_preview=True`.
- `main.py`: parsery `parse_screenshot_seconds` (1..60, domyślnie 3) i
  `parse_screenshots_enabled` (domyślnie włączone; 0/false/no/off wyłącza),
  endpoint `GET /api/game-preview/{game_id}` (404: brak gry / brak podglądu,
  200: `FileResponse` PNG).
- `ArcadeGames.delete_game` usuwa też plik podglądu (`previews/` w pętli
  cleanup).
- UI: `.game-thumb` na każdej karcie (`onerror` → placeholder 🎮), klik
  otwiera pełny podgląd w modalu `#previewViewer` (Escape/backdrop zamyka);
  klik w miniaturkę nie uruchamia gry.
- Testy: 35 nowych jednostkowych — `test/game_launcher_unit.py` (nowy),
  `test/game_orchestrator_unit.py` (nowy), rozszerzone
  `test/llm_service_unit.py` (prompty) i `test/main_unit.py` (parsery +
  endpoint). Integracyjny test żywego `--screenshot 3` pozostaje opcjonalny
  (poza CI, na własnym Lemonade Serverze).

**Env (finalne nazwy — w propozycji był literówka `SCREESHOT`):**
`INFINITY_ARCADE_SCREENSHOT_SECONDS` (domyślnie 3, clamp 1..60),
`INFINITY_ARCADE_SCREENSHOTS` (domyślnie `1`; `0`/`false`/`no`/`off` wyłącza).

---

## 2. Gate jakości: headless smoke test przed zapisem 🔴

**Problem:** auto-fix działa tylko na błędy w pierwszych ~2 s po starcie.
Gra, która wygeneruje się poprawnie, a rozsypie się po 30 s gameplayu
(błędy w pętli, dzielenie przez zero, pamięć), jest zapisywana bez żadnej
weryfikacji — użytkownik dowiaduje się dopiero, gdy zagra.

**Propozycja:**
- Po wygenerowaniu/remiksie/fixie, **przed** ostatecznym zapisem:
  `launch_game_process` headless (`SDL_VIDEODRIVER=dummy`) z wymuszonym
  autostopem po N sekundach (`INFINITY_ARCADE_SMOKE_SECONDS`, domyślnie 10,
  realizowane tym samym `--screenshot`-owym blokiem z pkt 1 lub osobnym
  `--smoke-test <sekundy>`).
- Kod wyjścia ≠ 0 albo pojawienie się `Traceback` w stderr → gra nie jest
  zapisana jako gotowa: auto-fix dostaje pełny stderr z smoke testu (nie
  tylko „2 s od startu"), z limitem prób z `INFINITY_ARCADE_MAX_RETRIES`.
- Wynik smoke testu trafia do `metadata.json` (`"smoke_test": "pass"|"fail"`,
  `"smoke_test_at": ...`) — UI może oznaczać gry `⚠ smoke fail` (zapisane mimo
  niepowodzenia, po wyczerpaniu retry).
- To też daje darmowy „screen-recording” do pkt 1 (klatki z końca smoke testu).

**Zależności:** pkt 1 (argument headless) — realizować **1 → 2** w tej kolejności.

**Testy:** jednostkowe: klasyfikacja wyniku (exit code, traceback w logu,
timeout); mockowany launcher; integracyjny lokalny: celowo zepsuty
`1/0` przechodzi przez cały cykl fixów.

---

## 3. Czat z grą: wielokrotne doszlifowanie w wątku 🟡

**Problem:** remix to zawsze „jednostrzałowy" nowy plik — nie ma rozmowy z
modelem nad jedną grą. Każda kolejna zmiana wymaga wybrania remiksu i
powtórnego opisu; kontekst wcześniejszych zmian ginie (chociaż linia
rodowodu istnieje).

**Propozycja:**
- Na karcie gry panel „Refine chat" — użytkownik pisze np. „dodaj cząsteczki
  przy trafieniu", model dostaje **bieżący kod + historię dotychczasowych
  poleceń w wątku** (ostatnie K wpisów, `INFINITY_ARCADE_CHAT_HISTORY`,
  domyślnie 5) i zwraca nowy kod.
- Server-side: endpointy `POST /api/refine-game/{game_id}` (streaming SSE jak
  remix) + `GET /api/refine-history/{game_id}`; historia w
  `metadata.json` (`"refine_history": [{"prompt": ..., "at": ...}]`) —
  każdy wpis = nowa wersja w istniejącej linii (wzrost `version`,
  `parent_game_id` = poprzedni element).
- UI: chat nad karta gry; po każdej udanej iteracji linia wersji i
  thumbnail (pkt 1) się odświeżają.
- Bez nowych modeli — ten sam `LEMONADE_MODEL_*`; koszt = jedna rozmowa
  streamingowa na wiadomość.

**Testy:** jednostkowe: budowanie promptu z historią (przycinanie do K,
pusta historia), zapis historii w metadata, numeracja wersji; test SSE
jak w `test/main_unit.py`.

---

## 4. Diff między wersjami (linie rodowodu) 🟡

**Problem:** linia `parent_game_id`/`version` jest klikalna, ale użytkownik
nie widzi **czego** dotyczyła zmiana — ma tylko dwa pliki `.py`.

**Propozycja:**
- `GET /api/game-diff/{game_id}?from={parent_id}` zwraca unified diff
  (`difflib.unified_diff`, bez nowych zależności).
- UI: w modalu kodu, gdy gra ma rodzica, zakładka „Changes" — render diffu
  z kolorowaniem wierszy (+zielone/−czerwone), przycisk „Copy".
- Bonus: w linii rodowodu na karcie gry pokazać liczbę zmian per skok
  (`+12 −3`), liczona serwerowo w `/api/games`.

**Testy:** jednostkowe: diff pusty (identyczne pliki), diff jednej linii,
grawnice (brak rodzica, rodzic wbudowany — builtin nie ma diffu), format
JSON.

---

## 5. Oceny, tagi i wyszukiwarka 🟡

**Problem:** biblioteka rośnie liniowo; po 30 grach znalezienie „tej
strzelanki z kosmicznym psem" to przewijanie kart.

**Propozycja:**
- `metadata.json` += `"rating": 0-5`, `"tags": [...]`, `"description": ...`.
- `description` + `tags` generowane LLM-em raz po `create` (tani request
  bez kodu, `max_tokens` ~120, bez thinking) — użytkownik może edytować
  w UI; remix dziedziczy tagi rodzica i LLM je uaktualnia.
- UI: pole wyszukiwarki (tytuł/tag/opis/prompt, `GET /api/games?q=`),
  gwiazdki na karcie (klik = ocena, `PUT /api/game-rating/{game_id}`),
  sortowanie (najnowsze / najlepsze / nazwa), filtr tagów.
- Dalsza perspektywa (poza tym punktem): prompt „remix" może dostawać
  tagi rodzica, żeby LLM rozumiał gatunek bez ponownego opisu.

**Testy:** jednostkowe: filtr `q=` (case-insensitive, tagi, pusty q),
clamp oceny 0–5, dziedziczenie tagów w remixu, formatowanie JSON.

---

## 6. Wydarzenia na żywo (SSE) 🟡

**Problem:** UI pyta `/api/game-status/{game_id}` cyklicznie; śmierć gry
pomiędzy pytaniami jest widoczna dopiero przy następnej odpytce (zależy od
tempa pollingu), a karta pokazuje „RUNNING" przez niepotrzebne sekundy.

**Propozycja:**
- `GET /api/events` — jeden strumień SSE dla całego UI:
  `game_finished {game_id, exit_code}`, `game_error {game_id, last_line}`,
  `game_saved {game_id}` (po create/remix/fix), `smoke_result {game_id}`.
- Emitowane z istniejącej maszynerii: `cleanup_finished_games` (middleware)
  już wykrywa zgony — tylko trzeba z nich pisać w kolejkę; front
  podłącza `EventSource`, przerywa polling statusu dla gier „na żywo".
- Bez WebSocketa (SSE jest prostsze, jednon kierunkowe i wystarczające;
  FastAPI ma to natywnie).
- Degradacja: klient bez `EventSource` (stare przeglądarki) zostaje na
  polingu — zero ryzyka.

**Testy:** jednostkowe: kolejka zdarzeń (dodaj, konsumuj, race cleanup),
test endpointu SSE jak istniejące testy streamingowe; test, że middleware
emituje `game_finished` dokładnie raz na proces.

---

## 7. Eksport / import gry 🟢

**Problem:** biblioteka jest lokalna — nie ma sposobu, żeby podzielić się
grą z innym użytkownikiem forka.

**Propozycja:**
- `GET /api/export-game/{game_id}` → plik `.iarc.json`
  (kod, metadata, linia rodowodu, screenshot z pkt 1 jeśli jest).
- `POST /api/import-game` (upload `.iarc.json`) → nowy `game_id`,
  `parent_game_id = null`, wersja 1, zachowane tagi/opis (pkt 5).
- UI: na karcie „Export", na liście „Import"; walidacja schematu JSON
  server-side, bezpieczny zapis (kod nie jest wykonywany przy imporcie —
  tylko plik `.py`).
- Format wersjonowany (`"format": 1`) — przyszłe zmiany formatu nie łamią
  starych plików.

**Testy:** jednostkowe: round-trip export/import, złe JSON (brak kluczy,
zły typ, nadmiarowy rozmiar), kolizje nazw (nowy game_id zawsze świeży),
import gry z linią rodzica (linia nie jest „przenoszona" — celowo).

---

## 8. Profile modeli 🟢

**Problem:** konfiguracja przez env vars jest świetna do skryptów, ale
użytkownik, który ma na serwerze 3 modele (mały szybki, średni,
high-end), musi restartować aplikację z innymi zmiennymi, żeby
przełączyć „tryb".

**Propozycja:**
- `~/.infinity-arcade/profiles.json`:
  `{ "profiles": { "fast": {"model": "Qwen3.5-9B"}, "quality":
  {"model": "Qwen3-Coder-30B", "thinking": true}, ... }, "active": "fast" }`.
- CLI: `infinity-arcade --profile quality`; UI (pkt 5, pasek): wybór
  profilu na żywo — zmienia tylko `LEMONADE_MODEL_*`/thinking dla
  **następnych** generacji (uruchomione gry nie są ruszane).
- Env vars wciąż mają pierwszeństwo nad profilem (porządek: env > profil >
  domyślne); profil edytowany plikiem, nie UI (UI tylko wybiera) — mniej
  powierzchni ataku.
- Ładnie się składa z §5 plan.md (env vars) — profil to warstwa na nich.

**Testy:** jednostkowe: parsowanie profili (pusty plik, brak klucza
`active`, nieznany model — fallback), kolejność priorytetów env > profil >
default, zmiana profilu nie dotyka uruchomionych procesów.

---

## 9. Statystyki biblioteki 🟢

**Problem:** brak wglądu w zużycie: ile gier wygenerowanych, które linie
najczęściej remiksowane, ile auto-fixów przeszło.

**Propozycja:**
- `metadata.json` += pola licznikowe przy operacjach: `"fixes_applied": n`,
  `"remix_count"` (liczba dzieci w linii).
- `GET /api/stats` → agregat: liczba gier, linie (średnia długość),
  gry z ocenami, gry `smoke fail`, tagi top-10, ostatnie 10 operacji.
- UI: sekcja „Library stats" na dole strony (statyczne, bez graf —
  `INFINITY_ARCADE_STATS=0/1` do ukrycia).
- Opcjonalnie (poza tym punktem): licznik tokenów z odpowiedzi LLM
  (`usage` w streamie, jeśli model/server go daje) zapisany per gra.

**Testy:** jednostkowe: agregacje na fikcyjnym metadata (pusta biblioteka,
jedna gra, linie 5-wersyjna), `remix_count` po remixu, format JSON.

---

## Proponowana kolejność realizacji

1. **1** (thumbnails) — największy efekt „wow" na karcie gry, fundament
   dla 2.
2. **2** (smoke test) — bezpośrednio korzysta z `--screenshot` headless
   z pkt 1; realnie zmniejsza liczbę zepsutych gier.
3. **6** (SSE) — tanie, natychmiast odczuwalne w UI (karty reagują na
   śmierć gry w <1 s), i daje kanał do emitowania wyników z pkt 2.
4. **4** (diff) — mały, czysto lokalny, od razu pokazuje wartość linii
   rodowodu.
5. **3** (czat z grą) — największy feature UX; potrzebuje SSE (6) do
   świeżych statusów, ale nie blokuje się na nim.
6. **5** (oceny/tagi/wyszukiwarka) — skaluje się z biblioteką; dobrze po
   3 (tagi rodzica trafiają w czat).
7. **7** (eksport/import) — zamknika „udostępnianie".
8. **8** (profile modeli) — wygodne, ale nie pilne (env vars działają).
9. **9** (statystyki) — na koniec, zbiera dane z wcześniej wdrożonych
   funkcji.
