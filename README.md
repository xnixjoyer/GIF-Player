# GIF Player

GIF Player displays animated GIF files as GTK3 layer-shell overlays on Wayland. A single supervisor daemon owns all overlay windows. GIF frames are decoded with Pillow and rendered with Cairo. Multiple instances of the same GIF, positioning, dragging, lock/edit mode, scaling, opacity, playback speed, flipping, bounce, jump, persistent state, and named profiles are preserved. Clients communicate with the daemon through the JSON-based Unix-socket protocol v2.

> **Display requirement:** GIF Player requires a Wayland session and a compositor that supports the layer-shell protocol. Niri, Sway, Hyprland, and Wayfire are suitable examples. X11 is not supported. Do not assume that every GNOME Shell or KDE Plasma session provides compatible layer-shell behavior without additional compositor or extension support.

## Architecture

`gif-player`, `gif-picker`, and `gif-control` share the same Python, XDG-path, bootstrap, and IPC implementation. The automatically started `gif-player daemon` owns all GTK3 windows. Multiple instances of the same GIF share one decoded `FrameStore`. The established GTK implementation is installed under `libexec/gif-player` and loaded through package-relative paths; it never depends on the current working directory or on a source checkout.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the detailed supervisor, rendering, and IPC design.

## Dependencies

Python runtime dependencies:

- PyGObject
- pycairo
- Pillow

System runtime dependencies:

- GTK 3
- gtk-layer-shell
- GLib
- GObject Introspection
- GdkPixbuf
- Cairo

The installed application does not use Pip, create a virtual environment, or set a global `LD_LIBRARY_PATH` at runtime.

## NixOS installation

Install into a user profile:

```console
nix profile install github:xnixjoyer/GIF-Player
```

Run directly without installing:

```console
nix run github:xnixjoyer/GIF-Player -- --help
nix run github:xnixjoyer/GIF-Player -- mascot
```

Use it from a NixOS flake:

```nix
environment.systemPackages = [
  inputs.gif-player.packages.${pkgs.system}.default
];
```

The flake supports `x86_64-linux` and `aarch64-linux` and exposes packages, apps, checks, and a development shell.

Development and package checks:

```console
nix develop
nix flake check
nix build .#gif-player
./result/bin/gif-player --help
nix run . -- --help
```

## Fedora installation

The repository contains `packaging/fedora/gif-player.spec`. The current package names used by the spec are:

```console
sudo dnf install \
  python3 python3-gobject python3-cairo python3-pillow \
  gtk3 gtk-layer-shell gobject-introspection
```

Build an RPM from a prepared `gif-player-0.2.0.tar.gz` source archive:

```console
mkdir -p ~/rpmbuild/{SOURCES,SPECS}
tar --exclude-vcs --transform 's,^,gif-player-0.2.0/,' \
  -czf ~/rpmbuild/SOURCES/gif-player-0.2.0.tar.gz .
cp packaging/fedora/gif-player.spec ~/rpmbuild/SPECS/
rpmbuild -ba ~/rpmbuild/SPECS/gif-player.spec
```

Install the resulting package:

```console
sudo dnf install ~/rpmbuild/RPMS/noarch/gif-player-*.noarch.rpm
```

The RPM uses Fedora's `%pyproject_*` macros, performs no network access during the build, installs no user data, and does not bundle GIF files.

## Arch Linux installation

The repository contains `packaging/arch/PKGBUILD` and `.SRCINFO`. Required official-repository packages include:

```console
sudo pacman -S --needed \
  python python-gobject python-cairo python-pillow \
  gtk3 gtk-layer-shell gobject-introspection-runtime
```

Build from the repository checkout:

```console
cd packaging/arch
makepkg --syncdeps --cleanbuild
pacman -Qlp gif-player-*.pkg.tar.zst
```

Install the resulting package:

```console
sudo pacman -U gif-player-*.pkg.tar.zst
```

The PKGBUILD builds the shared Python wheel without network isolation downloads, creates no files in a user's home directory, and does not bundle media.

## GIF directory

GIF directory priority:

1. explicit `--gif-dir DIR`
2. `GIF_PLAYER_GIF_DIR`
3. `$XDG_DATA_HOME/gif-player/gifs`
4. `~/.local/share/gif-player/gifs` when `XDG_DATA_HOME` is unset
5. an already existing `~/Scripts/Gif-Overlay/Gifs` as an optional compatibility fallback

The legacy directory is never created automatically.

```console
export GIF_PLAYER_GIF_DIR="$HOME/Pictures/Overlays"
gif-player picker
```

GIF files may be stored in subdirectories. The CLI resolves unique file stems without an external `find` command:

```console
gif-player mascot
gif-player --gif-dir ~/Pictures/Gifs mascot
gif-player run ~/Pictures/Gifs/anime/mascot.gif --monitor 1
```

When several files have the same stem, the CLI reports the ambiguity instead of starting a random match.

## Programs and CLI

```text
gif-player                         Open the picker
gif-player NAME                    Start a GIF by name
gif-player run GIF [OPTIONS]       Start a GIF by name or path
gif-player ipc ID ACTION [ARGS]    Control one widget
gif-player all ACTION [ARGS]       Control all widgets
gif-player list                    List running widget IDs
gif-player edit                    Unlock all widgets
gif-player lock                    Lock all widgets
gif-player stop-all | kill-all     Close all widgets
gif-player picker                  Open the picker
gif-player control                 Open the control panel
gif-player daemon                  Start the supervisor manually
gif-player self-test               Print and validate resolved XDG paths
gif-player doctor                  Validate Python imports and GTK typelibs
```

