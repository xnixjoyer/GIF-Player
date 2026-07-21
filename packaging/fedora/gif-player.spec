Name:           gif-player
Version:        0.2.0
Release:        1%{?dist}
Summary:        GTK3 layer-shell GIF overlay supervisor for Wayland
License:        LicenseRef-Unknown
URL:            https://github.com/xnixjoyer/GIF-Player
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3dist(setuptools) >= 69
BuildRequires:  python3dist(wheel)
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils

Requires:       python3-gobject
Requires:       python3-cairo
Requires:       python3-pillow
Requires:       gtk3
Requires:       gtk-layer-shell
Requires:       gobject-introspection

%description
GIF Player displays animated GIF files as GTK3 layer-shell overlays on
compatible Wayland compositors. One supervisor process manages multiple
windows and communicates with clients using a JSON Unix-socket protocol.

The upstream repository currently has no license file. The License tag is
therefore deliberately marked LicenseRef-Unknown and must be resolved before
submission to Fedora's official repositories.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files gif_player_paths gif_player_ipc gif_player_bootstrap gif_player_cli gif_picker_entry gif_control_entry

%check
%{python3} -m compileall -q .
PYTHONPATH=. %{python3} -m unittest discover -s tests -v
PYTHONPATH=%{buildroot}%{python3_sitelib} %{buildroot}%{_bindir}/gif-player --help >/dev/null

desktop-file-validate %{buildroot}%{_datadir}/applications/gif-player-picker.desktop
desktop-file-validate %{buildroot}%{_datadir}/applications/gif-player-control.desktop

test -x %{buildroot}%{_bindir}/gif-player
test -x %{buildroot}%{_bindir}/gif-picker
test -x %{buildroot}%{_bindir}/gif-control
test -f %{buildroot}%{_libexecdir}/gif-player/gif-script.py
test ! -e %{buildroot}%{_libexecdir}/gif-player/Gifs
! grep -R -E '/usr/bin/python3|~/Scripts/Gif-Overlay' \
  %{buildroot}%{_bindir} %{buildroot}%{_libexecdir}/gif-player/*.py

%files -f %{pyproject_files}
%{_bindir}/gif-player
%{_bindir}/gif-picker
%{_bindir}/gif-control
%{_libexecdir}/gif-player/
%{_datadir}/applications/gif-player-picker.desktop
%{_datadir}/applications/gif-player-control.desktop
%{_datadir}/fish/vendor_functions.d/gif.fish
%{_datadir}/fish/vendor_completions.d/gif-player.fish

%changelog
* Tue Jul 21 2026 GIF Player maintainers <noreply@example.invalid> - 0.2.0-1
- Add initial cross-distribution RPM packaging
