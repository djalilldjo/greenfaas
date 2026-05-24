# GreenFaaS — LaTeX Manuscript

This directory contains the consolidated LaTeX source for the GreenFaaS
paper. Two top-level builds are provided:

- `paper.tex` — generic two-column article layout (good for SoCC,
  e-Energy, IEEE CLOUD camera-ready or for a general-purpose preprint).
- `paper_elsevier.tex` — Elsevier journal review format (single-column,
  line-numbered, 12pt double-spaced), targeting *Future Generation
  Computer Systems* (FGCS) or similar Elsevier venues.

Both share the same section sources (`sections/`), figures
(`figures/`), and bibliography (`references.bib`).

## Building

```
./build.sh             # both review-style PDFs (default)
./build.sh acm         # paper.pdf only (generic two-column)
./build.sh elsevier    # paper_elsevier.pdf only (Elsevier journal review format)
./build.sh final       # paper_elsevier_final.pdf only (Elsevier camera-ready 3-column)
./build.sh all         # all three
```

Each script runs `pdflatex / bibtex / pdflatex / pdflatex` to resolve
cross-references and citations. The page counts are very different
because the Elsevier review format mandates single-column with
line-numbering and double-spacing for reviewer markup; the camera-ready
version (set `\documentclass[final,...]` in `paper_elsevier.tex`) is
tighter and closer to the typeset journal layout.

Requirements: TeX Live 2023 or later with standard packages
(amsmath, amssymb, algorithm, algpseudocode, booktabs, graphicx,
hyperref, natbib, geometry, enumitem, lineno). The Elsevier class
file (`elsevier/elsarticle.cls`) and three BibTeX styles
(`elsevier/elsarticle-num.bst`, `elsarticle-num-names.bst`,
`elsarticle-harv.bst`) are bundled with the project so the Elsevier
build is self-contained.

## Current state

- 10 numbered sections covering all of: introduction, related work,
  motivation, problem formulation, the cold-start carbon trade-off
  lemma, the GreenFaaS algorithm with pseudocode, simulator
  implementation, evaluation, discussion, and conclusion.
- 5 figures: motivation, break-even contour, and three zoomed
  sensitivity sweeps.
- 3 algorithms (top-level scheduler, lemma gate, slot scorer) and
  Lemma 1 (cold-start carbon dichotomy) with full proof.
- 1 main results table and one inline class-policy table.
- 22 bibliography entries covering the carbon-aware scheduling, FaaS
  systems, and online-algorithms literatures.

## Layout

```
latex/
├── paper.tex                 generic two-column article master
├── paper_elsevier.tex        Elsevier journal master
├── references.bib            shared BibTeX bibliography
├── build.sh                  build script for the generic version
├── build-elsevier.sh         build script for the Elsevier version
├── elsevier/                 bundled Elsevier class + BST styles
│   ├── elsarticle.cls
│   ├── elsarticle-num.bst
│   ├── elsarticle-num-names.bst
│   └── elsarticle-harv.bst
├── sections/
│   ├── 00_abstract.tex       (used by paper.tex; has "Abstract." prefix)
│   ├── 00_abstract_body.tex  (used by paper_elsevier.tex; no prefix)
│   ├── 01_introduction.tex
│   ├── 02_related_work.tex
│   ├── 03_motivation.tex
│   ├── 04_problem_formulation.tex
│   ├── 04_3_tradeoff_lemma.tex
│   ├── 05_algorithm.tex
│   ├── 06_simulator.tex
│   ├── 07_evaluation.tex
│   ├── 07_2_1_real_carbon.tex   (real-LWA-carbon validation subsection)
│   ├── 08_discussion.tex
│   └── 09_conclusion.tex
└── figures/                  PNG figures copied from ../figures/
```

## Switching the target journal

Inside `paper_elsevier.tex`, change `\journal{Future Generation Computer
Systems}` to the target journal name. Other Elsevier venues plausible
for this work: *Sustainable Computing: Informatics and Systems*
(supcom), *Performance Evaluation*, *Journal of Parallel and
Distributed Computing* (JPDC), *Future Generation Computer Systems*
(FGCS).

For non-Elsevier venues (ACM SoCC, IEEE CLOUD, USENIX ATC), use
`paper.tex` as the starting point and swap the document class for the
venue's official template; every label uses stable identifiers
(`sec:tradeoff`, `sec:evaluation:topology`, etc.) so cross-references
survive the class change.

## Trimming further

If the camera-ready version exceeds the journal's word count or page
limit:

1. **§2 Related Work** can shrink by merging §2.3's three FaaS-targeted
   subsection paragraphs into a single denser paragraph.
2. **§4.3 Trade-off Lemma** can lose the linear-approximation discussion
   without losing the analytical content.
3. **§7 Evaluation** can drop the per-axis prose for workload intensity
   (§7.7), since that axis has the smallest surprise factor.
