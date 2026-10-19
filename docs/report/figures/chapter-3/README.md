# Chapter 3 figure assets

This directory contains editable vector sources and PNG previews for the
Chapter 3 figures. The approved figures are embedded in
`../../chapter-3-system-design-and-methodology.md`. LaTeX-ready figure blocks
are preserved separately in `../../latex/chapter-3-figure-blocks.tex`.

## Figure set

| Final figure | Preserved asset stem | Format and role | Placement |
|---|---|---|---|
| 3.1 | `figure-3-1-overall-system-architecture` | Polished colour architecture overview | After the overall architecture subsection |
| 3.2 | `figure-3-2-canonical-traceability.md` | Monospace text in a Markdown code block; no image rendering | After data normalisation and traceability |
| 3.3 | `figure-3-6-storage-organization` | Three-column storage organisation diagram | After the three storage representations |
| 3.4 | `figure-3-3-retrieval-system-flowcharts` | Aligned monochrome R1/R2/R3 flowchart | After the three retrieval systems |
| 3.5 | `figure-3-4-evidence-validation-and-answerer` | Aligned monochrome validation and handoff flowchart | After EvidenceBundle and Answerer |
| 3.6 | `figure-3-5-e7-fusion-vs-full-context` | Polished colour comparison | After E7 and Full Context |

The storage-organisation figure is retained because storage representation
is a central experimental variable. It follows the explanatory idea used in the
Filesystem-Based Memory paper, while showing the actual frozen S1/S2/S3
stores in this project. It does not reproduce the paper's example or reveal
any candidate answer.

The asset stems preserve the working numbers used during figure review. Final
publication numbers follow first appearance in the chapter. This avoids
renaming the approved source assets while keeping the report numbering in
strict ascending order.

## Editable sources

Figures 3.1 and 3.3–3.6 are stored as SVGs and can be edited in Figma,
Illustrator, Inkscape, Affinity Designer, or any text editor. The PNG file
with the same stem is a preview and can be used for quick review. Figure 3.2
is deliberately stored as Markdown source so it renders as a restrained
monospace code block rather than as an image.

- Polished figures use a 1600 × 900 SVG canvas and the Chapter 1–2 visual
  language: navy, teal, amber, rounded cards, and restrained shadows.
- Figure 3.6 uses the same 1600 × 900 editable canvas.
- The monochrome flowcharts use larger task-specific canvases to preserve
  alignment and legibility when placed on a report page.

## Reproduction

The rendered figures are generated deterministically by three scripts:

```bash
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter3_polished.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter3_supporting.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter3_flowcharts.js
```

The SVG files are the canonical editable assets for rendered figures. PNG
previews are rendered from those SVGs using `sharp`. The Markdown file is the
canonical Figure 3.2 asset and requires no generator.

## Accuracy notes

- Figure 3.6 reflects the frozen stores used by the experiment: S1 contains
  30 flat session files; S2 contains the same 30 byte-identical file bodies
  under four topic directories; S3 contains two entity files, 35 H2 topic
  groups, and 390 provenance-bearing facts.
- Figure 3.5 treats Full Context as a diagnostic evidence-access path, not as
  a new memory store and not as an oracle.
- Figure 3.3 shows `finish_search` as the handoff that terminates retrieval and
  returns an EvidenceBundle; it is not the Answerer itself.
