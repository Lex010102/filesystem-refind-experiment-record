# Formal LaTeX Report Project

This directory is the formal LaTeX edition of the report. Chapters 1--6 are
deterministically migrated from the audited Markdown drafts in `docs/report/`.
The Markdown files remain the prose source of truth during the current writing
phase; the generated files in `chapters/` carry the publication structure.

## Project layout

- `main.tex`: report entry point.
- `config/metadata.tex`: title-page fields to complete before submission.
- `config/preamble.tex`: A4 layout, typography, tables, figures, citations, and
  cross-reference configuration.
- `frontmatter/`: title page and abbreviation list.
- `chapters/`: generated LaTeX for Chapters 1--6.
- `bibliography/references.bib`: the 14 references cited in Chapters 1--6.
- `scripts/migrate_markdown_to_latex.py`: deterministic Markdown-to-LaTeX
  migration, including labels and citation conversion.
- `scripts/build.sh`: XeLaTeX/latexmk or Tectonic build entry point.
- `migration-manifest.json`: source and output hashes plus migration counts.
- `build/`: generated PDF and compiler intermediates; not a prose source.

The approved report figures remain in `../figures/chapter-*`. The LaTeX files
refer to those assets directly, so there is no duplicate image tree to drift.

## Build

From this directory:

```sh
make pdf
```

The command first regenerates Chapters 1--6, compiles `build/main.pdf`, and
publishes `../../../output/pdf/memory-bench-report-chapters-1-6.pdf`. The build
script prefers `latexmk` with XeLaTeX and falls back to Tectonic. A standalone
Tectonic executable can also be supplied explicitly:

```sh
TECTONIC_BIN=/absolute/path/to/tectonic make pdf
```

To regenerate only the chapter files:

```sh
make migrate
```

## Migration rules

The migration script performs the following controlled transformations:

1. removes duplicated numeric prefixes from Markdown headings and assigns stable
   chapter/section labels;
2. converts frozen `[1]`--`[14]` citations to BibTeX keys;
3. turns approved images and the two text flowcharts into numbered figures;
4. turns Markdown table titles into numbered, compact portrait `longtable`
   captions and labels;
5. preserves the intentional Figure 4.2 gap, so the error-attribution flow remains
   Figure 4.3;
6. keeps every figure and table on an A4 portrait page, with wrapped columns,
   compact type, and no per-table forced page break;
7. converts direct Chapter, Section, Figure, and Table references to LaTeX
cross-references where the target is already present in Chapters 1--6.

## Compact Chapter 1--6 edition

The current layout is designed to keep the complete audited content of Chapters
1--6 below 50 pages without introducing landscape pages. It uses narrow but
printable A4 margins, 7.2pt body text, 5pt table text, compact heading and
caption spacing, smaller figure bounds, and compact front-matter pagination.
Running headers, footers, and page numbers are suppressed. The front matter
contains the title page and section-level table of contents only; separate
lists of figures, tables, abbreviations, and symbols are omitted. All numbered
headings remain in the chapters and in the PDF bookmarks.

Do not edit generated chapter files directly. Edit the corresponding Markdown
draft and rerun `make migrate`. Manual publication-only overrides should be added
to the migration script so that the transformation remains reproducible.

## Remaining front and back matter

The current project deliberately migrates only the completed Chapters 1--6 and
their bibliography. The declaration, acknowledgements, abstract, Chapters 7--9,
and the formal appendices should be added when their source text is complete.
Appendix references already present in the prose remain textual until those
appendices receive stable LaTeX labels.
