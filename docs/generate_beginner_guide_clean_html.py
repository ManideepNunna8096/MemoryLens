from __future__ import annotations

from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
MD_PATH = ROOT / "MemoryLens_Beginner_Project_Guide.md"
HTML_PATH = ROOT / "MemoryLens_Beginner_Project_Guide_Clean.html"


def inline_markup(text: str) -> str:
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    first = lines[index].strip()
    second = lines[index + 1].strip()
    return first.startswith("|") and first.endswith("|") and re.match(r"^\|[\s:\-|\+]+\|$", second) is not None


def parse_table(lines: list[str], index: int) -> tuple[str, int]:
    header = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
    rows = []
    index += 2
    while index < len(lines):
        line = lines[index].strip()
        if not (line.startswith("|") and line.endswith("|")):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
        index += 1

    parts = ["<table>", "<thead><tr>"]
    for cell in header:
        parts.append(f"<th>{inline_markup(cell)}</th>")
    parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{inline_markup(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts), index


def flush_paragraph(parts: list[str], paragraph: list[str]) -> None:
    if not paragraph:
        return
    text = " ".join(item.strip() for item in paragraph if item.strip())
    if text:
        parts.append(f"<p>{inline_markup(text)}</p>")
    paragraph.clear()


def close_lists(parts: list[str], list_stack: list[str]) -> None:
    while list_stack:
        parts.append(f"</{list_stack.pop()}>")


def ensure_list(parts: list[str], list_stack: list[str], tag: str) -> None:
    if list_stack and list_stack[-1] == tag:
        return
    close_lists(parts, list_stack)
    parts.append(f"<{tag}>")
    list_stack.append(tag)


def markdown_to_html(md_text: str) -> str:
    lines = md_text.splitlines()
    parts: list[str] = []
    paragraph: list[str] = []
    list_stack: list[str] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    index = 0

    while index < len(lines):
        raw = lines[index]
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                cls = "diagram" if code_lang.lower() in {"mermaid"} else "codebox"
                label = "Diagram source" if cls == "diagram" else "Code"
                parts.append(f'<div class="{cls}"><div class="box-label">{label}</div><pre>{escape(chr(10).join(code_lines))}</pre></div>')
                in_code = False
                code_lang = ""
                code_lines = []
            else:
                flush_paragraph(parts, paragraph)
                close_lists(parts, list_stack)
                in_code = True
                code_lang = stripped.strip("`").strip()
                code_lines = []
            index += 1
            continue

        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            flush_paragraph(parts, paragraph)
            close_lists(parts, list_stack)
            index += 1
            continue

        if stripped == "---":
            flush_paragraph(parts, paragraph)
            close_lists(parts, list_stack)
            parts.append('<div class="section-rule"></div>')
            index += 1
            continue

        if is_table_start(lines, index):
            flush_paragraph(parts, paragraph)
            close_lists(parts, list_stack)
            table_html, index = parse_table(lines, index)
            parts.append(table_html)
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_paragraph(parts, paragraph)
            close_lists(parts, list_stack)
            level = min(len(heading.group(1)), 4)
            parts.append(f"<h{level}>{inline_markup(heading.group(2).strip())}</h{level}>")
            index += 1
            continue

        bullet = re.match(r"^\s*-\s+(.*)$", line)
        if bullet:
            flush_paragraph(parts, paragraph)
            ensure_list(parts, list_stack, "ul")
            parts.append(f"<li>{inline_markup(bullet.group(1).strip())}</li>")
            index += 1
            continue

        numbered = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
        if numbered:
            flush_paragraph(parts, paragraph)
            ensure_list(parts, list_stack, "ol")
            parts.append(f"<li>{inline_markup(numbered.group(2).strip())}</li>")
            index += 1
            continue

        close_lists(parts, list_stack)
        paragraph.append(stripped)
        index += 1

    flush_paragraph(parts, paragraph)
    close_lists(parts, list_stack)
    return "\n".join(parts)


def main() -> None:
    body = markdown_to_html(MD_PATH.read_text(encoding="utf-8"))
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MemoryLens Beginner Project Guide</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 16mm 20mm 16mm;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #18202a;
      line-height: 1.45;
      font-size: 11.2pt;
      margin: 0;
      background: #ffffff;
    }}
    h1 {{
      font-size: 27pt;
      line-height: 1.15;
      margin: 0 0 14px;
      color: #111827;
      page-break-after: avoid;
    }}
    h2 {{
      font-size: 19pt;
      margin: 30px 0 10px;
      padding-top: 4px;
      color: #1d4ed8;
      page-break-after: avoid;
    }}
    h3 {{
      font-size: 14.5pt;
      margin: 20px 0 8px;
      color: #0f172a;
      page-break-after: avoid;
    }}
    h4 {{
      font-size: 12.5pt;
      margin: 15px 0 6px;
      color: #334155;
      page-break-after: avoid;
    }}
    p {{
      margin: 0 0 9px;
    }}
    ul, ol {{
      margin: 4px 0 11px 0;
      padding-left: 0;
    }}
    ul {{
      list-style: none;
    }}
    ul li::before {{
      content: "- ";
      font-weight: 700;
      color: #2563eb;
    }}
    ol {{
      list-style-position: inside;
    }}
    li {{
      margin: 3px 0;
      page-break-inside: avoid;
    }}
    code {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 9.7pt;
      background: #eef2ff;
      color: #1e3a8a;
      border-radius: 4px;
      padding: 1px 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 9px 0 15px;
      page-break-inside: avoid;
      font-size: 10.2pt;
    }}
    th {{
      background: #e0ecff;
      color: #0f172a;
      text-align: left;
      font-weight: 700;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 6px 7px;
      vertical-align: top;
    }}
    tr:nth-child(even) td {{
      background: #f8fafc;
    }}
    .section-rule {{
      height: 1px;
      background: #dbe4f0;
      margin: 18px 0;
      page-break-after: avoid;
    }}
    .codebox, .diagram {{
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      background: #f8fafc;
      margin: 10px 0 15px;
      page-break-inside: avoid;
      overflow: hidden;
    }}
    .diagram {{
      background: #f0f9ff;
      border-color: #bae6fd;
    }}
    .box-label {{
      font-size: 9pt;
      font-weight: 700;
      color: #475569;
      padding: 7px 9px 0;
    }}
    pre {{
      margin: 0;
      padding: 8px 9px 10px;
      white-space: pre-wrap;
      font-family: Consolas, "Courier New", monospace;
      font-size: 8.8pt;
      line-height: 1.35;
      color: #0f172a;
    }}
    strong {{
      color: #0f172a;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
