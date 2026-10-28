SHELL := /bin/sh

.PHONY: all migrate pdf clean

all: pdf

migrate:
	python3 scripts/migrate_markdown_to_latex.py

pdf: migrate
	./scripts/build.sh

clean:
	rm -rf build
