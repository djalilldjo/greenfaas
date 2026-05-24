#!/bin/bash
# Build GreenFaaS paper(s).
#
# Usage:
#   ./build.sh                  # both versions
#   ./build.sh acm              # paper.tex only (conference, two-column)
#   ./build.sh elsevier         # paper_elsevier.tex only (Elsevier journal preprint)
#
set -e
cd "$(dirname "$0")"

build_one() {
  local stem="$1"
  echo "================================================================"
  echo "Building $stem.pdf"
  echo "================================================================"
  echo "[1/4] pdflatex (first pass)..."
  pdflatex -interaction=nonstopmode "$stem.tex" > /dev/null
  echo "[2/4] bibtex..."
  bibtex "$stem" 2>&1 | grep -v "Warning--" | head -10 || true
  echo "[3/4] pdflatex (second pass)..."
  pdflatex -interaction=nonstopmode "$stem.tex" > /dev/null
  echo "[4/4] pdflatex (third pass)..."
  pdflatex -interaction=nonstopmode "$stem.tex" > /dev/null

  pages=$(pdfinfo "$stem.pdf" 2>/dev/null | grep "Pages:" | awk '{print $2}')
  size=$(ls -la "$stem.pdf" | awk '{print $5}')
  echo "  -> $stem.pdf  ($pages pages, $size bytes)"
}

target="${1:-both}"
case "$target" in
  acm)      build_one paper ;;
  elsevier) build_one paper_elsevier ;;
  final)    build_one paper_elsevier_final ;;
  all)      build_one paper ; build_one paper_elsevier ; build_one paper_elsevier_final ;;
  both)     build_one paper ; build_one paper_elsevier ;;
  *)        echo "Unknown target: $target. Use acm, elsevier, final, both, or all." ; exit 1 ;;
esac
