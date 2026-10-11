.PHONY: all clean fix format format-check lint lint-fix type

CMD:=poetry run
PYMODULE:=ferrybot

all: type format lint
fix: format lint-fix

format:
	$(CMD) ruff format $(PYMODULE)

format-check:
	$(CMD) ruff format --check $(PYMODULE)

lint:
	$(CMD) ruff check $(PYMODULE)

lint-fix:
	$(CMD) ruff check --fix $(PYMODULE)

type:
	$(CMD) mypy $(PYMODULE)

clean:
	git clean -Xdf # Delete all files in .gitignore