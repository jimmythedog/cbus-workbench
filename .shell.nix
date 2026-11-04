{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [
      ps.pyside6
      ps.pyyaml
    ]))
    pkgs.bashInteractive
    pkgs.uv
    pkgs.ruff
  ];

  UV_PYTHON_DOWNLOADS = "never";
  QT_QPA_PLATFORM = "xcb";
}
