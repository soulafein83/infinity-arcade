# Plan ulepszeń — Infinity Arcade (fork `soulafein83/infinity-arcade`)

> Stan: **wykonano 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4, 5, 6, 7, 8** (commity Partii A–D + 3.2 + 4 + 2.2 + 6 + 2.5 + 7 + 8), reszta: propozycje.
> Prioritety: 🔴 wysokie (wpływ na stabilność/jakość gier), 🟡 średnie (UX/komfort), 🟢 niskie (porządek, przyszłość).
>
> Zasady forka: rozwijany oddzielnie od upstreamu (`lemonade-sdk/infinity-arcade`),
> praca wyłącznie na forku, własny Lemonade Server (127.0.0.1:13305) — aplikacja
> **nie uruchamia serwera** i nie pobiera modeli samodzielnie.

---

## 1. Cykl życia procesów gier 🔴

### 1.1. Obsługa SIGTERM w aplikacji ✅
**Problem:** `main()` czyści uruchomione gry tylko przy `KeyboardInterrupt` (Ctrl+C).
`kill <pid>` (SIGTERM) zabija aplikację, a **dzieci (procesy gier) zostają osierocone** —
stwierdzone empirycznie (gra `a5dc07da` żyła po zamknięciu aplikacji).

**Propozycja:**
- Handler `signal.SIGTERM` wywołujący ten sam cleanup co Ctrl+C (iteracja po
  `game_launcher.running_games` → `stop_game`).
- Dodatkowe zabezpieczenie: w `GameLauncher.launch_game_process` startować grę z
  `start_new_session=True` i w `stop_game` zabijać **grupę procesów**
  (`os.killpg`), żeby nie zostawały wnuki.

### 1.2. Powiadomienie frontendu o zgonie gry ✅
**Problem:** gra może się rozsypać >2 s po starcie (po sprawdzeniu launcher).
Klient dowiaduje się tylko, że status przestał zwracać `running: true`.

**Propozycja:**
- Plik logów (stdout/stderr) każdego procesu gry: `~/.infinity-arcade/logs/{game_id}.log`.
- Endpoint `GET /api/game-log/{game_id}` (ostatnie N linii) + pole „last error” na karcie gry
  w UI; opcjonalnie SSE/WebSocket push przy wykryciu zgonu przez `cleanup_finished_games`.

### 1.3. Endpoint zatrzymania gry ✅
**Problem:** w UI brak sposobu na zamknięcie działającej gry (launcher ma `stop_game`,
ale brak marasy API).

**Propozycja:** `POST /api/stop-game/{game_id}` + przycisk „Stop” na karcie gry.

---

## 2. Jakość generowania kodu przez LLM 🔴

