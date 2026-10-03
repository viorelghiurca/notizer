# Notizer

Besprechungen aufnehmen, transkribieren und zusammenfassen – lokal auf deinem PC.
Desktop-App für Windows und Linux, gebaut mit Tauri 2, React und einem Python-Core.

**Stand: M0 (Grundgerüst).** Die App startet, bringt den Core mit und kann Audiodateien
(MP3, M4A, WAV) importieren, abspielen, umbenennen, in Ordner sortieren und über den
Papierkorb löschen. Transkription folgt in M1, die KI-Auswertung in M3.

## Aufbau

```
notizer/
├─ core/                 Notizer Core (Python, FastAPI, SQLite)
│  ├─ notizer_core/      api.py, db.py, config.py, audio.py, __main__.py
│  └─ tests/             pytest
├─ app/                  Oberfläche (React + TypeScript, Vite)
│  ├─ src/               App.tsx, components/, lib/
│  └─ src-tauri/         Desktop-Hülle (Rust); startet den Core als Hintergrundprozess
├─ scripts/build_core.py baut den Core als Einzeldatei für den Installer
└─ .github/workflows/    automatischer Build von .exe/.msi und .deb/.AppImage
```

So arbeiten die Teile zusammen:

1. Die App startet den Core. Der Core sucht sich einen freien Port und meldet
   `NOTIZER_READY {"port": …, "token": …}`.
2. Die Oberfläche spricht nur über `http://127.0.0.1:<port>` mit dem Token im Header
   `X-Notizer-Token`. Der Core ist von außen nicht erreichbar.
3. Wird die App geschlossen (oder stürzt sie ab), beendet sich der Core von selbst.

Daten liegen unter Windows in `%LOCALAPPDATA%\Notizer`, unter Linux in
`~/.local/share/Notizer` (Datenbank `notizer.db`, Audiodateien in `audio/`).

## Voraussetzungen für die Entwicklung

- Python 3.11 oder neuer
- Node.js 22
- Rust (https://rustup.rs)
- Windows: „Microsoft C++ Build Tools“ (Desktopentwicklung mit C++); WebView2 ist in
  Windows 10/11 bereits enthalten
- Linux (Ubuntu/Debian):
  `sudo apt install libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev libssl-dev patchelf`

## Einrichten

```bash
# Core
cd core
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q

# Oberfläche
cd ../app
npm install
```

## Starten (Entwicklung)

```bash
cd app
npm run tauri dev
```

Im Entwicklungsmodus startet die App den Core direkt aus `core/` mit der Python-venv;
Änderungen an der Oberfläche erscheinen sofort.

Nur im Browser, ohne Tauri:

```bash
# Terminal 1
cd core && python -m notizer_core --port 8765 --token dev
# Terminal 2
cd app && npm run dev        # dann http://localhost:1420 öffnen
```

## Installer bauen

**Automatisch (empfohlen):** Repository auf GitHub hochladen, dann unter
*Actions → Build → Run workflow* starten. Nach etwa 15 Minuten liegen unter dem Lauf die
Artefakte `notizer-Windows` (Setup-.exe und .msi) und `notizer-Linux` (.deb und .AppImage).
Ein Tag wie `v0.1.0` startet den Build ebenfalls.

**Lokal** (auf dem jeweiligen System, mit aktivierter Core-venv):

```bash
python scripts/build_core.py
cd app
npm run tauri build -- --config src-tauri/tauri.bundle.conf.json
```

Ergebnis unter `app/src-tauri/target/release/bundle/`, z. B.
`nsis/Notizer_0.1.0_x64-setup.exe`. Eine Windows-.exe lässt sich nur unter Windows bauen
(lokal oder über GitHub Actions).

Hinweis: Der Installer ist noch nicht signiert. Windows SmartScreen zeigt deshalb beim
ersten Start „Unbekannter Herausgeber“ – über *Weitere Informationen → Trotzdem ausführen*
geht es weiter.

## API (M0)

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/api/health` | Lebenszeichen (ohne Token) |
| GET | `/api/info` | Version, Datenordner, Formate |
| GET | `/api/recordings?folder_id=&unfiled=&trash=&q=` | Aufnahmen auflisten |
| POST | `/api/recordings/import` | Dateien hochladen (`files`, optional `last_modified`, `folder_id`) |
| GET/PATCH | `/api/recordings/{id}` | lesen, Titel/Ordner/Favorit ändern |
| DELETE | `/api/recordings/{id}` | in den Papierkorb |
| POST | `/api/recordings/{id}/restore` | wiederherstellen |
| DELETE | `/api/recordings/{id}/permanent` | endgültig löschen (nur aus dem Papierkorb) |
| DELETE | `/api/trash` | Papierkorb leeren |
| GET | `/api/recordings/{id}/audio?token=` | Audiodatei streamen |
| GET/POST/PATCH/DELETE | `/api/folders[/{id}]` | Ordner verwalten |
| GET | `/api/counts` | Zähler für die Seitenleiste |

Aufnahmen im Papierkorb werden beim Start nach 30 Tagen endgültig gelöscht.

## Nächster Meilenstein: M1 – Transkript

faster-whisper (Wort-Zeitstempel), Sprechertrennung mit pyannote, Transkript-Ansicht mit
Sprechern und Sprung zur Stelle im Player, Job-Fortschritt per WebSocket.
