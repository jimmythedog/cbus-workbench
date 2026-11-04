.PHONY: test lint format check

.DEFAULT_GOAL := help

# Use Nix-provided Python on NixOS, uv elsewhere.
ifeq ($(wildcard /etc/NIXOS),/etc/NIXOS)
    RUN = nix-shell .shell.nix --run 'python main.py'
    TEST = nix-shell .shell.nix --run 'python -m unittest discover -s tests'
else
    RUN = uv run python main.py
    TEST = uv run python -m unittest discover -s tests
endif

run:
	$(RUN)

test:
	$(TEST)

lint:
	ruff check .

format:
	ruff format .

check: test lint
	ruff format --check .
	git diff --check

help:
	@echo "Available targets:"
	@echo "  make run     Run the application"
	@echo "  make test    Run all tests"
	@echo "  make lint    Check code with Ruff"
	@echo "  make format  Format code with Ruff"
	@echo "  make check   Run tests, lint and formatting checks"
