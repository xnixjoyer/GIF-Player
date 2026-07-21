# Cross-distribution packaging

GIF Player keeps one shared Python wheel definition in `pyproject.toml` while preserving the existing GTK3 supervisor, JSON IPC v2, XDG paths, runtime patches, profiles, multiple instances, and Nix flake.

## Fedora

The RPM recipe is `packaging/fedora/gif-player.spec`.

```console
sudo dnf install rpm-build python3-devel pyproject-rpm-macros \
  python3-setuptools python3-wheel desktop-file-utils \
  python3-gobject python3-cairo python3-pillow gtk3 gtk-layer-shell \
  gobject-introspection

mkdir -p ~/rpmbuild/{SOURCES,SPECS}
tar --exclude-vcs --exclude='./dist' --exclude='./build' \
  --transform 's,^,gif-player-0.3.0/,' \
  -czf ~/rpmbuild/SOURCES/gif-player-0.3.0.tar.gz .
cp packaging/fedora/gif-player.spec ~/rpmbuild/SPECS/
rpmbuild -ba ~/rpmbuild/SPECS/gif-player.spec
sudo dnf install ~/rpmbuild/RPMS/noarch/gif-player-*.noarch.rpm
```

## Arch Linux

The Arch recipe is `packaging/arch/PKGBUILD`; `.SRCINFO` is committed for repository tooling.

```console
cd packaging/arch
makepkg --syncdeps --cleanbuild
sudo pacman -U gif-player-*.pkg.tar.zst
```

## Installed layout

```text
/usr/bin/gif-player
/usr/bin/gif-picker
/usr/bin/gif-control
/usr/libexec/gif-player/gif-script.py
/usr/libexec/gif-player/gif-picker.py
/usr/libexec/gif-player/gif-control.py
/usr/share/applications/
/usr/share/fish/vendor_functions.d/
/usr/share/fish/vendor_completions.d/
```

Python modules are installed in the distribution's normal site-packages directory. The bootstrap locates the legacy GTK implementation through the platform data prefix, so `/usr/libexec/gif-player` works for Fedora and Arch while the existing package-local Nix layout continues to work.

No GIF files, user configuration, cache, state, profile, socket, lock, or log files are bundled into packages. Runtime data continues to use XDG paths.

## License status

The repository currently has no license file. RPM and Arch metadata therefore use an explicit unresolved/custom license marker. This must be resolved before submission to official Fedora or Arch repositories.

## CI

`.github/workflows/cross-distro.yml` builds and inspects:

- the shared Python wheel,
- a Fedora 44 RPM,
- an Arch Linux package.

The existing Nix workflow remains authoritative for the flake and Nix profile installation.
