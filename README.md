# GIF Player

GIF Player zeigt animierte GIFs als GTK3-Layer-Shell-Overlays unter Wayland.
Ein Supervisor-Daemon verwaltet mehrere Fenster, mehrere Instanzen desselben
GIFs, Profile, Positionen, Dragging, Lock/Edit, Skalierung, Transparenz,
Geschwindigkeit, Bounce und zufällige Sprünge. GIFs werden mit Pillow dekodiert
und mit Cairo gerendert; das JSON-basierte Unix-Socket-Protokoll bleibt Version 2.

> **Display:** Benötigt eine Wayland-Sitzung und einen Compositor mit
> `wlr-layer-shell`-Unterstützung, etwa Niri, Sway, Hyprland oder Wayfire.
> GTK4 und X11 werden nicht verwendet.

## Architektur

`gif-player`, `gif-picker` und `gif-control` verwenden dieselbe XDG- und
Bootstrap-Schicht. Der automatisch gestartete `gif-player daemon` besitzt alle
GTK3-Fenster. Mehrere Instanzen derselben Datei teilen einen `FrameStore`.

Die testbare Player-Logik in `gif_player_runtime.py` ergänzt den bestehenden
GTK3-Player um Disposal-sichere Frame-Kopien, absolute Frame-Deadlines,
positionsgleiche Compact/Canvas-Übergänge, freies Offscreen-Dragging und getrennte
Bounce-Grenzen. Details stehen in [ARCHITECTURE.md](ARCHITECTURE.md) und im
[Player-Pipeline-Bericht](docs/PLAYER_PIPELINE_ANALYSIS.md).

## Installation

```console
nix profile add github:xnixjoyer/GIF-Player
```

Direkt ohne Installation:

```console
nix run github:xnixjoyer/GIF-Player -- --help
nix run github:xnixjoyer/GIF-Player -- mascot
```

In einer NixOS-Flake:

```nix
environment.systemPackages = [
  inputs.gif-player.packages.${pkgs.system}.default
];
```

Der Flake unterstützt `x86_64-linux` und `aarch64-linux` und stellt
`packages`, `apps`, `checks` und eine Development Shell bereit.

## GIF-Verzeichnis

Priorität:

1. `--gif-dir DIR`
2. `GIF_PLAYER_GIF_DIR`
3. `$XDG_DATA_HOME/gif-player/gifs` oder `~/.local/share/gif-player/gifs`

Ein bereits vorhandenes `~/Scripts/Gif-Overlay/Gifs` wird als
Kompatibilitätsfallback erkannt, aber nie erstellt.

```console
export GIF_PLAYER_GIF_DIR="$HOME/Pictures/Overlays"
gif-player picker
```

GIFs dürfen in Unterordnern liegen. Das CLI löst eindeutige Dateistämme ohne
externes `find` auf:

```console
gif-player mascot
gif-player --gif-dir ~/Pictures/Gifs mascot
gif-player run ~/Pictures/Gifs/anime/mascot.gif --monitor 1
```

Bei mehreren gleichnamigen Dateien meldet das CLI die Mehrdeutigkeit, statt
eine zufällige Datei zu starten.

## Programme und CLI

```text
gif-player                         Picker öffnen
gif-player NAME                    GIF nach Namen starten
gif-player run GIF [Optionen]      GIF per Name oder Pfad starten
gif-player ipc ID ACTION [ARGS]    Widget steuern
gif-player all ACTION [ARGS]       Alle Widgets steuern
gif-player list                    Laufende IDs anzeigen
gif-player edit                    Alle entsperren
gif-player lock                    Alle sperren
gif-player stop-all | kill-all     Alle Widgets schließen
gif-player picker                  Picker öffnen
gif-player control                 Control-Panel öffnen
gif-player daemon                  Supervisor manuell starten
gif-player doctor                  Python- und GTK-Abhängigkeiten prüfen
```

