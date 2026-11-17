.PHONY: test lint format check mdfs user-guide

.DEFAULT_GOAL := help
TEST_ARGS = -m tests discover -s tests -b -q
MMC_VERSION ?=

# Use Nix-provided Python on NixOS, uv elsewhere.
ifeq ($(wildcard /etc/NIXOS),/etc/NIXOS)
    RUN = nix-shell .shell.nix --run 'python main.py'
    TEST = nix-shell .shell.nix --run 'QT_QPA_PLATFORM=offscreen python $(TEST_ARGS)'
    FETCH_MDFS = nix-shell .shell.nix --run 'python scripts/fetch_mdfs.py $(if $(MMC_VERSION),--version "$(MMC_VERSION)")'
    BUILD_USER_GUIDE = nix-shell .shell.nix --run 'python scripts/build_user_guide.py'
else
    RUN = uv run python main.py
    TEST = QT_QPA_PLATFORM=offscreen uv run python $(TEST_ARGS)
    FETCH_MDFS = uv run python scripts/fetch_mdfs.py $(if $(MMC_VERSION),--version "$(MMC_VERSION)")
    BUILD_USER_GUIDE = uv run python scripts/build_user_guide.py
endif

run:
	$(RUN)

mdfs:
	$(FETCH_MDFS)

user-guide:
	$(BUILD_USER_GUIDE)

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
	@echo "  make run        Run the application"
	@echo "  make mdfs       Fetch pinned MMC MDFs (optional MMC_VERSION=<tag>)"
	@echo "  make user-guide Build the offline HTML user guide"
	@echo "  make test       Run all tests"
	@echo "  make lint       Check code with Ruff"
	@echo "  make lint-fix   Fix code with Ruff"
	@echo "  make format     Format code with Ruff"
	@echo "  make check      Run tests, lint and formatting checks"
