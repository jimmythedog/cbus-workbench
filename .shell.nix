{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [
      ps.pyside6
    ]))
    pkgs.bashInteractive
    pkgs.uv
    pkgs.ruff
  ];

  UV_PYTHON_DOWNLOADS = "never";
}