Widget-Aktionen: `status`, `lock`, `unlock`, `toggle`, `pause`, `play`,
`move X Y`, `move-by DX DY`, `scale N`, `corner POS`, `opacity N`, `flip MODE`,
`speed N`, `bounce`, `stop-bounce`, `hop`, `jump`, `jump-rate SECONDS`, `reset`,
`quit`.

Beispiele:

```console
gif-player mascot
gif-player mascot                  # zweite Instanz: mascot-2
gif-player ipc mascot-2 move 300 120
gif-player ipc mascot scale 1.4
gif-player all lock
gif-player stop-all
```

## Freies Positionieren außerhalb des Monitors

Im Edit-/Drag-Modus werden manuelle Positionen nicht an Monitorgrenzen geklemmt.
Negative X/Y-Werte und Werte jenseits der rechten oder unteren Grenze sind
erlaubt. Ein GIF darf teilweise oder vollständig außerhalb liegen.

```console
gif-player ipc mascot move -250 900
gif-player ipc mascot move 3000 -400
```

Ein teilweise außerhalb liegendes Widget behält beim Locken exakt seine
Position. Dafür bleibt es intern als durchklickbare Canvas-Surface aktiv. Sobald
es wieder vollständig innerhalb liegt, kann der Player in den kompakten Modus
zurückkehren.

Wiederherstellung:

```console
gif-player ipc mascot corner center
gif-player ipc mascot reset
gif-player ipc mascot move 100 100
```

Bounce verwendet weiterhin eigene, strikt begrenzte Koordinaten. Bei einem auf
einer Achse größeren GIF wird diese Achse zentriert und angehalten, während die
andere Achse weiter bouncen kann.

## Jump- und Frame-Pacing

Der Compact/Canvas-Wechsel vor einem Hop verwendet einen zweiphasigen,
positionsgleichen Übergang. Der erste Canvas-Frame zeigt denselben GIF-Frame an
derselben Position und besitzt einen Jump-Offset von exakt null. Es wird kein
absichtlich transparenter Übergangsframe mehr ausgegeben.

GIF-Animationen verwenden monotone absolute Deadlines. Wenn der GTK-Main-Loop
kurz blockiert war, werden überfällige Zeitabschnitte berücksichtigt, aber nur
das neueste fällige Frame gezeichnet. Dadurch entstehen keine schnellen
Catch-up-Bursts alter Frames.

## Timing-Diagnose

Detaillierte Logs sind standardmäßig aus. Zum Reproduzieren eines visuellen
Problems den Daemon zuerst beenden und mit Diagnose neu starten:

```console
gif-player stop-all
GIF_PLAYER_DEBUG_TIMING=1 gif-player daemon
```

Danach in einem zweiten Terminal Picker, Hop oder Bounce ausführen. Das Log liegt
unter:

```console
cat "$XDG_RUNTIME_DIR/gif-player/daemon.log"
```

Es enthält monotone JSON-Ereignisse für Surface-Übergänge, `size-allocate`,
Jump-Fortschritt, Frame-Deadlines, ausgelassene Catch-up-Draws, Damage und Draws.

## Fish

Das Paket installiert `share/fish/vendor_functions.d/gif.fish` und
Completions. Die Funktion enthält keine Installationspfade:

```fish
function gif
    command gif-player $argv
end
```

## XDG-Speicherorte

| Inhalt | Standard |
|---|---|
| Socket `daemon.sock` | `$XDG_RUNTIME_DIR/gif-player/` |
| Daemon-Lock und `daemon.log` | `$XDG_RUNTIME_DIR/gif-player/` |
| Fallback Runtime | `/tmp/gif-player-$UID/` |
| `state.json`, `profiles.json` | `$XDG_CONFIG_HOME/gif-player/` |
| Thumbnail-Cache | `$XDG_CACHE_HOME/gif-player/thumbs/` |
| GIFs | `$XDG_DATA_HOME/gif-player/gifs/` |

