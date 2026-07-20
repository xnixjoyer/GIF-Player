# GIF-Overlay — Architektur (finale Version, Protokoll v2)

## Komponenten

```
                        ┌──────────────────────────────────────────┐
 gif.fish / Terminal ─┐ │  gif-script.py daemon  (EIN Prozess)     │
 gif-picker.py ───────┼─►  Gio.SocketService ── WidgetManager      │
 gif-control.py ──────┘ │   daemon.sock          │   │   │         │
                        │                 WidgetWindow × N (GTK3)  │
                        │                        │                 │
                        │              FrameStoreRegistry          │
                        │        (1 Frame-Satz pro GIF-Datei,      │
                        │         egal wie viele Instanzen)        │
                        └──────────────────────────────────────────┘
```

- **Daemon**: startet automatisch beim ersten `run`/Picker-Klick, beendet
  sich selbst 2 s nachdem das letzte Widget geschlossen wurde.
  Single-Instance über `flock` auf `daemon.lock`; räumt beim Start
  Alt-Versionen (ein Prozess pro GIF) auf. Diagnose: `daemon.log`
  (max. 512 KB) im Runtime-Verzeichnis.
- **Clients** (CLI, Picker, Panel) sind kurzlebig und sprechen alle
  dasselbe Protokoll über einen Socket.

## Entscheidungen (und warum)

|Frage           |Entscheidung                                                      |Begründung                                                                                                                                                                                                                                                                              |
|----------------|------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|Prozessmodell   |**Supervisor statt 1 Prozess/GIF**                                |~60–80 MB RAM pro weiterem GIF gespart (Python+GTK nur einmal); Discovery trivial (kein PID-Datei-Scan, keine Stale-Races); `apply-setup` atomar ohne Spawn-/Warte-Schleifen; 5× dasselbe GIF = **1×** dekodieren.                                                                      |
|IPC             |**Gio.SocketService auf dem Main-Loop**                           |Ersetzt den Server-Thread samt `idle_add`+`Event.wait`-Handshake. Dispatch ist ein normaler Funktionsaufruf im Main-Thread — kein Locking, keine Timeouts zwischen Threads.                                                                                                             |
|GTK3 vs. GTK4   |**GTK3 bleibt**                                                   |Für ein kleines Overlay bringt GSK/GPU-Rendering nichts Messbares. Migration (Event-Controller, Menü-API, gtk4-layer-shell als neue Abhängigkeit) wäre groß und auf Niri hier nicht testbar — während Canvas/Kompakt-Modell, Input-Regionen und Drag auf GTK3/Niri **verifiziert** sind.|
|Rendering       |**Cairo, premultiplied ARGB-Frames**                              |Scale/Opacity/Flip sind reine Zeichen-Transformationen; Damage-Regionen pro Frame; OpenGL wäre Overkill mit mehr Wakeups.                                                                                                                                                               |
|Decoding        |**PIL im Worker-Thread**                                          |Kanonisches GTK-Muster; asyncio bräuchte Drittbibliotheken (gbulb) ohne Gewinn, GdkPixbufAnimation kann nicht budgetiert downscalen. Memory-Budget (256 MiB) über einmaliges Downscaling, **alle** Frames bleiben erhalten.                                                             |
|Animationstiming|Monotone Deadline (GIF-Frames), **Frame-Clock-Ticks** (Bounce/Hop)|Driftfrei bzw. vsync-synchron, dt-basiert.                                                                                                                                                                                                                                              |
|fish            |**Optional**                                                      |Das CLI ist vollständig (`run/ipc/all/list/edit/lock/stop-all/picker/control`); `gif.fish` ist nur noch Komfort.                                                                                                                                                                        |

## Surface-Modell (Wayland-korrekt, unverändert)

- **Kompakt** (gesperrt + ruhend): Surface = GIF-Größe, Position via
  Layer-Shell-Margins, Input-Region leer → durchklickbar, minimaler
  Compositing-/RAM-Aufwand (wichtig fürs Gaming: kein permanentes
  Fullscreen-Overlay).
- **Canvas** (Edit/Drag/Bounce/Hop): Surface an allen vier Kanten
  verankert, GIF wird per Cairo an einem internen Offset gezeichnet.
  Die Surface bewegt sich **nie** → Drag ist exakt 1:1 und immun gegen
  Compositor-Latenz (Margins-Dragging ist auf Wayland prinzipiell racy).
- Schutz: `size-allocate` wird nur als Arbeitsfläche übernommen, wenn die
  Allokation ≥ 70 % der Monitorgröße ist (verhindert den Positions-Reset
  beim Moduswechsel); Übergangs-Frames werden leer gelassen statt falsch
  platziert.

## Protokoll v2 (eine JSON-Zeile pro Anfrage/Antwort)

```
Socket : /tmp/gif-widget-<user>/daemon.sock
Anfrage: {"action": <str>, "id": <widget|"*">, ...}   Antwort: {"ok":true,...} | {"error":...}

Daemon : ping | list | spawn{gif,id?,state?,monitor?} | stop-all
         | apply-setup{widgets:[…]} | quit-daemon
Widget : status lock unlock toggle pause play move move-by scale corner
         opacity flip speed bounce stop-bounce hop jump jump-rate reset quit
```

`list` liefert die **vollen Status-Dicts** aller Widgets → Panel-Poll und
Setup-Snapshot sind je genau ein Round-Trip.

## Persistenz

- `state.json`: pro **GIF-Dateistamm** (nicht pro Instanz); bei mehreren
  Instanzen speichert nur die erste. Felder: x, y, scale, opacity, flip,
  speed, bouncing, jumping, jump_rate. flock + atomarer Replace.
- `profiles.json`: benannte Setups (Liste vollständiger Einträge),
  Anwendung atomar im Daemon.
- Thumbnail-Cache: `~/.cache/gif-overlay/thumbs` (HiDPI-bewusst, mit
  Hintergrund-Pruning).

## Trade-offs & bekannte Grenzen

- **Ein Prozess = gemeinsamer Crash-Radius.** Mitigation: Decode komplett
  gekapselt (defekte GIFs laufen mit Teil-Frames weiter oder schließen nur
  ihr Fenster), PyGObject fängt Callback-Exceptions ohne den Loop zu
  beenden, `daemon.log` für Diagnose. Neustart ist ein `gif <name>`.
- Nach Code-Updates: `gif kill-all` (Daemon beendet sich, nächster Start
  lädt den neuen Code). Alt-Daemons (≤ v3) werden beim Start automatisch
  weggeräumt.
- Nicht im Container testbar (nur auf Niri): tatsächliches Layer-Shell-
  Verhalten. Abgedeckt durch Stub-/Protokoll-Tests + manuelle Smoke-Liste:
1. `gif <name>` ×2 → zwei Instanzen, versetzt. 2) `gif edit` → Drag 1:1,
   Positionen bleiben nach Lock/Neustart. 3) Bounce ohne Rahmen, flüssig.
1. Jump-Toggle: unregelmäßige Sprünge, Rate-Slider wirkt. 5) Setup
   speichern → kill-all → Setup anwenden (ein Klick, exakt wiederhergestellt).
1. Panel-Slider butterweich, kein Layout-Springen. 7) `gif kill-all`
   → Daemon-Exit nach ~2 s (`pgrep -f gif-script` leer).