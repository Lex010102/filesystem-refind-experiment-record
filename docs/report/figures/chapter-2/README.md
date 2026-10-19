# Chapter 2 Figure Manifest

This directory is the canonical project location for the rendered figures used in Chapter 2. Every figure has a publication PNG and a matching editable SVG. Figures 2.2 and 2.3 are generated deterministically by `generate_chapter2_figures.js`. Figures 2.1 and 2.4 are monochrome FigJam flowcharts exported after manual layout refinement.

| Figure | Canonical file | Intended section | Short caption |
|---|---|---|---|
| Figure 2.1 | `figure-2-1-long-term-memory-lifecycle-and-failure-stages.png` | Section 2.1.3 | Long-term memory lifecycle and failure-stage diagnosis |
| Figure 2.2 | `figure-2-2-filesystem-refind-full-context-access-paths.png` | Section 2.5.5 | Filesystem, ReFind-style, and Full Context access paths |
| Figure 2.3 | `figure-2-3-locomo-multi-session-evidence-structure.png` | Section 2.6.3 | LoCoMo sessions, question categories, and source-turn annotations |
| Figure 2.4 | `figure-2-4-evaluation-families-across-pipeline.png` | Section 2.7.5 | Observation points of answer, evidence, and process metrics |

## Asset specification

- Rendered assets: Figures 2.1–2.4.
- Canvas: Figures 2.2 and 2.3 use 1672 × 941 pixels (16:9). Figures 2.1 and 2.4 use content-fitted portrait canvases exported at 2× resolution from FigJam.
- Background: Figures 2.1 and 2.4 use an opaque near-white `#FAFAFA` background for reliable display in Markdown, PDF, and LaTeX renderers.
- Style: Figures 2.1 and 2.4 use monochrome line art; Figures 2.2 and 2.3 use the navy, teal, amber, red, and violet visual language of Chapter 1.
- Source: each figure has an editable SVG. Figures 2.2 and 2.3 additionally have a deterministic JavaScript generator; Figures 2.1 and 2.4 retain their fully editable FigJam source board.
- Integrity: `SHA256SUMS` covers every canonical rendered PNG and SVG asset.

Figures 2.1 and 2.4 are single connected flowcharts rather than row-based comparison layouts. Figure 2.1 follows one lifecycle spine with maintenance and failure branches. Figure 2.4 follows one answer-generation pipeline with Full Context and evaluation branches. Both use a black, white, and grey line-art theme. Earlier rendered alternatives are retained under `archive/` for provenance.

## LaTeX path convention

If the future LaTeX root is `docs/report/main.tex`, use paths such as:

```latex
\includegraphics[height=0.82\textheight]{figures/chapter-2/figure-2-1-long-term-memory-lifecycle-and-failure-stages.png}
```

If the LaTeX root is placed elsewhere, update `\graphicspath` once rather than renaming or duplicating the image files.

Use the portrait figures with a height constraint and the 16:9 figures with a width constraint. The SVG files are the local editable vector snapshots; the FigJam board is the live editable source for Figures 2.1 and 2.4.

## Preservation rule

- Keep the canonical filenames stable after they are cited in the report.
- Keep each canonical PNG together with its matching SVG source, this manifest, the generator, and `SHA256SUMS`.
- Include this entire directory when committing, archiving, or transferring the report project.
