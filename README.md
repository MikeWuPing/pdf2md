# PDF2MD — PDF to Markdown Converter

> 将 PDF 技术文档（规格书、数据手册、参考手册）批量转换为高质量 Markdown，保留表格结构、提取嵌入图片、自动清除水印。

> Batch convert PDF technical documents (datasheets, reference manuals, specs) to clean Markdown with table preservation, image extraction, and watermark removal.

[中文](#中文) | [English](#english)

---

## 中文

### 项目动机

对于需要将芯片规格书、数据手册、参考手册等 PDF 技术文档转为 Markdown 的工程师而言，Microsoft 的 [MarkItDown](https://github.com/microsoft/markitdown) 在基础文本转换方面表现不错，但在三个关键场景下存在明显短板：

1. **图片提取**——大多数 PDF 中嵌入的图片无法被 MarkItDown 提取，输出中完全没有图片引用
2. **水印处理**——保密文档中的水印文本会与正文交叠，产生大量乱码
3. **表格检测**——ARM TRM 和 Intel EDS 等文档中的无边框寄存器表格经常漏检

PDF2MD 通过三步流水线系统性解决上述问题：先在 PDF 源层面去除水印，再通过频率分析过滤页眉页脚，最后用 pdfplumber + PyMuPDF + 启发式规则三者协作完成转换。

### 核心特性

- **水印去除**：使用 `pikepdf` 在 PDF 内部结构中扫描并移除水印，支持两种形态——嵌入 XObject 的水印（Form XObject，通过 `Do` 命令绘制）和直接绘制在页面内容流中的文本水印（使用独立嵌入子集字体，如 `AAAAAA+FontName-0`）。字体特征均可配置。
- **页眉页脚过滤**：基于频率分析——跨页重复出现在页面顶部/底部的文本块被自动识别并过滤。
- **表格保留**：三路表格检测策略：
    - pdfplumber（主力）处理无边框表格（ARM 指令编码表、Intel 寄存器表）
    - PyMuPDF 处理有边框表格
    - 启发式后备规则处理 pdfplumber 漏检的表格（ARM 风格 `\n` 分列、Intel 风格 `\s{2,}` 分列）
- **图片提取**：提取嵌入图片到 `<文件名>_images/` 子目录。大于 3KB 的图片在 Markdown 中生成引用。
- **目录镜像**：输出目录结构与输入完全一致。
- **文字顺序**：带有浮点容差的栏感知排序——同行块 y 坐标四舍五入到 0.1pt 后按 x 从左到右排列。多栏页面通过 ≥100pt 的水平间距自动识别。
- **水印文本清理**：从混合文本块中移除已知水印词片段。

### 快速开始

```bash
# 安装依赖
pip install pikepdf PyMuPDF pdfplumber

# 将 PDF 放入 input/ 目录
mkdir -p input
cp /path/to/your/pdfs/*.pdf input/

# 运行完整流水线
python remove_watermark.py
python convert_hybrid.py

# 输出在 output_hybrid/
```

### 架构

```
input/                      # PDF 源文件（支持任意嵌套深度）
    └── Spec/
        └── Vendor/Chip/
            └── document.pdf

python remove_watermark.py  # 第一步：水印去除
    input/ → clean_pdfs/

python convert_hybrid.py    # 第二步+第三步：过滤 + 转换
    clean_pdfs/ → output_hybrid/
        └── Spec/Vendor/Chip/
            ├── document.md
            └── document_images/
                ├── page0001_img000.png
                └── page0011_img001.jpeg
```

### 处理流水线

| 步骤 | 脚本 | 引擎 | 作用 |
|------|------|------|------|
| 1 | `remove_watermark.py` | pikepdf | 从 PDF 源码层面移除水印（XObject 型 + 内容流文本型） |
| 2 | 内置 | 频率分析 | 检测并过滤跨页重复的页眉/页脚/水印文本 |
| 3 | `convert_hybrid.py` | pdfplumber + PyMuPDF + 启发式 | 提取文字、表格、图片，组装 Markdown |

### 水印形态说明

PDF 水印可能以两种内部形态存在：
- **XObject 型**：水印打包为 Form XObject，页面内容流通过 `q ... cm /Name Do Q` 命令绘制。递归扫描 XObject 树找水印字体，追溯引用链路后从内容流移除对应 `Do` 命令。
- **内容流文本型**：水印文本直接用特征字体写入页面内容流（常带旋转矩阵斜向平铺）。统计页面字体资源找出独立于正文的嵌入子集字体，定位包含其全部文本块的 `q ... Q` 段并整段移除。

两种形态检测失败时文件原样复制，不会损坏内容。

### 表格检测详解

**ARM 风格（单块多行）**

表格的每一行是一个 PyMuPDF 文本块，列间以 `\n` 分隔。取连续块的列数众数确定表格列数，超出列以 `<br>` 合并入末列。

**Intel 风格（多块空格分列）**

列间以 `\s{2,}` 分隔的多个相邻文本块。要求连续 3 行以上且列数一致才判定为表格，以避免正文中多栏文本被误判。

### 文字排序

PyMuPDF 以浮点数报告块坐标，同行块可能相差不足 0.001pt。PDF2MD 将 y 坐标四舍五入到 0.1pt 后再排序，确保同行块按 x 坐标从左到右正确排列。

多栏页面通过检测正文块之间 ≥100pt 的水平间距自动识别，按「先栏后行」排序。

### 依赖

- Python 3.10+
- pikepdf ≥ 10.0
- PyMuPDF ≥ 1.24
- pdfplumber ≥ 0.11

### 局限性

- **加密 PDF**：无法处理水印去除（原样复制），后续转换不受影响
- **扫描件水印**：水印以纯图像层存在（无文本层的扫描件），无法通过结构分析移除
- **跨页表格**：跨越页面边界的寄存器表，续页上会重复表头行
- **矢量图**：方框图、流水线图等矢量图形不会被提取为图片
- **扫描件 PDF**：不支持（需要 OCR）

### 许可

MIT

---

## English

### Motivation

Converting PDF technical documents to Markdown is a common pain point for engineers who need to search, diff, or feed chip specifications into LLMs. Existing tools like Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) handle basic text well but fall short on three critical fronts:

1. **Image extraction** — MarkItDown produces zero images from most PDFs
2. **Watermark handling** — Confidential watermarks interleave with content, producing garbled output
3. **Table detection** — Borderless register tables (common in ARM TRMs and Intel EDS documents) are missed

PDF2MD addresses all three through a three-step pipeline: watermark removal → header/footer filtering → hybrid extraction (pdfplumber + PyMuPDF + heuristics).

### Features

- **Watermark removal**: Strips watermarks at the PDF source level using `pikepdf`. Two forms are supported — XObject-embedded watermarks (Form XObjects drawn via `Do` commands) and content-stream text watermarks (text drawn directly in the page stream with a distinctive embedded subset font, e.g. `AAAAAA+FontName-0`). Font signatures are customizable.
- **Header/footer filtering**: Frequency-based analysis detects repeated page headers/footers and filters them before text extraction.
- **Table preservation**: Dual-strategy table detection:
    - *pdfplumber* for borderless tables (ARM TRM instruction encodings, Intel register tables)
    - *PyMuPDF* for bordered tables
    - *Heuristic fallback* for ARM-style (newline-separated) and Intel-style (whitespace-separated) patterns
- **Image extraction**: Extracts embedded images to a `*_images/` subdirectory. Images larger than 3KB are referenced in the Markdown output.
- **Directory mirroring**: Output directory structure exactly mirrors the input structure.
- **Text ordering**: Column-aware sorting with floating-point-tolerant y-coordinate alignment ensures correct reading order.
- **Watermark text cleaning**: Removes known watermark substrings from mixed content blocks.

### Quick Start

```bash
# Install dependencies
pip install pikepdf PyMuPDF pdfplumber

# Prepare PDFs in input/
mkdir -p input
cp /path/to/your/pdfs/*.pdf input/

# Run full pipeline
python remove_watermark.py
python convert_hybrid.py

# Output in output_hybrid/
```

### Architecture

```
input/                      # Place PDF files here (any nesting depth)
    └── Spec/
        └── Vendor/Chip/
            └── document.pdf

python remove_watermark.py  # Step 1: Watermark removal
    input/ → clean_pdfs/

python convert_hybrid.py    # Steps 2-3: Filtering + conversion
    clean_pdfs/ → output_hybrid/
        └── Spec/Vendor/Chip/
            ├── document.md
            └── document_images/
                ├── page0001_img000.png
                └── page0011_img001.jpeg
```

### Processing Pipeline

| Step | Script | Engine | Purpose |
|------|--------|--------|---------|
| 1 | `remove_watermark.py` | pikepdf | Remove watermarks from PDF source (XObject-based + content-stream text) |
| 2 | built-in | frequency analysis | Detect and filter repeated headers/footers/watermarks |
| 3 | `convert_hybrid.py` | pdfplumber + PyMuPDF + heuristics | Extract text, tables, and images; assemble Markdown |

### Watermark Forms in Detail

PDF watermarks appear in two internal forms:
- **XObject-embedded**: The watermark is packaged as a Form XObject drawn via `q ... cm /Name Do Q`. The tool recursively scans the XObject tree for the watermark font, traces the reference chain, and removes the corresponding `Do` commands from the content stream.
- **Content-stream text**: Watermark text is written directly into the page content stream (often with a rotation matrix for diagonal tiling). The tool finds the embedded subset font distinct from body fonts in page font resources, locates the `q ... Q` section covering all of its text blocks, and removes the section wholesale.

If neither form matches, the file is copied as-is — no damage to the content.

### Table Detection in Detail

**ARM-style (single-block, multi-line rows)**

Each table row is a PyMuPDF text block with `\n`-separated column cells. The modal column count across consecutive blocks determines the table structure. Overflow cells (multi-line detail text) are merged into the last column with `<br>` separators.

**Intel-style (multi-block, spaced-field rows)**

Columns separated by `\s{2,}` across multiple adjacent text blocks. Requires ≥3 consecutive rows with consistent column counts to avoid false positives.

### Text Ordering

PyMuPDF reports block coordinates with floating-point precision. Same-line blocks may differ by ≤0.001pt in y-coordinate. PDF2MD rounds y-coordinates to 0.1pt before sorting, ensuring visually same-line blocks sort left-to-right by x-coordinate.

Multi-column layouts are detected by finding ≥100pt x-gaps between body text blocks, then sorting column-first, top-to-bottom within each column.

### Requirements

- Python 3.10+
- pikepdf ≥ 10.0
- PyMuPDF ≥ 1.24
- pdfplumber ≥ 0.11

### Limitations

- **Encrypted PDFs**: Cannot be processed for watermark removal (copied as-is)
- **Scanned image watermarks**: Watermarks living purely in the image layer (scans without a text layer) cannot be removed via structural analysis
- **Page-spanning tables**: Register tables that cross page boundaries may have header rows repeated on continuation pages
- **Vector graphics**: Block diagrams, pipeline diagrams, and other vector art are not extracted as images
- **Scanned PDFs**: Not supported (requires OCR)

### License

MIT

---

*Generated with [Claude Code](https://claude.ai/code)*
