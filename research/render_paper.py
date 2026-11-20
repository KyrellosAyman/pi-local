"""Render the versioned Pi Local paper using the checked-in Markdown source."""

from argparse import ArgumentParser
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


HERE = Path(__file__).resolve().parent
TITLE = "Pi Local: A Desktop Harness for Local Inference and Recoverable Agent Work"
AUTHOR = "KyrellosAyman"
INK = colors.HexColor("#171f29")
ACCENT = colors.HexColor("#185b57")
RULE = colors.HexColor("#cedbdc")
TINT = colors.HexColor("#eff5f5")


def style(name, font, size, leading, **kwargs):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=INK, **kwargs)


BODY = style("Body", "Times-Roman", 11, 15.2, spaceAfter=8, allowWidows=False)
HEADINGS = {
    "h1": style("Title", "Times-Bold", 27, 29, alignment=TA_CENTER, spaceAfter=13, keepWithNext=True),
    "h2": style("Section", "Times-Bold", 15, 18, spaceBefore=14, spaceAfter=6, keepWithNext=True),
    "h3": style("Subsection", "Times-Bold", 12, 15, spaceBefore=9, spaceAfter=4, keepWithNext=True),
}
CELL = style("Cell", "Helvetica", 8.8, 11.5)
LABEL = style("Label", "Helvetica-Bold", 8.8, 11.5)


def render(source, destination, version):
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = markdown.parse(source)
    doc = SimpleDocTemplate(str(destination), pagesize=A4, title=TITLE, author=AUTHOR,
                            subject=f"Pi Local research report, version {version}",
                            leftMargin=65, rightMargin=65, topMargin=64, bottomMargin=57)
    flow = []
    table = None
    for index, token in enumerate(tokens):
        if token.type == "table_open":
            table = []
        elif token.type == "tr_open":
            table.append([])
        elif token.type == "table_close":
            layout = Table(table, colWidths=[doc.width / len(table[0])] * len(table[0]), repeatRows=1,
                           hAlign="LEFT")
            layout.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TINT),
                ("LINEABOVE", (0, 0), (-1, 0), .8, ACCENT),
                ("LINEBELOW", (0, 0), (-1, 0), .5, RULE),
                ("LINEBELOW", (0, -1), (-1, -1), .5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flow.extend((layout, Spacer(1, 10)))
            table = None
        elif token.type == "inline":
            parent = tokens[index - 1]
            html = markdown.renderer.renderInline(token.children, markdown.options, {})
            html = html.replace("<code>", '<font face="Courier">').replace("</code>", "</font>")
            if table is not None:
                table[-1].append(Paragraph(html, LABEL if parent.tag == "th" else CELL))
            else:
                flow.append(Paragraph(html, HEADINGS.get(parent.tag, BODY)))

    def decorate(page, document):
        width, height = A4
        page.setStrokeColor(RULE)
        page.line(65, height - 41, width - 65, height - 41)
        page.line(65, 44, width - 65, 44)
        page.setFont("Helvetica", 8)
        page.setFillColor(ACCENT)
        page.drawString(65, height - 34, "PI LOCAL RESEARCH REPORT")
        page.drawRightString(width - 65, height - 34, f"VERSION {version}")
        page.drawString(65, 32, "KyrellosAyman  /  Pi Local")
        page.drawRightString(width - 65, 32, str(document.page))

    def canvas(path, **kwargs):
        kwargs.update(invariant=True, pageCompression=True)
        return Canvas(path, **kwargs)

    doc.build(flow, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=canvas)


def main():
    cli = ArgumentParser(description=__doc__)
    cli.add_argument("version")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--check", action="store_true", help="Verify the saved PDF against a fresh render.")
    args = cli.parse_args()
    source = (HERE / "PAPER.md").read_text(encoding="utf-8")
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version) or f"Version {args.version} •" not in source:
        cli.error("The three-part version must match the paper's version line.")
    destination = args.output or HERE / f"pi-local-v{args.version}.pdf"
    if args.check:
        with TemporaryDirectory() as directory:
            candidate = Path(directory) / "paper.pdf"
            render(source, candidate, args.version)
            if candidate.read_bytes() != destination.read_bytes():
                cli.error("The saved PDF differs from a fresh render.")
    else:
        render(source, destination, args.version)
    print(destination)


if __name__ == "__main__":
    main()
