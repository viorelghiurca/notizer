# Notizer

Besprechungen aufnehmen, transkribieren und zusammenfassen – lokal auf deinem PC.
Desktop-App für Windows und Linux, gebaut mit Tauri 2, React und einem Python-Core.

**Stand: M1 (Transkript).** Audiodateien (MP3, M4A, WAV) importieren, verwalten und
lokal transkribieren – mit Sprechererkennung, Live-Fortschritt, Bearbeiten im Text,
Sprecher umbenennen, Sprung zur Stelle im Player, Volltextsuche und Export als TXT/SRT.
Die KI-Auswertung (Notizen, Mindmap, E-Mail, Termine) folgt in M3.

## Transkription

| Teil | Technik | Download beim ersten Gebrauch |
| --- | --- | --- |
| Spracherkennung | faster-whisper, Standard `large-v3-turbo` (wählbar: large-v3, medium, small) | 0,5–3 GB von Hugging Face |
| Sprechertrennung | sherpa-onnx mit pyannote-Segmentierung 3.0 und WeSpeaker-Stimmmodell (ONNX, kein PyTorch) | ca. 33 MB von GitHub |

Danach läuft alles ohne Internet. Modelle liegen im Datenordner unter `models/`.
Läuft eine NVIDIA-Grafikkarte mit CUDA, nutzt faster-whisper sie automatisch, sonst die CPU.

Ablauf eines Auftrags: Transkribieren (0–80 %) → Sprecher erkennen (80–98 %) → Zusammenführen.
Ein Worker arbeitet die Aufträge nacheinander ab; Fortschritt kommt per WebSocket.
Abbrechen ist jederzeit möglich; nach einem Neustart gelten laufende Aufträge als abgebrochen.

Fehlersuche: `notizer-core --selftest datei.wav` prüft Audio-Dekodierung, Sprachpausen-
Erkennung und Sprechertrennung und gibt das Ergebnis aus.

## Aufbau

```
notizer/
├─ core/                 Notizer Core (Python, FastAPI, SQLite)
│  ├─ notizer_core/      api.py, db.py, engines.py, jobs.py, exporting.py, …
│  └─ tests/             pytest; demo_server.py für Oberflächentests ohne Whisper-Modell
├─ app/                  Oberfläche (React + TypeScript, Vite)
│  ├─ src/               App.tsx, components/, lib/
│  └─ src-tauri/         Desktop-Hülle (Rust); startet den Core als Hintergrundprozess
├─ scripts/build_core.py baut den Core als Ordner für den Installer
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

Oberfläche testen ohne Whisper-Modell (Sprechertrennung echt, Text vorgegeben):
`cd core && python -m tests.demo_server --port 8765 --token dev --data-dir /tmp/notizer-demo`

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
`nsis/Notizer_0.1.0_x64-setup.exe`. Der Core wird als Ordner `core/` mitgeliefert
(rund 650 MB entpackt, im Installer etwa 220 MB), damit er ohne Entpacken sofort startet. Eine Windows-.exe lässt sich nur unter Windows bauen
(lokal oder über GitHub Actions).

Hinweis: Der Installer ist noch nicht signiert. Windows SmartScreen zeigt deshalb beim
ersten Start „Unbekannter Herausgeber“ – über *Weitere Informationen → Trotzdem ausführen*
geht es weiter.

## API

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
| POST | `/api/recordings/{id}/transcribe` | Auftrag starten (`language`, `diarize`, `num_speakers`, `model`) |
| GET | `/api/jobs` · `/api/recordings/{id}/job` | laufende Aufträge · letzter Auftrag einer Aufnahme |
| POST | `/api/jobs/{id}/cancel` | Auftrag abbrechen |
| GET | `/api/recordings/{id}/transcript` | Abschnitte und Sprecher |
| PATCH | `/api/segments/{id}` | Text oder Sprecher eines Abschnitts ändern |
| PATCH | `/api/recordings/{id}/speakers/{label}` | Sprecher umbenennen |
| GET/POST | `/api/recordings/{id}/export` | TXT/SRT herunterladen bzw. in Datei schreiben |
| GET/PATCH | `/api/settings` | Modell, Standardsprache, Sprechertrennung, eigene Begriffe |
| GET | `/api/models` | Modelle und ob sie schon geladen sind |
| WS | `/ws?token=` | Ereignisse: Auftragsfortschritt, Statusänderungen |

Aufnahmen im Papierkorb werden beim Start nach 30 Tagen endgültig gelöscht.

## Nächste Meilensteine

- **M2 – App-Grundlagen:** Export als PDF/Word, Transkript-Suche mit Treffern im Text, Sortierung
- **M3 – KI-Ausgaben:** Vorlagen, Zusammenfassung, Mindmap, E-Mail, Termine, Frag Notizer, Stimmprofile
