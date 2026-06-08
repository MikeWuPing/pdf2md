#!/usr/bin/env python3
"""Step 1: Remove watermark XObjects from PDFs using pikepdf.

Finds all page-level XObject names that ultimately reference the watermark
font (AAAAAB+Helvetica-Bold), then removes the Do commands that draw them
from page content streams. Outputs cleaned PDFs to input_clean/.
"""

import os
import re
import sys
import pikepdf

INPUT_DIR = "input"
OUTPUT_DIR = "clean_pdfs"
WATERMARK_FONT = "AAAAAB+Helvetica-Bold"


def find_watermark_leaves(pdf):
    """Find leaf XObject names that directly contain the watermark font.
    Returns set of full paths like '/Resources/XObject/Fm1'."""
    wm_leaves = set()

    def search(obj, path, depth=0):
        if depth > 20:
            return
        try:
            subtype = str(obj.get('/Subtype', ''))
            if subtype == '/Form' and '/Resources' in obj:
                resources = obj.Resources
                if '/Font' in resources:
                    fonts = resources.Font
                    for font_name in fonts.keys():
                        font = fonts[font_name]
                        bf = str(font.get('/BaseFont', ''))
                        if WATERMARK_FONT in bf:
                            wm_leaves.add(path)
                            return
                if '/XObject' in resources:
                    xobjects = resources.XObject
                    for xo_name in xobjects.keys():
                        search(xobjects[xo_name], f'{path}/{xo_name}', depth + 1)
        except Exception:
            pass

    for page in pdf.pages:
        try:
            if '/Resources' in page and '/XObject' in page.Resources:
                xobjects = page.Resources.XObject
                for name in xobjects.keys():
                    search(xobjects[name], name)
        except Exception:
            pass

    return wm_leaves


def find_page_level_wm_xobjects(pdf):
    """Find page-level XObject names that chain down to watermark leaves.
    Returns set of XObject names like {'/_0', '/_1', '/Jn_0', '/Jn_1'}."""
    wm_leaves = find_watermark_leaves(pdf)
    if not wm_leaves:
        return set()

    page_level_wm = set()

    def leads_to_wm(obj, path, depth=0):
        if depth > 20:
            return False
        try:
            if path in wm_leaves:
                return True
            subtype = str(obj.get('/Subtype', ''))
            if subtype != '/Form':
                return False
            # Check content stream for leaf references
            if hasattr(obj, 'read_bytes'):
                content = obj.read_bytes().decode('latin-1', errors='ignore')
                for leaf in wm_leaves:
                    leaf_name = leaf.rsplit('/', 1)[-1] if '/' in leaf else leaf
                    if leaf_name in content or leaf in content:
                        return True
            # Recurse into nested XObjects
            if '/Resources' in obj and '/XObject' in obj.Resources:
                for xo_name in obj.Resources.XObject.keys():
                    new_path = f'{path}/{xo_name}'
                    if leads_to_wm(obj.Resources.XObject[xo_name], new_path, depth + 1):
                        return True
        except Exception:
            pass
        return False

    for page in pdf.pages:
        try:
            if '/Resources' in page and '/XObject' in page.Resources:
                for name in page.Resources.XObject.keys():
                    if leads_to_wm(page.Resources.XObject[name], name):
                        page_level_wm.add(name)
                        if name.endswith('_1'):
                            page_level_wm.add(name[:-1] + '0')
        except Exception:
            pass

    return page_level_wm


def clean_content_stream(content_bytes, wm_names):
    """Remove watermark Do commands from content stream bytes.
    Returns (new_bytes, was_modified)."""
    text = content_bytes.decode('latin-1', errors='ignore')
    original = text

    for name in sorted(wm_names, key=len, reverse=True):
        escaped = re.escape(name)
        # Pattern: q (or Q q) followed by matrix transform, /Name Do, Q
        pat = (
            r'(?:Q\r\n)?q\r\n'
            r'(?:[\d.\-]+ ){5}[\d.\-]+ cm\r\n'
            + escaped +
            r'\s+Do\r\nQ'
        )
        text = re.sub(pat, '', text)

    if text == original:
        return content_bytes, False

    return text.encode('latin-1', errors='ignore'), True


def process_pdf(input_path, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        import shutil
        print(f"  -> Skipping (cannot open): {e}")
        shutil.copy2(input_path, output_path)
        return False

    wm_names = find_page_level_wm_xobjects(pdf)
    if not wm_names:
        print(f"  -> No watermark XObjects found")
        pdf.save(output_path)
        pdf.close()
        return False

    print(f"  -> Found {len(wm_names)} WM XObject names: {sorted(wm_names)}")

    modified = False
    for page in pdf.pages:
        try:
            if '/Contents' not in page:
                continue
            contents = page.Contents

            # Handle both single stream and array
            if isinstance(contents, pikepdf.Array):
                for stream_ref in contents:
                    stream = stream_ref
                    if hasattr(stream, 'read_bytes'):
                        data = stream.read_bytes()
                        new_data, changed = clean_content_stream(data, wm_names)
                        if changed:
                            modified = True
                            stream.write(new_data)
            elif hasattr(contents, 'read_bytes'):
                data = contents.read_bytes()
                new_data, changed = clean_content_stream(data, wm_names)
                if changed:
                    modified = True
                    contents.write(new_data)
        except Exception as e:
            pass  # skip problematic pages

    if modified:
        pdf.save(output_path)
    else:
        pdf.save(output_path)

    pdf.close()
    return modified


def main():
    if len(sys.argv) > 1:
        pdf_files = sys.argv[1:]
    else:
        pdf_files = []
        for root, dirs, files in os.walk(INPUT_DIR):
            for f in sorted(files):
                if f.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(root, f))

    for pdf_path in pdf_files:
        rel = os.path.relpath(pdf_path, INPUT_DIR)
        out_path = os.path.join(OUTPUT_DIR, rel)
        print(f"Processing: {rel}")
        removed = process_pdf(pdf_path, out_path)
        print(f"  -> {'REMOVED' if removed else 'Not found / copied'}")

    print(f"\nDone. Clean PDFs in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
