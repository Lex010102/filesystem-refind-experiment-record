# Chapter 1 Figure Manifest

This directory is the canonical project location for the figures used in Chapter 1. The report source must reference these project-relative files rather than the image-generation cache.

| Figure | Canonical file | Intended section | Short caption |
|---|---|---|---|
| Figure 1.1 | `figure-1-1-long-term-conversational-memory-challenge.png` | Section 1.1.1 | Long-term conversational memory challenge across multiple sessions |
| Figure 1.2 | `figure-1-2-full-context-vs-selective-retrieval.png` | Section 1.1.2 | Full Context compared with selective retrieval |
| Figure 1.3 | `figure-1-3-storage-retrieval-utilisation-pipeline.png` | Section 1.1.3 | Storage–retrieval–utilisation pipeline and failure points |
| Figure 1.4 | `figure-1-4-research-landscape-and-gap.png` | Section 1.3.4 | Conceptual research landscape and unresolved comparison gap |
| Figure 1.5 | `figure-1-5-study-overview.png` | Section 1.3.5 | High-level overview of the controlled study |

## LaTeX path convention

If the future LaTeX root is `docs/report/main.tex`, use paths such as:

```latex
\includegraphics[width=\textwidth]{figures/chapter-1/figure-1-3-storage-retrieval-utilisation-pipeline.png}
```

If the LaTeX root is placed elsewhere, update `\graphicspath` once rather than renaming or duplicating the image files.

## Preservation rule

- Keep these filenames stable after they are cited in the report.
- Do not reference files under `.codex/generated_images`; that directory is only the generation cache.
- Include this entire directory when committing, archiving, or transferring the report project.
