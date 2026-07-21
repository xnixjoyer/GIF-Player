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
  version = "0.1.0";
  pyproject = false;

  src = lib.cleanSource ../.;

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

  buildPhase = ''
    runHook preBuild
    runHook postBuild
  '';

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

  installPhase = ''
    runHook preInstall

    libexec="$out/libexec/gif-player"
    mkdir -p "$libexec" "$out/bin" "$out/share/applications" \
      "$out/share/fish/vendor_functions.d" "$out/share/fish/vendor_completions.d"

    install -m755 gif-script.py gif-picker.py gif-control.py "$libexec/"
    install -m644 gif_player_paths.py gif_player_ipc.py gif_player_bootstrap.py "$libexec/"
    install -m755 gif_player_cli.py gif_picker_entry.py gif_control_entry.py "$libexec/"

    for spec in \
      "gif-player:gif_player_cli.py" \
      "gif-picker:gif_picker_entry.py" \
      "gif-control:gif_control_entry.py"; do
      name="''${spec%%:*}"
      script="''${spec#*:}"
      printf '%s\n' \
        '#!${python3Packages.python.interpreter}' \
        'import runpy, sys' \
        "sys.path.insert(0, '$libexec')" \
        "runpy.run_path('$libexec/$script', run_name='__main__')" \
        > "$out/bin/$name"
      chmod +x "$out/bin/$name"
    done

    install -m644 gif.fish "$out/share/fish/vendor_functions.d/gif.fish"
    install -m644 completions/gif-player.fish \
      "$out/share/fish/vendor_completions.d/gif-player.fish"
    install -m644 data/*.desktop "$out/share/applications/"

    runHook postInstall
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

    ! grep -R -E '/usr/bin/python3|~/Scripts/Gif-Overlay' \
      "$out/bin" "$out/libexec/gif-player/gif_player"*.py

    test ! -e "$out/libexec/gif-player/Gifs"
    env -u WAYLAND_DISPLAY "$out/bin/gif-player" picker 2>&1 \
      | grep -q 'WAYLAND_DISPLAY ist nicht gesetzt'
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
