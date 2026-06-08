---
name: pdf2md
description: Convert PDF files to Markdown with watermark removal, header/footer filtering, table preservation, and image extraction. Use when converting PDF documents (especially technical specs, datasheets, reference manuals) to clean Markdown format.
---

# PDF2MD — PDF to Markdown Converter

## Overview

Three-step pipeline that converts PDF documents to clean Markdown:

1. **Watermark Removal** — `remove_watermark.py` strips watermark XObjects from PDF internals using pikepdf
2. **Header/Footer Filtering** — frequency-based detection removes repeated headers/footers (built into `convert_hybrid.py`)
3. **Hybrid Conversion** — pdfplumber (tables) + PyMuPDF (images + text) + heuristics → Markdown

## When to Use

- Converting watermarked PDF technical documents (datasheets, EDS, TRM, BIOS specs) to Markdown
- Batch converting PDF libraries with directory structure preservation
- Extracting tables and images from PDFs that MarkItDown cannot handle

**Not for:** scanned PDFs (OCR-based), forms, PDF portfolios

## Quick Start

```bash
# Install dependencies
pip install pikepdf PyMuPDF pdfplumber

# Full pipeline
python remove_watermark.py && python convert_hybrid.py
```

## Architecture

| Component | Technology | Role |
|-----------|-----------|------|
| Watermark removal | pikepdf | Removes Form XObject watermarks (AAAAAB+Helvetica-Bold font) |
| Header/footer filter | frequency analysis | Detects repeated top/bottom text across pages |
| Table extraction | pdfplumber (primary) + PyMuPDF (fallback) | Both bordered and borderless tables |
| Image extraction | PyMuPDF (fitz) | Extracts embedded images to `*_images/` directory |
| Text extraction | PyMuPDF blocks + heuristics | Column-aware sorting, watermark text cleaning |

## Directory Structure

```
pdf2md/
├── remove_watermark.py    # Step 1: watermark removal
├── convert_hybrid.py      # Steps 2+3: filtering + conversion
├── requirements.txt       # Python dependencies
├── input/                 # Place PDF files here
├── clean_pdfs/            # Intermediate: watermark-free PDFs
└── output_hybrid/         # Final Markdown output
    └── path/to/
        ├── document.md
        └── document_images/
```

## Table Detection Strategies

### ARM-style (borderless tables)
Each table row is a single text block with `\n`-separated column cells. The modal column count is detected, and overflow cells are merged with `<br>`.

### Intel-style (spaced-field tables)
Columns are separated by `\s{2,}` across multiple text blocks. Requires ≥3 matching rows for confidence.

## Watermark Removal

Uses `pikepdf` to operate on PDF internals:
- Recursively scan Form XObjects for watermark font (`AAAAAB+Helvetica-Bold`)
- Trace XObject reference chains to find page-level root XObjects
- Regex-remove Do commands from page content streams

The watermark font name can be customized by editing the `WATERMARK_FONT` variable.

## Text Ordering

Blocks are sorted with y-coordinates rounded to 0.1pt precision, then by x-coordinate. This ensures visually same-line blocks are sorted left-to-right. Multi-column pages are detected by ≥100pt x-gaps and sorted column-first.

## Dependencies

```bash
pip install pikepdf PyMuPDF pdfplumber
```

## Limitations

- Encrypted PDFs cannot be processed for watermark removal (copied as-is)
- PDFs with character-level watermark interleaving may have residual garbled text
- Page-spanning tables may have header row repeated on continuation pages
- Vector graphics (block diagrams) are not extracted as images
