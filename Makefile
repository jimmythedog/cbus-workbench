.PHONY: test lint format check

.DEFAULT_GOAL := help
TEST_ARGS = -m unittest discover -s tests

# Use Nix-provided Python on NixOS, uv elsewhere.
ifeq ($(wildcard /etc/NIXOS),/etc/NIXOS)
    RUN = nix-shell .shell.nix --run 'python main.py'
    TEST = nix-shell .shell.nix --run 'QT_QPA_PLATFORM=offscreen python $(TEST_ARGS)'
else
    RUN = uv run python main.py
    TEST = QT_QPA_PLATFORM=offscreen uv run python $(TEST_ARGS)'
endif

run:
	$(RUN)

test:
	$(TEST)

lint:
	ruff check .

lint-fix:
	ruff check . --fix

format:
	ruff format .

check: test lint
	ruff format --check .
	git diff --check

help:
	@echo "Available targets:"
	@echo "  make run      Run the application"
	@echo "  make test     Run all tests"
	@echo "  make lint     Check code with Ruff"
	@echo "  make lint-fix Fix code with Ruff"
	@echo "  make format   Format code with Ruff"
	@echo "  make check    Run tests, lint and formatting checks"
