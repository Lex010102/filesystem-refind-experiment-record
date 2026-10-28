#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD_DIR="$PROJECT_DIR/build"
DELIVERY_DIR="$PROJECT_DIR/../../../output/pdf"
mkdir -p "$BUILD_DIR"
cd "$PROJECT_DIR"

if command -v latexmk >/dev/null 2>&1; then
  latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error \
    -outdir="$BUILD_DIR" main.tex
elif command -v tectonic >/dev/null 2>&1; then
  tectonic main.tex --outdir "$BUILD_DIR" --keep-logs --keep-intermediates
elif [ -n "${TECTONIC_BIN:-}" ] && [ -x "$TECTONIC_BIN" ]; then
  "$TECTONIC_BIN" main.tex --outdir "$BUILD_DIR" --keep-logs --keep-intermediates
else
  echo "No LaTeX compiler found. Install latexmk + XeLaTeX or Tectonic, or set TECTONIC_BIN." >&2
  exit 127
fi

mkdir -p "$DELIVERY_DIR"
cp "$BUILD_DIR/main.pdf" "$DELIVERY_DIR/memory-bench-report-chapters-1-6.pdf"

echo "Built $BUILD_DIR/main.pdf"
echo "Published $DELIVERY_DIR/memory-bench-report-chapters-1-6.pdf"