Supported widget actions include `status`, `lock`, `unlock`, `toggle`, `pause`, `play`, `move X Y`, `move-by DX DY`, `scale N`, `corner POS`, `opacity N`, `flip MODE`, `speed N`, `bounce`, `stop-bounce`, `hop`, `jump`, `jump-rate SECONDS`, `reset`, and `quit`.

Examples:

```console
gif-player mascot
gif-player mascot                  # second instance: mascot-2
gif-player ipc mascot-2 move 300 120
gif-player ipc mascot scale 1.4
gif-player ipc mascot opacity 0.75
gif-player ipc mascot speed 1.5
gif-player ipc mascot flip h
gif-player ipc mascot bounce
gif-player ipc mascot jump
gif-player all lock
gif-player stop-all
```

## Picker, control panel, and profiles

Open the graphical picker:

```console
gif-picker
```

Open the live control panel:

```console
gif-control
```

The picker provides cached thumbnails, category filtering for GIF subdirectories, and named profiles. Profiles store complete multi-widget setups and can restore multiple instances with their position, scale, opacity, flip, speed, bounce, jump, and jump-rate settings.

## Fish integration

All packages install `share/fish/vendor_functions.d/gif.fish` and Fish completions. The function is a thin, path-independent wrapper:

```fish
function gif
    command gif-player $argv
end
```

Bash and Zsh users can use every feature directly through `gif-player`; Fish is optional.

## XDG locations

| Data | Default location |
|---|---|
| Socket `daemon.sock` | `$XDG_RUNTIME_DIR/gif-player/` |
| Daemon lock and `daemon.log` | `$XDG_RUNTIME_DIR/gif-player/` |
| Runtime fallback | `/tmp/gif-player-$UID/` |
| `state.json` and `profiles.json` | `$XDG_CONFIG_HOME/gif-player/` |
| Configuration fallback | `~/.config/gif-player/` |
| Thumbnail cache | `$XDG_CACHE_HOME/gif-player/thumbs/` |
| Cache fallback | `~/.cache/gif-player/thumbs/` |
| GIF files | `$XDG_DATA_HOME/gif-player/gifs/` |
| Data fallback | `~/.local/share/gif-player/gifs/` |

The runtime directory is owned by the current user and forced to mode `0700`. The daemon socket uses mode `0600`. The application never writes to `/usr`, `/nix/store`, `site-packages`, or its installed `libexec` directory.

## Error handling and diagnostics

- **`WAYLAND_DISPLAY is not set` / localized equivalent:** start the application inside a graphical Wayland session.
- **GtkLayerShell typelib missing:** install the distribution's `gtk-layer-shell` package and its GObject Introspection data.
- **GTK cannot initialize the display:** verify that the Wayland display socket is reachable from the process environment.
- **Compositor does not support layer shell:** use a compatible compositor or enable verified layer-shell support. The program exits with a concise error instead of an expected-user-error traceback.
- **Daemon runs but no overlay is visible:** inspect `$XDG_RUNTIME_DIR/gif-player/daemon.log`, or `/tmp/gif-player-$UID/daemon.log` when no XDG runtime directory is available.
- **Wrong GIF directory:** `gif-player self-test` prints the resolved paths.
- **Missing Python or GTK component:** `gif-player doctor` validates Cairo, Pillow, PyGObject, Gtk 3.0, Gdk 3.0, GdkPixbuf 2.0, and GtkLayerShell 0.1.
- **After a package update:** run `gif-player stop-all`; the next start loads the daemon from the new package.

## Automated checks

```console
python -m compileall -q .
PYTHONPATH=. python -m unittest discover -s tests -v
ruff check gif_player_*.py tests
desktop-file-validate data/gif-player-picker.desktop
desktop-file-validate data/gif-player-control.desktop
```

Automated checks cover Python syntax, imports, XDG resolution, runtime permissions, socket paths, profile/state/cache paths, recursive and ambiguous GIF-name resolution, JSON IPC messages, daemon ping behavior, display-free CLI help, required protocol-v2 actions, and protection against writes to installed package directories. They do not require a real Wayland compositor.

GitHub Actions contains separate jobs for Python checks, Nix flake/build checks, a Fedora RPM build, and an Arch package build. CI does not pretend to test real overlay behavior.

## Manual Wayland smoke tests

Run this checklist on NixOS, Fedora, and Arch Linux under a compatible compositor:

1. [ ] `gif-picker` opens.
2. [ ] GIF files are discovered in the configured directory.
3. [ ] A GIF starts successfully.
4. [ ] Multiple instances of the same GIF work.
5. [ ] `gif-control` sees every instance.
6. [ ] Positioning and dragging work exactly.
7. [ ] Lock and edit mode work.
8. [ ] Scaling works.
9. [ ] Opacity works.
10. [ ] Playback speed works.
11. [ ] Horizontal and vertical flip work.
12. [ ] Bounce works.
13. [ ] Jump works.
14. [ ] A profile can be saved.
15. [ ] A profile can be restored.
16. [ ] `gif-player stop-all` closes every instance.
17. [ ] The daemon exits automatically after the final widget closes.
18. [ ] Config, cache, runtime, and data files use the documented XDG locations.
19. [ ] Stored settings survive a restart.
20. [ ] The installed application works after deleting or moving the source checkout.

## Media and licensing

The project does not bundle GIF files, anime content, or other media. The repository currently has no license file. The Nix package intentionally omits `meta.license`; Fedora and Arch package metadata mark the licensing status as unresolved. A license must be supplied by the rights holder before redistribution through repositories that require an approved license declaration.
