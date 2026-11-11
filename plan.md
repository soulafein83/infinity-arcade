# Plan ulepszeń — Infinity Arcade (fork `soulafein83/infinity-arcade`)

> Stan: **wykonano 1.1, 1.2, 1.3, 2.1, 2.3, 2.4** (commity Partii A–C), reszta: propozycje.
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

### 2.2. Oszczędzanie budżetu tokenów (model „thinking”)
**Problem:** Qwen 3.5-9B to model z tokenami racjonowania (`reasoning_content`),
które spalone są z `max_tokens` przed właściwym kodem.

**Propozycja:**
- Próbować włączenie trybu bez myślenia w żądaniach generujących kod
  (np. `extra_body={"chat_template_kwargs": {"enable_thinking": false}}` —
  wymaga testu na tym modelu) — więcej miejsca na kod przy tym samym limicie.
- Tytuł: `max_tokens: 800` jest bezpieczne, ale dla non-thinking można spaść do ~100;
  dla thinking zostawić 800 — ustawić świadomie per tryb, nie „na oko”.

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

### 2.5. Liczba prób auto-fix
`max_retries=1` w `launch_game_endpoint` — dla większego modelu 2 próby bywają
wystarczające, ale kosztują ~2× czas. Propozycja: wartość konfigurowalna
(domyślnie 1), ewentualnie 2 za przełącznikiem.

---

## 3. Magazyn gier i wersjonowanie 🟡

### 3.1. Rodowód gier w metadata
**Problem:** remix tworzy nowy `game_id`, ale jedynym śladem pochodzenia jest
tekst w polu `prompt` („Remix of 'Pong Duel v2'"). Trudno wybrać właściwą wersję
do kolejnego remiksu (stąd reguła „remiksuj od najnowszej”).

**Propozycja:** pola `"parent_game_id"` i `"version"` w `metadata.json`;
UI pokazuje drzewo/łańcuch wersji; remix domyślnie z najnowszej wersji łańcucha.

### 3.2. Porządki
- `DELETE /api/delete-game` nie czyszczy backupów (po 2.4) ani logów — dodać.
- `metadata.json` zapisywany bez blokady/atomarnie — przy większej liczbie gier
  napisać atomarnie (tmp + `os.replace`).

---

## 4. Frontend / UX 🟡

- Karta gry: wskaźnik „działa” + przycisk Stop (z pkt 1.3) + „ostatni błąd”.
- Widok kodu źródłowego w przeglądarce (endpoint `open-game-file` otwiera
  plik systemowym edytorem — lepiej wbudowany viewer z podglądem).
- Historia remiksów danej gry na karcie (z pkt 3.1).
- Opcjonalnie: przycisk „Remix od najnowszej wersji” zamiast ręcznego wyboru.

---

## 5. Konfiguracja w forku 🟡

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

## 6. Testy i CI 🟢

- `pytest` nie jest w `install_requires` — dodać (wymaga zgody użytkownika).
- Testy jednostkowe już istnieją (`test/lemonade_client_unit.py`, ~1200 linii) —
  uruchomić je jako bazę.
- GitHub Actions na forku: matrix Python, `pytest` na każdy push do `main`.
- Testy dla `_extract_python_code` (przypadki: brak bloku, ucięty blok,
  bloki bez pygame, wiele bloków).

---

## 7. Drobiazgi 🟢

- `generate_game_id()`: 8 znaków UUID — kolizje praktycznie niemożliwe, OK.
- `version.py`: podnieść wersję w forku, żeby odróżnić buildy.
- Logowanie: debug zapisuje pełne odpowiedzi LLM do plików w `/tmp` — przenieść
  do `~/.infinity-arcade/llm-responses/` z limitowaną historią.
- `cleanup_finished_games` wywoływany w wielu endpointach — OK, ale przyda się
  jedno miejsce (middleware) zamiast powielania.

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
