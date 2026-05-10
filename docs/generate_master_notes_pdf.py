from __future__ import annotations

from pathlib import Path
import math
import re
import textwrap


ROOT = Path(__file__).resolve().parent
MD_PATH = ROOT / "MemoryLens_Master_Notes.md"
PDF_PATH = ROOT / "MemoryLens_Master_Notes.pdf"


PAGE_W = 595.28  # A4 points
PAGE_H = 841.89
MARGIN_L = 44
MARGIN_R = 44
MARGIN_T = 48
MARGIN_B = 48


def pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def approx_wrap(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    return textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=False,
    ) or [""]


def parse_markdown(md_text: str):
    lines = md_text.splitlines()
    blocks = []
    in_code = False
    code_lines: list[str] = []
    current_list = None

    def flush_list():
        nonlocal current_list
        if current_list:
            blocks.append(("list", current_list))
            current_list = None

    def flush_code():
        nonlocal code_lines
        if code_lines:
            blocks.append(("code", code_lines[:]))
            code_lines = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                in_code = False
                flush_code()
            else:
                flush_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_list()
            blocks.append(("blank", ""))
            continue

        if line.startswith("# "):
            flush_list()
            blocks.append(("h1", line[2:].strip()))
            continue
        if line.startswith("## "):
            flush_list()
            blocks.append(("h2", line[3:].strip()))
            continue
        if line.startswith("### "):
            flush_list()
            blocks.append(("h3", line[4:].strip()))
            continue

        m = re.match(r"^-\s+(.*)$", line)
        if m:
            item = m.group(1).strip()
            if current_list is None:
                current_list = []
            current_list.append(item)
            continue

        flush_list()
        blocks.append(("p", line.strip()))

    if in_code:
        flush_code()
    flush_list()
    return blocks


def make_layout(blocks):
    items = []
    for kind, data in blocks:
        if kind == "blank":
            items.append({"kind": "blank", "height": 8})
            continue
        if kind in {"h1", "h2", "h3", "p"}:
            if kind == "h1":
                size = 20
                font = "bold"
                indent = 0
                width = 78
                before = 14
                after = 8
            elif kind == "h2":
                size = 15
                font = "bold"
                indent = 0
                width = 84
                before = 12
                after = 6
            elif kind == "h3":
                size = 12
                font = "bold"
                indent = 0
                width = 88
                before = 10
                after = 4
            else:
                size = 11
                font = "regular"
                indent = 0
                width = 96
                before = 0
                after = 2
            text = data
            if kind == "p" and text.startswith("**") and text.endswith("**"):
                text = text.strip("*")
                font = "bold"
            wrapped = approx_wrap(text, width)
            items.append(
                {
                    "kind": kind,
                    "font": font,
                    "size": size,
                    "indent": indent,
                    "before": before,
                    "after": after,
                    "lines": wrapped,
                }
            )
            continue
        if kind == "list":
            item_lines = []
            for bullet in data:
                prefix = "- "
                wrapped = approx_wrap(bullet, 88)
                item_lines.append((prefix + wrapped[0], True))
                for extra in wrapped[1:]:
                    item_lines.append(("  " + extra, False))
            items.append(
                {
                    "kind": "list",
                    "font": "regular",
                    "size": 11,
                    "indent": 0,
                    "before": 0,
                    "after": 2,
                    "lines": item_lines,
                }
            )
            continue
        if kind == "code":
            wrapped = []
            for c in data:
                if not c.strip():
                    wrapped.append("")
                else:
                    wrapped.extend(approx_wrap(c, 92))
            items.append(
                {
                    "kind": "code",
                    "font": "mono",
                    "size": 9,
                    "indent": 8,
                    "before": 6,
                    "after": 6,
                    "lines": wrapped,
                }
            )
            continue
    return items


