.PHONY: test lint run browser

test:
	python -m pytest -q

lint:
	ruff check .
	ruff format --check .

run:
	python -m liteclaw

browser:
	python scripts/check_browser.py
