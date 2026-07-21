# GIF Player – Architektur (GTK3, Supervisor, IPC v2)

## Komponenten

```text
gif-player / gif-picker / gif-control
                  │
                  ├── XDG- und Bootstrap-Schicht
                  │   (gif_player_paths.py, gif_player_bootstrap.py)
                  │
                  └── gif-script.py daemon
                        ├── Gio.SocketService, JSON-Protokoll v2
                        ├── WidgetManager
                        ├── WidgetWindow × N (GTK3 + GtkLayerShell)
                        └── FrameStoreRegistry (Pillow → Cairo)
```

Die Rendering- und Animationsimplementierung bleibt GTK3-basiert. Ein einziger
Daemon verwaltet alle Layer-Shell-Fenster. Mehrere Instanzen desselben GIFs
teilen weiterhin einen dekodierten Frame-Satz.

## Installierte Programme

- `gif-player`: shellunabhängiges Haupt-CLI und Daemon-Bootstrap.
- `gif-picker`: grafischer Picker.
- `gif-control`: Live-Control-Panel.
- `gif`: optionale Fish-Funktion, die nur `gif-player` aufruft.

Die Python-Dateien liegen im Nix-Paket unter `libexec/gif-player`. Interne
Starts verwenden immer `sys.executable` und einen absoluten Pfad in genau
diesem `libexec`-Verzeichnis. Das aktuelle Arbeitsverzeichnis und globale
Python-Installationen sind irrelevant.

## XDG-Pfade

| Inhalt | Pfad |
|---|---|
| Socket, Lock, Log | `$XDG_RUNTIME_DIR/gif-player`, Fallback `/tmp/gif-player-$UID` |
| Zustand und Profile | `$XDG_CONFIG_HOME/gif-player` |
| Thumbnail-Cache | `$XDG_CACHE_HOME/gif-player/thumbs` |
| GIFs | `$XDG_DATA_HOME/gif-player/gifs` |

Das Runtime-Verzeichnis wird auf `0700`, der Socket auf höchstens `0600`
gesetzt. Der alte Ordner `~/Scripts/Gif-Overlay/Gifs` wird nur erkannt, wenn er
bereits existiert und der XDG-GIF-Ordner noch nicht vorhanden ist; er wird nie
angelegt.

## Protokoll v2

Eine Anfrage und eine Antwort bestehen jeweils aus genau einer JSON-Zeile.

```text
Daemon: ping, list, spawn, stop-all, apply-setup, quit-daemon
Widget: status, lock, unlock, toggle, pause, play, move, move-by, scale,
        corner, opacity, flip, speed, bounce, stop-bounce, hop, jump,
        jump-rate, reset, quit
```

## Display-Anforderung

Overlay, Picker und Control benötigen eine Wayland-Sitzung und einen Compositor
mit Layer-Shell-Unterstützung, beispielsweise Niri, Sway, Hyprland oder Wayfire.
CLI-Hilfe, Pfadtests, Syntaxprüfungen und IPC-Unit-Tests benötigen kein Display.
