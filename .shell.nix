{
  pkgs ? import <nixpkgs> { },
}:

pkgs.mkShell {
  packages = with pkgs; [
    python3
    uv
  ];

  # Use the Python interpreter provided by Nix.
  UV_PYTHON_DOWNLOADS = "never";
}