### 2.1. Wykrywanie ucięcia odpowiedzi (finish_reason) ✅
**Problem:** `max_tokens=16000` pomaga, ale jeśli odpowiedź i tak się utnie,
model nie domknie bloku ```python — wyekstrakowany kod jest niekompletny,
a gra dostaje auto-fix, który często nie daje rady.

**Propozycja:** w pętli streamingu (`llm_service.generate_game_code_with_llm`)
sprawdzać `chunk.choices[0].finish_reason`; przy `"length"` wysłać wyraźny błąd
„kod ucięty — zwiększ limit / skróć grę” zamiast cichego auto-fixu.

### 2.2. Oszczędzanie budżetu tokenów (model „thinking") ✅
**Problem:** Qwen 3.5-9B to model z tokenami racjonowania (`reasoning_content`),
które spalone są z `max_tokens` przed właściwym kodem.

**Propozycja:**
- Próbować włączenie trybu bez myślenia w żądaniach generujących kod
  (np. `extra_body={"chat_template_kwargs": {"enable_thinking": false}}` —
  wymaga testu na tym modelu) — więcej miejsca na kod przy tym samym limicie.
- Tytuł: `max_tokens: 800` jest bezpieczne, ale dla non-thinking można spaść do ~100;
  dla thinking zostawić 800 — ustawić świadomie per tryb, nie „na oko”.

**Wykonanie (testy na Qwen3.5-9B-GGUF):**
- zthinking WŁĄCZONY: tytuł spalał całe `max_tokens=800` na myślenie
  (`finish_reason="length"`, pusty `content` → fallback tytułowy);
- zthinking WYŁĄCZONY: tytuł w 4 tokenach („Speed Pong"), kod generuje się
  bez zużycia budżetu na reasoning; parametr działa też w streamingu;
- model bez tej opcji (Gemma-4-E4B) akceptuje parametr bez błędu
  (llama.cpp ignoruje nieznane kwargi) — bezpieczne wysyłać zawsze.
- Implementacja: `no_thinking` w `llm_service.py` (tytuł: `max_tokens` 100
  non-thinking / 800 thinking; kod: `extra_body` z `enable_thinking: false`),
  przełącznik env `INFINITY_ARCADE_THINKING` (domyślnie **off**), testy
  jednostkowe `test/llm_service_unit.py`, test żywy pełnego przepływu
  (create-game na Qwen3.5-9B: tytuł + kompletna gra).

### 2.3. Lepsze prompty (wnioski z sesji z Pongiem) ✅
- **Tryb `create`:** dodać do system promptu sekcję o wymaganej geometrii gry
  (opis ekranu, osi, ścian vs krawędzie punktowe) — zapobiega zamianie osi,
  która kosztowała jeden pełny remix.
- **Tryb `remix`:** jawną instrukcję: „zachowaj bez zmian wszystkie fragmenty
  poza wskazanymi; nie przemieszaj kodu, nie zmieniaj nazw zmiennych bez potrzeby” —
  redukuje regresje (w v2 zniknął poprawiony jitter mimo że nie był celem).
- **Tryb `debug`:** dołączyć do `mode_data` nie tylko błąd, ale ostatnie linie
  stderr gry (z pliku logów z pkt 1.2) — model dostaje pełniejszy kontekst.
- Opcjonalnie: limit wielkości („maks. ~300 linii”) żeby kod mieścił się w budżecie.

### 2.4. Backup przed auto-fixem ✅
**Problem:** auto-fix **nadpisuje** plik gry z tym samym `game_id` — poprzednia
wersja kodu znika.

**Propozycja:** przed zapisaniem `fixed_code` skopiować stary plik do
`~/.infinity-arcade/backups/{game_id}.v{n}.py` (metadane: czas, powód fixa).

### 2.5. Liczba prób auto-fix ✅
`max_retries=1` w `launch_game_endpoint` — dla większego modelu 2 próby bywają
wystarczające, ale kosztują ~2× czas. Propozycja: wartość konfigurowalna
(domyślnie 1), ewentualnie 2 za przełącznikiem.

**Wykonanie:**
- zmienna env `INFINITY_ARCADE_MAX_RETRIES` (domyślnie 1; wartości <1 i
  niepoprawne clampowane/fallback do 1 — `parse_max_retries` w `main.py`),
- wartość czytana przy starcie razem z pozostałymi ustawieniami forka i
  przekazywana do `launch_game_with_auto_fix_streaming`,
- testy jednostkowe `test/main_unit.py` (8 przypadków: brak, pusta, 1, 2,
  białe znaki, 0, ujemna, niepoprawna).

---

## 3. Magazyn gier i wersjonowanie 🟡

### 3.1. Rodowód gier w metadata ✅
**Problem:** remix tworzy nowy `game_id`, ale jedynym śladem pochodzenia jest
tekst w polu `prompt` („Remix of 'Pong Duel v2'"). Trudno wybrać właściwą wersję
do kolejnego remiksu (stąd reguła „remiksuj od najnowszej”).

**Propozycja:** pola `"parent_game_id"` i `"version"` w `metadata.json`;
UI pokazuje drzewo/łańcuch wersji; remix domyślnie z najnowszej wersji łańcucha.

### 3.2. Porządki ✅
- `DELETE /api/delete-game` nie czyszczy backupów (po 2.4) ani logów — dodać.
- `metadata.json` zapisywany bez blokady/atomarnie — przy większej liczbie gier
  napisać atomarnie (tmp + `os.replace`).

---

## 4. Frontend / UX 🟡 ✅

- Karta gry: wskaźnik „działa” (badge `● RUNNING`) + przycisk Stop (z pkt 1.3)
  + „ostatni błąd”.
- Widok kodu źródłowego w przeglądarce: endpoint `GET /api/game-source/{game_id}`
  + modal `#codeViewer` (Copy, zamknięcie Esc/kliknięcie tła); pozostaje też
  „Open Python File”.