def build_pages(items):
    pages = []
    cur = []
    y = PAGE_H - MARGIN_T

    def line_height(size: int, kind: str):
        if kind == "h1":
            return size * 1.35
        if kind == "h2":
            return size * 1.3
        if kind == "h3":
            return size * 1.25
        if kind == "code":
            return size * 1.45
        if kind == "list":
            return size * 1.32
        return size * 1.28

    def need(height: float):
        nonlocal y, cur
        if y - height < MARGIN_B:
            pages.append(cur)
            cur = []
            y = PAGE_H - MARGIN_T

    for item in items:
        if item["kind"] == "blank":
            need(item["height"])
            cur.append({"kind": "blank", "y": y})
            y -= item["height"]
            continue

        before = item.get("before", 0)
        after = item.get("after", 0)
        lines = item["lines"]
        size = item["size"]
        kind = item["kind"]
        h = before + after + len(lines) * line_height(size, kind)
        need(h)
        y -= before
        if kind in {"h1", "h2", "h3", "p", "code"}:
            for line in lines:
                cur.append(
                    {
                        "kind": kind,
                        "text": line,
                        "size": size,
                        "font": item["font"],
                        "x": MARGIN_L + item.get("indent", 0),
                        "y": y,
                    }
                )
                y -= line_height(size, kind)
        elif kind == "list":
            for text, first in lines:
                cur.append(
                    {
                        "kind": "list",
                        "text": text,
                        "size": size,
                        "font": item["font"],
                        "x": MARGIN_L + 8,
                        "y": y,
                    }
                )
                y -= line_height(size, kind)
        y -= after

    if cur:
        pages.append(cur)
    return pages


def make_pdf(pages):
    font_regular_id = 3
    font_bold_id = 4
    font_mono_id = 5

    total_objects = 5 + len(pages) * 2
    objects: list[str | None] = [None] * total_objects
    objects[0] = "<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = None  # Pages tree placeholder
    objects[2] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    objects[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"

    page_object_ids = []
    for idx, page_items in enumerate(pages):
        content_obj_id = 6 + idx * 2
        page_obj_id = content_obj_id + 1
        page_object_ids.append(page_obj_id)
        content_lines = []
        content_lines.append("BT")
        current_font = None
        for item in page_items:
            if item["kind"] == "blank":
                continue
            font_name = {
                "regular": "F1",
                "bold": "F2",
                "mono": "F3",
            }[item["font"]]
            if current_font != font_name:
                content_lines.append(f"/{font_name} {item['size']} Tf")
                current_font = font_name
            content_lines.append(f"1 0 0 1 {item['x']:.2f} {item['y']:.2f} Tm")
            content_lines.append(f"({pdf_escape(item['text'])}) Tj")
        content_lines.append("ET")
        content = "\n".join(content_lines).encode("utf-8")
        stream = f"<< /Length {len(content)} >>\nstream\n".encode("utf-8") + content + b"\nendstream"
        objects[content_obj_id - 1] = stream.decode("latin1")
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R /F3 {font_mono_id} 0 R >> >> "
            f"/Contents {content_obj_id} 0 R >>"
        )
        objects[page_obj_id - 1] = page_obj

    kids = " ".join(f"{obj} 0 R" for obj in page_object_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>"

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n".encode("utf-8"))
        if isinstance(obj, bytes):
            pdf.extend(obj)
        else:
            pdf.extend((obj or "").encode("utf-8"))
        pdf.extend(b"\nendobj\n")
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects)+1}\n".encode("utf-8"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("utf-8"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "utf-8"
        )
    )
    return bytes(pdf)


def main():
    md_text = MD_PATH.read_text(encoding="utf-8")
    blocks = parse_markdown(md_text)
    items = make_layout(blocks)
    pages = build_pages(items)
    pdf_bytes = make_pdf(pages)
    PDF_PATH.write_bytes(pdf_bytes)
    print(f"Wrote {PDF_PATH}")


if __name__ == "__main__":
    main()
