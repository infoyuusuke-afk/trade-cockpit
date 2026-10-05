"""Build the Word master from the Markdown master.

The two files are the same blocks in the same order. This script does not
invent sections and does not submit orders.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = ROOT / "docs" / "100oku" / "100億PROJECT_MASTER_SPEC.md"
DOCX = ROOT / "docs" / "100oku" / "100億PROJECT_MASTER_SPEC.docx"
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def blocks(text: str) -> list:
    rows = text.splitlines()
    found = []
    index = 0
    while index < len(rows):
        line = rows[index]
        if line.startswith("```"):
            index += 1
            body = []
            while index < len(rows) and not rows[index].startswith("```"):
                body.append(rows[index])
                index += 1
            found.append(("code", "\n".join(body)))
            index += 1
            continue
        if line.startswith("|"):
            table = []
            while index < len(rows) and rows[index].startswith("|"):
                cells = [cell.strip() for cell in rows[index].strip().strip("|").split("|")]
                if not all(set(cell) <= set("-: ") and cell for cell in cells):
                    table.append(cells)
                index += 1
            found.append(("table", table))
            continue
        if line.startswith("### "):
            found.append(("heading", 3, line[4:].strip()))
        elif line.startswith("## "):
            found.append(("heading", 2, line[3:].strip()))
        elif line.startswith("# "):
            found.append(("heading", 1, line[2:].strip()))
        elif line.startswith("- "):
            found.append(("bullet", line[2:].strip()))
        elif line.strip():
            found.append(("paragraph", line.strip()))
        index += 1
    return found


def write_docx(markdown_path: Path, docx_path: Path) -> None:
    from docx import Document

    document = Document()
    for block in blocks(markdown_path.read_text(encoding="utf-8")):
        kind = block[0]
        if kind == "heading":
            document.add_heading(block[2], level=block[1])
        elif kind == "paragraph":
            document.add_paragraph(block[1])
        elif kind == "bullet":
            document.add_paragraph(block[1], style="List Bullet")
        elif kind == "code":
            document.add_paragraph(block[1])
        elif kind == "table":
            table_rows = block[1]
            width = max(len(row) for row in table_rows)
            table = document.add_table(rows=len(table_rows), cols=width)
            for row_index, row in enumerate(table_rows):
                for col_index in range(width):
                    value = row[col_index] if col_index < len(row) else ""
                    table.rows[row_index].cells[col_index].text = value
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(docx_path)


def _cell_text(cell) -> str:
    texts = []
    for node in cell.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if name == "t":
            texts.append(node.text or "")
        elif name in {"br", "cr"}:
            texts.append("\n")
    return "".join(texts).strip()


def read_docx_blocks(docx_path: Path) -> list:
    with zipfile.ZipFile(docx_path) as package:
        xml = package.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    body = root.find("w:body", WORD_NS)
    found = []
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            style = child.find("./w:pPr/w:pStyle", WORD_NS)
            style_name = "" if style is None else style.attrib.get(f"{{{WORD_NS['w']}}}val", "")
            text = _cell_text(child)
            if not text:
                continue
            if style_name == "Heading1":
                found.append(("heading", 1, text))
            elif style_name == "Heading2":
                found.append(("heading", 2, text))
            elif style_name == "Heading3":
                found.append(("heading", 3, text))
            elif style_name == "ListBullet":
                found.append(("bullet", text))
            else:
                found.append(("paragraph", text))
        elif tag == "tbl":
            table = []
            for row in child.findall("./w:tr", WORD_NS):
                table.append([_cell_text(cell) for cell in row.findall("./w:tc", WORD_NS)])
            found.append(("table", table))
    return found


def main() -> None:
    write_docx(MARKDOWN, DOCX)


if __name__ == "__main__":
    main()
