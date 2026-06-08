#!/usr/bin/env python3
"""Hybrid PDF to Markdown converter v3.

Strategy:
1. Pre-scan: detect headers/footers/watermarks by frequency analysis across all pages
2. Filter them out before text extraction
3. pdfplumber: primary table extractor (best for borderless tables)
4. PyMuPDF (fitz): image extraction + text blocks
5. Heuristic: text-pattern table detection as last-resort fallback

Output: output_hybrid/ with mirrored directory structure, extracted images.
"""

import fitz
import os
import re
import sys
from collections import Counter

INPUT_DIR = "clean_pdfs"
OUTPUT_DIR = "output_hybrid"

# ── Special character normalization ──────────────────────────────────────────

def replace_special_chars(text):
    rpl = {"–": "-", "—": "--", "‘": "'", "’": "'", "“": '"', "”": '"',
           "•": "-", "…": "...", " ": " ", "­": "", "™": "(TM)", "®": "(R)",
           "": "-", "−": "-", "ﬁ": "fi", "ﬂ": "fl"}
    for old, new in rpl.items():
        text = text.replace(old, new)
    return text


def clean_watermark_from_text(text, wm_words):
    """Remove watermark substrings from a text block.
    Returns (cleaned_text, is_garbled)."""
    if not wm_words:
        return text, False

    # Check if text is heavily garbled (watermark mixed with content character by character)
    # Garbled text has very short "words" (1-2 chars) and no dictionary words
    words = re.findall(r'[a-zA-Z]{2,}', text)
    if words:
        wm_word_count = sum(1 for w in words if w.lower() in wm_words)
        wm_ratio = wm_word_count / len(words) if words else 0
        if wm_ratio > 0.5:
            return "", True  # heavily garbled, discard entirely

    # Remove known watermark words
    cleaned = text
    for wm in sorted(wm_words, key=len, reverse=True):
        # Case-insensitive replacement
        cleaned = re.sub(r'(?i)' + re.escape(wm), '', cleaned)

    # Clean up extra whitespace
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned, False

# ── Header / Footer / Watermark detection ───────────────────────────────────

def normalize_signature(text):
    """Normalize text for signature comparison: collapse whitespace, remove
    page numbers and standalone digits that vary per page."""
    s = re.sub(r"\s+", " ", text.strip().lower())
    # Remove standalone numbers (page numbers, revision dates)
    s = re.sub(r"\b\d+\b", "#", s)
    # Collapse multiple # placeholders
    s = re.sub(r"#(\s+#)+", "#", s)
    return s


def pre_scan_document(doc):
    """Pre-scan all pages to build:
    - header/footer filter function
    - watermark words set for text cleaning
    """
    all_sigs = []
    body_texts = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_h = page.rect.height
        blocks = page.get_text("blocks")
        for b in blocks:
            if b[6] != 0:
                continue
            text = b[4].strip()
            if not text or len(text) < 2:
                continue
            y_center = (b[1] + b[3]) / 2
            y_ratio = y_center / page_h
            sig = normalize_signature(text)
            if sig:
                all_sigs.append((y_ratio, sig))
            if 0.15 < y_ratio < 0.85:
                body_texts.append(text)

    total_pages = len(doc)

    # Classify by zone
    header_sigs = [s for yr, s in all_sigs if yr < 0.12]
    footer_sigs = [s for yr, s in all_sigs if yr > 0.88]
    body_sigs = [s for yr, s in all_sigs if 0.12 <= yr <= 0.88]

    def frequent_sigs(sig_list, threshold=0.5):
        counts = Counter(sig_list)
        min_pages = max(3, int(total_pages * threshold))
        return {sig for sig, count in counts.items() if count >= min_pages}

    header_filter = frequent_sigs(header_sigs)
    footer_filter = frequent_sigs(footer_sigs)

    watermark_filter = set()
    body_counts = Counter(body_sigs)
    for sig, count in body_counts.items():
        if count >= max(2, int(total_pages * 0.3)) and len(sig) > 10:
            watermark_filter.add(sig)

    all_filters = header_filter | footer_filter | watermark_filter

    # Known watermark patterns
    known_wm_patterns = [
        r"rock\s*cao", r"caoshengming", r"byosoft", r"cnda\d+",
        r"ipla\(\d+\)\d+",
    ]

    def should_filter(text):
        if not text or len(text.strip()) < 2:
            return True
        for pat in known_wm_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return normalize_signature(text) in all_filters

    # Extract watermark words from body text that contains email/domain patterns
    wm_words = set()
    for text in body_texts:
        if re.search(r'@\w+\.\w+|cnda\d+|ipla\(\d+\)', text, re.IGNORECASE):
            tokens = re.findall(r'[a-zA-Z0-9@._-]+', text)
            for tok in tokens:
                if len(tok) >= 3:
                    wm_words.add(tok.lower())

    print(f"  [filter] headers={len(header_filter)} footers={len(footer_filter)} "
          f"watermarks={len(watermark_filter)} wm_words={len(wm_words)}")

    return should_filter, wm_words