- Historia remiksów danej gry na karcie (z pkt 3.1): klikalny łańcuch wersji
  (najstarsza → najnowsza); kliknięcie wersji uruchamia ją.
- Opcjonalnie: przycisk „Remix od najnowszej wersji” — ZAKRYTE server-side w
  pkt 3.1/Partii D (Remix zawsze remixuje najnowszy element łańcucha,
  `latest_in_lineage`), dodatkowy przycisk niepotrzebny.

---

## 5. Konfiguracja w forku ✅

W forku wiele rzeczy jest zaszytych — warto wydostać do konfiguracji
(plik `~/.infinity-arcade/config.json` lub zmienne środowiskowe):

| Co | Gdzie | Propozycja |
|---|---|---|
| URL serwera `127.0.0.1:13305` | `lemonade_client.py`, `README`, `docs` | `LEMONADE_URL` / config |
| Model default/npu/high_end | `MODELS` w `lemonade_client.py` | config (użytkownik zarządza modelami) |
| Port aplikacji `8081` | `main()` | argument CLI / config |
| Auto-start serwera | `server-running-status` w `main.py` (uruchamia serwer, gdy nie działa) | **wyłączyć w forku** — zasada: aplikacja nie startuje serwera; status ma tylko raportować |
| `install-server` / `install-model` | marasy + UI | ukryć w forku (modelami zarządza użytkownik ręcznie) |
| `webbrowser.open` przy starcie | `main()` | flaga `--no-browser` |

---

## 6. Testy i CI 🟢 ✅

- `pytest` nie jest w `install_requires` — dodać (wymaga zgody użytkownika).
- Testy jednostkowe już istnieją (`test/lemonade_client_unit.py`, ~1200 linii) —
  uruchomić je jako bazę.
- GitHub Actions na forku: matrix Python, `pytest` na każdy push do `main`.
- Testy dla `_extract_python_code` (przypadki: brak bloku, ucięty blok,
  bloki bez pygame, wiele bloków).

**Wykonanie:**
- `pytest>=8.0.0` dodany do `install_requires` (setup.py); `[tool.pytest.ini_options]`
  w `pyproject.toml` (`testpaths`, wzorce `*_unit.py` itd.).
