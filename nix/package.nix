{
  lib,
  python3Packages,
  gtk3,
  gtk-layer-shell,
  glib,
  gdk-pixbuf,
  gobject-introspection,
  wrapGAppsHook3,
}:

python3Packages.buildPythonApplication {
  pname = "gif-player";
  version = "0.2.0";
  pyproject = true;

  src = lib.cleanSource ../.;

  build-system = with python3Packages; [
    setuptools
    wheel
  ];

  dependencies = with python3Packages; [
    pygobject3
    pycairo
    pillow
  ];

  nativeBuildInputs = [
    gobject-introspection
    wrapGAppsHook3
  ];

  buildInputs = [
    gtk3
    gtk-layer-shell
    glib
    gdk-pixbuf
  ];

  dontWrapGApps = true;

  checkPhase = ''
    runHook preCheck
    python -m compileall -q .
    PYTHONPATH=. python -m unittest discover -s tests -v
    python - <<'PY'
    import cairo
    import gi
    from PIL import Image

    for namespace, version in (
        ("Gtk", "3.0"),
        ("Gdk", "3.0"),
        ("GdkPixbuf", "2.0"),
        ("GtkLayerShell", "0.1"),
    ):
        gi.require_version(namespace, version)
    from gi.repository import Gdk, GdkPixbuf, Gtk, GtkLayerShell  # noqa: F401,E402
    print("Python imports and GTK typelibs: OK")
    PY
    runHook postCheck
  '';

  preFixup = ''
    makeWrapperArgs+=("''${gappsWrapperArgs[@]}")
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/home"
    export XDG_RUNTIME_DIR="$TMPDIR/runtime"
    export XDG_CONFIG_HOME="$TMPDIR/config"
    export XDG_CACHE_HOME="$TMPDIR/cache"
    export XDG_DATA_HOME="$TMPDIR/data"
    mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"

    find "$out" -type f -exec sha256sum {} + | sort > "$TMPDIR/out-before"
    "$out/bin/gif-player" --help >/dev/null
    "$out/bin/gif-player" doctor | grep -q 'GTK typelibs: OK'
    "$out/bin/gif-player" self-test | grep -q '"protocol": 2'
    test "$(stat -c %a "$XDG_RUNTIME_DIR/gif-player")" = 700

    test -x "$out/bin/gif-player"
    test -x "$out/bin/gif-picker"
    test -x "$out/bin/gif-control"
    test -f "$out/libexec/gif-player/gif-script.py"
    ! grep -R -E '/usr/bin/python3|~/Scripts/Gif-Overlay' \
      "$out/bin" "$out/libexec/gif-player/gif_player"*.py
    test ! -e "$out/libexec/gif-player/Gifs"

    wayland_error="$(env -u WAYLAND_DISPLAY "$out/bin/gif-player" picker 2>&1 || true)"
    printf '%s\n' "$wayland_error" | grep -q 'WAYLAND_DISPLAY ist nicht gesetzt'

    find "$out" -type f -exec sha256sum {} + | sort > "$TMPDIR/out-after"
    cmp "$TMPDIR/out-before" "$TMPDIR/out-after"
    runHook postInstallCheck
  '';

  meta = {
    description = "GTK3 layer-shell GIF overlay supervisor for Wayland";
    homepage = "https://github.com/xnixjoyer/GIF-Player";
    mainProgram = "gif-player";
    platforms = lib.platforms.linux;
  };
}