def clean_watermark_from_text(text, wm_words):
    """Remove watermark substrings from text. Returns (cleaned_text, is_garbled)."""
    if not text:
        return text, False

    words = re.findall(r'[a-zA-Z]{2,}', text)
    total_alpha = sum(len(w) for w in words)

    # Heuristic: garbled text has low average alphabetic word length
    # (watermark interleaving produces short character fragments)
    if words and total_alpha > 0:
        avg_word_len = total_alpha / len(words)
        # If average word length < 3.5 and we have watermark words, likely garbled
        if avg_word_len < 3.5 and wm_words:
            wm_count = sum(1 for w in words if w.lower() in wm_words)
            if wm_count > 0:
                # Check ratio of legitimate English words
                common_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
                                'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
                                'have', 'from', 'they', 'this', 'that', 'with', 'will',
                                'each', 'which', 'their', 'them', 'other', 'about',
                                'intel', 'core', 'lake', 'data', 'memory', 'system',
                                'power', 'support', 'processor', 'technology', 'specification'}
                real_words = sum(1 for w in words if w.lower() in common_words)
                if real_words == 0 and wm_count >= 2:
                    return "", True  # all words are watermark fragments, no real English

    if not wm_words:
        return text, False

    # Remove watermark words from text
    cleaned = text
    for wm in sorted(wm_words, key=len, reverse=True):
        cleaned = re.sub(r'(?i)' + re.escape(wm), '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

    # After cleaning, if almost nothing left, discard
    if len(cleaned) < 10:
        return "", True

    return cleaned, False


# ── Image extraction (PyMuPDF) ──────────────────────────────────────────────

def extract_images_from_page(page, doc, img_dir, img_rel_dir, page_num):
    """Extract images and return markdown references with correct relative paths."""
    refs = []
    for idx, img_info in enumerate(page.get_images(full=True)):
        try:
            base = doc.extract_image(img_info[0])
            if not base:
                continue
            img_bytes = base["image"]
            ext = base["ext"]
            name = f"page{page_num:04d}_img{idx:03d}.{ext}"
            with open(os.path.join(img_dir, name), "wb") as f:
                f.write(img_bytes)
            if len(img_bytes) > 3072:
                refs.append(f"![{name}]({img_rel_dir}/{name})")
        except Exception:
            continue
    return refs


# ── Table extraction ────────────────────────────────────────────────────────

def extract_tables_from_page(plumber_page, fitz_page):
    """Extract tables: pdfplumber first, PyMuPDF as fallback.
    Returns (markdown_tables, table_y_ranges) where table_y_ranges is a list of
    (y0, y1) tuples for filtering overlapping heuristic table blocks."""
    tables, y_ranges = _tables_pdfplumber(plumber_page)
    if not tables:
        tables, y_ranges = _tables_fitz(fitz_page)
    return tables, y_ranges


def _tables_pdfplumber(page):
    try:
        results = []
        y_ranges = []
        # Use find_tables() for position info (bbox)
        found = page.find_tables()
        for table in found:
            data = table.extract()
            if not data or len(data) < 2:
                continue
            rows = [[(c or "").strip().replace("\n", " ") for c in row]
                    for row in data if row and any(c and c.strip() for c in row)]
            if len(rows) < 2:
                continue
            lines = []
            for i, row in enumerate(rows):
                lines.append("| " + " | ".join(row) + " |")
                if i == 0:
                    lines.append("| " + " | ".join(["---"] * len(row)) + " |")
            results.append("\n".join(lines))
            # pdfplumber bbox: (x0, top, x1, bottom) — same as PyMuPDF (top-left origin)
            # No conversion needed.
            y_ranges.append((table.bbox[1], table.bbox[3]))  # (y0=top, y1=bottom)
        return results, y_ranges
    except Exception:
        return [], []


def _tables_fitz(page):
    try:
        results = []
        y_ranges = []
        for table in page.find_tables():
            data = table.extract()
            if not data or len(data) < 2:
                continue
            rows = [[(str(c) or "").strip().replace("\n", " ") for c in row]
                    for row in data if row and any(c for c in row)]
            if len(rows) < 2:
                continue
            lines = []
            for i, row in enumerate(rows):
                lines.append("| " + " | ".join(row) + " |")
                if i == 0:
                    lines.append("| " + " | ".join(["---"] * len(row)) + " |")
            results.append("\n".join(lines))
            y_ranges.append((table.bbox[1], table.bbox[3]))
        return results, y_ranges
    except Exception:
        return [], []


# ── Text extraction (PyMuPDF) ──────────────────────────────────────────────

def extract_raw_blocks(page, block_filter, wm_words):
    """Extract text blocks, filtering headers/footers/watermarks and cleaning
    watermark text from mixed blocks.

    Blocks are sorted by reading order: column-first (left column before right),
    then top-to-bottom within each column. This preserves the correct text flow
    for multi-column layouts."""
    blocks = page.get_text("blocks")
    result = []
    for b in blocks:
        if b[6] == 0 and b[4].strip():
            text = b[4].strip()
            if block_filter(text):
                continue
            text, is_garbled = clean_watermark_from_text(text, wm_words)
            if is_garbled or not text or len(text) < 2:
                continue
            result.append((b[1], b[0], b[3], text))

    if not result:
        return result

    # Column-aware sorting: detect true multi-column layout (two distinct groups
    # of x-positions separated by at least 100pt), then sort by column first.
    # Only consider body blocks (exclude very top/bottom header/footer regions).
    page_h = page.rect.height
    body_blocks = [b for b in result if 0.12 < b[0] / page_h < 0.88] if result else []
    body_x = sorted(set(b[1] for b in body_blocks)) if body_blocks else []

    is_multi_column = False
    split_x = 0
    for i in range(len(body_x) - 1):
        gap = body_x[i+1] - body_x[i]
        if gap > 100 and body_x[i] > 50 and body_x[i+1] < page.rect.width - 50:
            is_multi_column = True
            split_x = (body_x[i] + body_x[i+1]) / 2
            break

    if is_multi_column and split_x > 0:
        left_col = [b for b in result if b[1] < split_x]
        right_col = [b for b in result if b[1] >= split_x]
        left_col.sort(key=lambda t: (round(t[0], 1), t[1]))
        right_col.sort(key=lambda t: (round(t[0], 1), t[1]))
        result = left_col + right_col
    else:
        result.sort(key=lambda t: (round(t[0], 1), t[1]))

    return result


def group_and_detect_tables(raw_blocks):
    """Detect tables from raw text blocks."""

    def flush_arm_rows():
        nonlocal arm_start, arm_rows
        if arm_rows:
            if len(arm_rows) >= 2:
                arm_table_clusters.append((arm_start, arm_rows))
            else:
                text_blocks.extend(raw_blocks[arm_start:arm_start + len(arm_rows)])
        arm_start = None
        arm_rows = []

    def is_table_row_block(lines):
        if len(lines) < 3:
            return False
        if not all(len(l) < 80 for l in lines):
            return False
        full = "\n".join(lines)
        if "©" in full or "Copyright" in full:
            return False
        if re.match(r"^[ivxlc]+\s*$", lines[0].strip()):
            return False
        if sum(len(l) for l in lines) / len(lines) < 5:
            return False
        return True

    # Pass 1: ARM-style (multi-line blocks)
    text_blocks = []
    arm_table_clusters = []
    arm_start = None
    arm_rows = []

    for i, block in enumerate(raw_blocks):
        lines = block[3].split("\n")
        if is_table_row_block(lines):
            if arm_start is None:
                arm_start = i
                arm_rows = [lines]
            elif i - (arm_start + len(arm_rows)) <= 2:
                arm_rows.append(lines)
            else:
                flush_arm_rows()
                arm_start = i
                arm_rows = [lines]
        else:
            flush_arm_rows()
            text_blocks.append(block)
    flush_arm_rows()

    tables_output = []
    for start_idx, rows in arm_table_clusters:
        col_counts = [len(r) for r in rows]
        mode_count = Counter(col_counts).most_common(1)[0][0]
        if mode_count >= 3:
            lines = []
            for row in rows:
                if len(row) > mode_count:
                    merged = row[:mode_count - 1] + ["<br>".join(row[mode_count - 1:])]
                elif len(row) < mode_count:
                    merged = row + [""] * (mode_count - len(row))
                else:
                    merged = row
                cells = [c.replace("\n", " ").strip() for c in merged]
                lines.append("| " + " | ".join(cells) + " |")
                if len(lines) == 1:
                    lines.append("| " + " | ".join(["---"] * mode_count) + " |")
            tables_output.append("\n".join(lines))
        else:
            for idx in range(start_idx, start_idx + len(rows)):
                if idx < len(raw_blocks):
                    text_blocks.append(raw_blocks[idx])

    # Pass 2: Intel-style (spaced fields across blocks)
    text_blocks.sort(key=lambda t: (round(t[0], 1), t[1]))
    clusters, cur = [], []
    for block in text_blocks:
        if not cur:
            cur.append(block)
        elif block[0] - cur[-1][2] < 20:
            cur.append(block)
        else:
            clusters.append(cur)
            cur = [block]
    if cur:
        clusters.append(cur)

    text_output = []
    for cluster in clusters:
        fields_per_line = []
        for block in cluster:
            fields = re.split(r"\s{2,}", block[3])
            if len(fields) >= 3 and all(len(f.strip()) < 100 for f in fields):
                fields_per_line.append(fields)

        if len(fields_per_line) >= 3:
            col_counts = [len(f) for f in fields_per_line]
            mode_count = Counter(col_counts).most_common(1)[0][0]
            if mode_count >= 3:
                lines = []
                for row in fields_per_line:
                    if len(row) > mode_count:
                        merged = row[:mode_count - 1] + [" ".join(row[mode_count - 1:])]
                    elif len(row) < mode_count:
                        merged = row + [""] * (mode_count - len(row))
                    else:
                        merged = row
                    lines.append("| " + " | ".join(c.strip() for c in merged) + " |")
                    if len(lines) == 1:
                        lines.append("| " + " | ".join(["---"] * mode_count) + " |")
                tables_output.append("\n".join(lines))
                continue

        # Keep each block as its own paragraph to preserve structure
        for b in cluster:
            text_output.append(b[3])

    return text_output, tables_output


def merge_nearby_paragraphs(paras):
    """Extremely conservative merge: only join a block to its predecessor when
    the predecessor clearly ends mid-sentence AND the successor looks like a
    direct continuation (starts lowercase or with a common continuation word).
    Everything else stays separate to preserve PDF structure."""
    if len(paras) < 2:
        return paras

    merged = [paras[0]]
    for p in paras[1:]:
        prev = merged[-1].rstrip()
        # Don't merge if prev ends like a complete sentence or header
        prev_ends_closed = prev.endswith(('.', ':', ';', '!', '?', ')', ']', '}', '"', "'"))
        # Don't merge if prev is very short (likely a label/header)
        prev_short = len(prev) < 30
        # Next starts lowercase or with common sentence continuation
        p_lower_start = len(p) > 0 and p[0].islower()

        if prev_ends_closed or prev_short:
            merged.append(p)
        elif p_lower_start:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


# ── Main conversion ─────────────────────────────────────────────────────────

def convert_page(fitz_page, doc, plumber_page, img_dir, img_rel_dir,
                 page_num, block_filter, wm_words):
    img_refs = extract_images_from_page(fitz_page, doc, img_dir, img_rel_dir, page_num)
    tables, table_y_ranges = extract_tables_from_page(plumber_page, fitz_page)

    raw_blocks = extract_raw_blocks(fitz_page, block_filter, wm_words)

    # Exclude blocks that overlap with already-detected table regions.
    # This prevents the heuristic from re-detecting the same table.
    # y_ranges are already in PyMuPDF coordinates (top-left origin).
    if table_y_ranges:
        filtered_blocks = []
        for block in raw_blocks:
            y0, x0, y1, text = block
            block_in_table = False
            for ty0, ty1 in table_y_ranges:
                if not (y1 < ty0 - 5 or y0 > ty1 + 5):
                    block_in_table = True
                    break
            if not block_in_table:
                filtered_blocks.append(block)
        raw_blocks = filtered_blocks

    clean_paras, heuristic_tables = group_and_detect_tables(raw_blocks)

    # Content-based dedup: remove tables whose non-empty cells substantially
    # overlap with any already-kept table. This catches both heuristic duplicates
    # and pdfplumber duplicates (e.g., tables spanning page boundaries).
    def table_cell_set(t):
        cells = set()
        for line in t.strip().split("\n"):
            if line.startswith("|---"):
                continue
            for cell in line.split("|")[1:-1]:
                stripped = cell.strip()
                if stripped:
                    cells.add(stripped)
        return cells

    # Dedup both heuristic and pdfplumber/fitz tables together
    all_candidates = tables + heuristic_tables
    deduped = []
    existing_cells = []

    for t in all_candidates:
        tc = table_cell_set(t)
        if not tc:
            continue
        is_dup = False
        for ec in existing_cells:
            if not ec:
                continue
            overlap = len(tc & ec) / max(len(tc), len(ec))
            if overlap > 0.6:
                is_dup = True
                break
        if not is_dup:
            deduped.append(t)
            existing_cells.append(tc)

    tables = deduped

    clean_paras = [replace_special_chars(p) for p in clean_paras]
    clean_paras = merge_nearby_paragraphs(clean_paras)

    parts = []
    if clean_paras:
        parts.append("\n\n".join(clean_paras))
    for table in tables:
        parts.append("")
        parts.append(table)
    if img_refs:
        parts.append("")
        parts.extend(img_refs)

    return "\n".join(parts)


def process_pdf(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    pdf_name = os.path.basename(pdf_path)
    stem = os.path.splitext(pdf_name)[0]
    img_dir_name = f"{stem}_images"
    img_dir = os.path.join(out_dir, img_dir_name)
    os.makedirs(img_dir, exist_ok=True)

    doc = fitz.open(pdf_path)

    # Phase 0: detect headers/footers/watermarks
    block_filter, wm_words = pre_scan_document(doc)

    # Open pdfplumber once for the whole file
    try:
        import pdfplumber
        ppdf = pdfplumber.open(pdf_path)
    except Exception:
        ppdf = None

    pages_output = []
    for page_idx in range(len(doc)):
        fitz_page = doc[page_idx]
        plumber_page = ppdf.pages[page_idx] if ppdf and page_idx < len(ppdf.pages) else None
        content = convert_page(fitz_page, doc, plumber_page,
                               img_dir, img_dir_name, page_idx + 1, block_filter, wm_words)
        if content.strip():
            pages_output.append(content)

    doc.close()
    if ppdf:
        ppdf.close()

    full = "\n\n---\n\n".join(pages_output)
    full = re.sub(r"\n{4,}", "\n\n\n", full)

    out_path = os.path.join(out_dir, stem + ".md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full)

    img_count = len(os.listdir(img_dir))
    return out_path, len(pages_output), img_count


def main():
    if len(sys.argv) > 1:
        pdf_files = sys.argv[1:]
    else:
        pdf_files = []
        for root, dirs, files in os.walk(INPUT_DIR):
            for f in sorted(files):
                if f.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(root, f))

    for pdf_path in pdf_files:
        rel = os.path.relpath(pdf_path, INPUT_DIR)
        out_subdir = os.path.join(OUTPUT_DIR, os.path.dirname(rel))
        print(f"Converting: {rel}")
        out, pages, imgs = process_pdf(pdf_path, out_subdir)
        print(f"  -> {pages} pages, {imgs} images")

    print(f"\nDone. Output in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