Runtime wird privat mit Modus `0700` erstellt; der Socket verwendet höchstens
`0600`. Es wird nie in den Nix Store geschrieben.

## Entwicklung und Checks

```console
nix develop
python gif_player_cli.py --help
python -m unittest discover -s tests -v
ruff check .
nixfmt flake.nix nix/package.nix
nix flake check
nix build .#gif-player
./result/bin/gif-player --help
nix run .#gif-player -- --help
```

Die automatischen Checks prüfen Python-Syntax, `gi`, Cairo und Pillow, die
Typelibs `Gtk 3.0`, `Gdk 3.0`, `GdkPixbuf 2.0` und `GtkLayerShell 0.1`,
displayfreie CLI-Hilfe, isolierte XDG-Pfade, Runtime-Modus, Protokoll-v2-
Roundtrips, GIF-Namensauflösung, Disposal 2/3, lokale Paletten,
Cairo-Premultiplication, Jump-Kontinuität, freie Positionen, Bounce-Reflexion und
absolute Frame-Deadlines. Sie öffnen kein echtes Wayland-Fenster.

## Fehlerdiagnose

- `WAYLAND_DISPLAY ist nicht gesetzt`: Anwendung innerhalb einer grafischen
  Wayland-Sitzung starten.
- Kein Overlay trotz laufendem Daemon: Layer-Shell-Unterstützung des
  Compositors prüfen und das Log unter `$XDG_RUNTIME_DIR/gif-player/daemon.log`
  lesen.
- Falsches GIF-Verzeichnis: `gif-player self-test` zeigt die aufgelösten Pfade.
- Fehlende Python-/GTK-Komponente: `gif-player doctor` prüft Imports und Typelibs.
- Unsichtbar herausgeschobenes GIF: `corner center`, `reset` oder direkte X/Y-
  Position verwenden.
- Nach einem Paketupdate: `gif-player stop-all`; der nächste Start lädt den
  Daemon aus dem neuen Paket.

## Manueller Wayland-Smoke-Test

- [ ] Picker öffnet sich.
- [ ] GIF aus dem konfigurierten Verzeichnis startet.
- [ ] Mehrere Instanzen desselben GIFs funktionieren.
- [ ] Control-Panel findet alle Instanzen.
- [ ] Lock und Edit funktionieren.
- [ ] Dragging bleibt exakt 1:1.
- [ ] Skalierung, Transparenz und Geschwindigkeit funktionieren.
- [ ] Manueller und automatischer Jump zeigen keinen leeren Übergangsframe.
- [ ] Teilweise und vollständig offscreen liegende Positionen bleiben erhalten.
- [ ] Lock/Edit verändert eine offscreen Position nicht.
- [ ] `corner center` und `reset` holen ein unsichtbares GIF zurück.
- [ ] Bounce bleibt innerhalb seiner gültigen Achsen.
- [ ] Übergroße Bounce-Achsen bleiben ruhig und zentriert.
- [ ] Profile lassen sich speichern und wiederherstellen.
- [ ] `gif-player stop-all` beendet alle Widgets.
- [ ] Der Daemon beendet sich nach dem letzten Widget automatisch.
- [ ] Nach einem Neustart werden Config und Cache aus den XDG-Pfaden gelesen.

Eine ausführliche 60/120/144-Hz-, Multi-Monitor- und HiDPI-Checkliste steht im
[Player-Pipeline-Bericht](docs/PLAYER_PIPELINE_ANALYSIS.md).

## Medien und Lizenz

Das Paket bündelt keine GIFs oder anderen Anime-/Medieninhalte. Im Repository
ist derzeit keine Lizenzdatei vorhanden. Deshalb setzt das Nix-Paket bewusst
kein `meta.license`. Vor einer Weiterverteilung sollte eine passende Lizenz
vom Rechteinhaber ergänzt werden.
