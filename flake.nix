{
  description = "GIF Player - GTK3 Wayland layer-shell GIF overlays";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          gif-player = pkgs.callPackage ./nix/package.nix { };
        in
        {
          inherit gif-player;
          default = gif-player;
        }
      );

      apps = forAllSystems (system: {
        gif-player = {
          type = "app";
          program = "${self.packages.${system}.gif-player}/bin/gif-player";
        };
        default = self.apps.${system}.gif-player;
      });

      checks = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          package = self.packages.${system}.gif-player;
        in
        {
          inherit package;
          cli-smoke = pkgs.runCommand "gif-player-cli-smoke" { nativeBuildInputs = [ package ]; } ''
            export HOME="$TMPDIR/home"
            export XDG_RUNTIME_DIR="$TMPDIR/runtime"
            export XDG_CONFIG_HOME="$TMPDIR/config"
            export XDG_CACHE_HOME="$TMPDIR/cache"
            export XDG_DATA_HOME="$TMPDIR/data"
            mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
            chmod 700 "$XDG_RUNTIME_DIR"
            gif-player --help >/dev/null
            gif-player self-test > report.json
            grep -q '"protocol": 2' report.json
            touch "$out"
          '';
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (pythonPackages: with pythonPackages; [
            pygobject3
            pycairo
            pillow
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.gtk3
              pkgs.gtk-layer-shell
              pkgs.glib
              pkgs.gdk-pixbuf
              pkgs.gobject-introspection
              pkgs.ruff
              pkgs.nixfmt-rfc-style
            ];
            shellHook = ''
              export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
              export GI_TYPELIB_PATH="${pkgs.lib.makeSearchPath "lib/girepository-1.0" [
                pkgs.gtk3
                pkgs.gtk-layer-shell
                pkgs.gdk-pixbuf
              ]}''${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
              echo "GIF Player dev shell: python, GTK3, GtkLayerShell, Cairo, Pillow, ruff, nixfmt"
            '';
          };
        }
      );
    };
}