- `test/llm_service_unit.py` + klasa `TestExtractPythonCode` (8 testów: brak bloku,
  ucięty blok, blok bez pygame, ```python / ```py / gołe ```, wiele bloków —
  wybór najdłuższego z pygame, case-insensitive pygame).
- `.github/workflows/ci.yml`: matrix Python 3.10–3.13, `pytest test/` z pominięciem
  `lemonade_client_integration.py` (testy integracyjne wymagają żywego Lemonade
  Servera — forka go nie startuje). Lokalnie: 75 passed, 5 skipped (testy win-only).

---

## 7. Drobiazgi 🟢 ✅

- `generate_game_id()`: 8 znaków UUID — kolizje praktycznie niemożliwe, OK.
- `version.py`: podnieść wersję w forku, żeby odróżnić buildy.
- Logowanie: debug zapisuje pełne odpowiedzi LLM do plików w `/tmp` — przenieść
  do `~/.infinity-arcade/llm-responses/` z limitowaną historią.
- `cleanup_finished_games` wywoływany w wielu endpointach — OK, ale przyda się
  jedno miejsce (middleware) zamiast powielania.

**Wykonanie:**
- `version.py`: `0.3.0` → `0.4.0` (odróżnia buildy forka od upstreamu).
- Debug odpowiedzi LLM: nowa funkcja `_save_llm_response` w `llm_service.py` —
  pełna odpowiedź trafia do `~/.infinity-arcade/llm-responses/`
  (nazwa `YYYYMMDDTHHMMSS_µs_{mode}.txt`, sortowalna), historia ograniczona do
  najnowszych `LLM_RESPONSE_KEEP = 20` plików; `import tempfile` usunięty
  (pozostałe użycia są w `lemonade_client.py` i nie dotyczą LLM).
- `cleanup_finished_games`: 4 jawne wywołania w endpointach (`/api/games`,
  `/api/launch-game`, `/api/game-status`, `/api/stop-game`) zastąpione jednym
  HTTP middleware (`@self.app.middleware("http")` w `ArcadeApp.__init__`),
  które sprząta skończone gry przed każdym żądaniem.
- Testy: `TestSaveLlmResponse` (4 testy: zapis pliku, tworzenie katalogu,
  przycinanie historii do 20, domyślny katalog) w `test/llm_service_unit.py` i
  `TestFinishedGamesMiddleware` (2 testy: middleware usuwa skończone gry a
  zostawia uruchomione + zarejestrowany dokładnie raz) w `test/main_unit.py`.
  Lokalnie: 89 passed, 5 skipped.

---

## 8. Poprawki CI (poza planem) 🟢 ✅

Po §7 dwa workflowy dziedziczone z upstreamu wciąż padały na każdym pushu:

- `Run LemonadeClient Tests` — ściąga i instaluje lemonade-server na runnerze
  i odpala testy integracyjne wymagające żywego serwera z modelem. Sprzeczne z
  zasadą forka (nie startujemy serwera, nie pobieramy modeli) i bez sensu w
  CI — testy integracyjne mają sens tylko lokalnie, wobec własnego serwera
  użytkownika.
- `Lint Python Code` — pylint zgłaszał 6 błędów (exit code 12), wszystkie z
  kodu epoki forka: nieużywany `Optional` w `game_launcher.py`,
  `use-dict-literal` w `llm_service.py`, `thinking_enabled`/`max_retries`
  definiowane poza `__init__` (§2.5, §4), nieużywane parametry handlera
  SIGTERM.

**Wykonanie:**
- Usunięto `.github/workflows/test_lemonade_client.yml` (unit testy
  `lemonade_client_unit.py` i tak leżą w naszym workflow `CI`).
- Fixy pylint: usunięto `Optional` z importów, `dict(...)` → dosłownik w
  `generate_game_code_with_llm`, `thinking_enabled`/`max_retries`
  zainicjalizowane w `ArcadeApp.__init__` (nadpisywane w
  `initialize_model_and_services`), parametry sygnału → `_signum, _frame`.
- Pylint: 9.96 → **10.00/10**; testy bez zmian: 89 passed, 5 skipped.

---

## Proponowana kolejność realizacji

1. **1.1** (SIGTERM — już się spłacił w produkcji)
2. **2.1** (finish_reason — tania zmiana, duża wartość diagnostyczna)
3. **2.3** (prompty — zero ryzyka, bezpośredni efekt na jakość gier)
4. **1.2 + 1.3** (logi + stop — kompletuje kontrolę nad grami)
5. **2.4** (backup przed fixem — ubezpieczenie)
6. **3.1** (rodowód — ułatwia pracę z wersjami)
7. **5** (konfiguracja + wyłączenie auto-startu — dopasowanie forka do zasad)
8. reszta w miarę potrzeb
