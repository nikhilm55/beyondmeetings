"""Create polished PDF briefs from AI-structured meeting Markdown."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .library import resolve_markdown


FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)]\(([^)]+)\)")
INLINE_MARKUP = re.compile(r"(\*\*|__|==|`|(?<!\*)\*(?!\*)|(?<!_)_(?!_))")
DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
ACTION_OWNER = re.compile(r"\s+—\s+\*\*(.+?)\*\*")
ACTION_DUE = re.compile(r"\s+·\s+Due:\s+(.+?)\s*$")

INK = (24, 35, 58)
MUTED = (101, 113, 133)
INDIGO = (91, 92, 233)
INDIGO_DARK = (64, 65, 196)
INDIGO_PALE = (241, 241, 255)
BLUE_PALE = (238, 246, 255)
GREEN = (23, 137, 83)
GREEN_PALE = (235, 249, 242)
AMBER = (182, 112, 18)
AMBER_PALE = (255, 247, 229)
RED = (198, 57, 76)
RED_PALE = (255, 239, 242)
LINE = (220, 225, 234)
WHITE = (255, 255, 255)


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)


@dataclass
class MeetingDocument:
    title: str
    metadata: dict[str, str | list[str]]
    sections: list[Section]
    follow_up: str = ""
    warning: str = ""

    def section(self, title: str) -> Section | None:
        return next(
            (section for section in self.sections if section.title.casefold() == title.casefold()),
            None,
        )


def default_pdf_export_dir(home: Path | None = None) -> Path:
    """Return a visible, cross-platform folder suitable for file pickers."""
    home = Path(home or Path.home())
    return home / "Downloads" / "BeyondMeetings"


def _plain(text: str) -> str:
    text = WIKI_LINK.sub(lambda match: match.group(2) or match.group(1), text)
    text = MARKDOWN_LINK.sub(lambda match: f"{match.group(1)} ({match.group(2)})", text)
    return INLINE_MARKUP.sub("", text).strip()


def _parse_front_matter(raw: str) -> dict[str, str | list[str]]:
    metadata: dict[str, str | list[str]] = {}
    current_list = ""
    for line in raw.splitlines():
        item = re.match(r"^\s+-\s+(.+)$", line)
        if item and current_list:
            value = metadata.setdefault(current_list, [])
            if isinstance(value, list):
                value.append(_plain(item.group(1).strip('"\'')))
            continue
        key_value = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if not key_value:
            continue
        key, value = key_value.groups()
        if value:
            metadata[key] = _plain(value.strip().strip('"\''))
            current_list = ""
        else:
            metadata[key] = []
            current_list = key
    return metadata


def parse_meeting_markdown(markdown: str, fallback_title: str) -> MeetingDocument:
    """Extract the deterministic structure produced by the meeting-note AI."""
    front = FRONT_MATTER.match(markdown)
    metadata = _parse_front_matter(front.group(1)) if front else {}
    body = markdown[front.end():] if front else markdown
    title = fallback_title
    sections: list[Section] = []
    current: Section | None = None
    follow_parts: list[str] = []
    warning_parts: list[str] = []
    callout = ""

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            title = _plain(line[2:]) or fallback_title
            continue
        if line.startswith("## "):
            current = Section(_plain(line[3:]))
            sections.append(current)
            callout = ""
            continue
        if line.startswith(">"):
            quote = line.lstrip(">").strip()
            directive = re.match(r"\[!(\w+)\][+-]?\s*(.*)", quote)
            if directive:
                kind, label = directive.groups()
                callout = "warning" if kind.casefold() == "warning" else "follow"
                if label:
                    (warning_parts if callout == "warning" else follow_parts).append(label)
            elif callout:
                (warning_parts if callout == "warning" else follow_parts).append(quote)
            continue
        if not line or line == "---" or line.startswith("*Transcribed with"):
            continue
        if current is None:
            continue
        if re.match(r"^- (?:\[[ xX]\] )?", line):
            current.items.append(line[2:])
        else:
            current.paragraphs.append(line)

    follow_up = " ".join(_plain(part) for part in follow_parts).strip()
    warning = " ".join(_plain(part) for part in warning_parts).strip()
    return MeetingDocument(title, metadata, sections, follow_up, warning)


def _font_files() -> tuple[Path | None, Path | None]:
    """Find a Unicode-capable system font without bundling a large font file."""
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
         Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        (windows / "segoeui.ttf", windows / "segoeuib.ttf"),
        (windows / "arial.ttf", windows / "arialbd.ttf"),
    ]
    for regular, bold in candidates:
        if regular.is_file():
            return regular, bold if bold.is_file() else regular
    return None, None


def _pdf_text(text: str, unicode_font: bool) -> str:
    if unicode_font:
        return text
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _output_name(note: Path, suffix: str = "") -> str:
    stem = UNSAFE_FILENAME.sub("-", note.stem).strip(" .") or "Meeting"
    dated = f"{stem} - {note.parent.name}" if DATE_FOLDER.match(note.parent.name) else stem
    clean_suffix = UNSAFE_FILENAME.sub("-", suffix).strip(" .")
    return f"{dated}{f' - {clean_suffix}' if clean_suffix else ''}.pdf"


def _display_date(value: str) -> tuple[str, str]:
    if not value:
        return "Date unavailable", ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value, ""
    return parsed.strftime("%d %b %Y"), parsed.strftime("%I:%M %p").lstrip("0")


def _action_parts(raw: str) -> tuple[str, str, str]:
    text = re.sub(r"^\[[ xX]\]\s*", "", raw)
    owner_match = ACTION_OWNER.search(text)
    due_match = ACTION_DUE.search(text)
    owner = _plain(owner_match.group(1)) if owner_match else ""
    due = _plain(due_match.group(1)) if due_match else ""
    cut = min(
        [match.start() for match in (owner_match, due_match) if match] or [len(text)]
    )
    return _plain(text[:cut]), owner, due


def export_meeting_pdf(
    library: Path,
    requested: str,
    export_dir: Path | None = None,
    markdown_override: str | None = None,
    filename_suffix: str = "",
    brief_label: str = "AI MEETING BRIEF",
    show_metrics: bool = True,
) -> Path:
    """Render one safely-resolved Markdown meeting into a branded PDF brief."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as exc:  # pragma: no cover - packaging/install failure
        raise RuntimeError(
            "PDF support is not installed. Reinstall BeyondMeetings to add it."
        ) from exc

    note = resolve_markdown(Path(library), requested)
    if not note.is_file():
        raise FileNotFoundError(f"Note not found: {requested}")
    destination = Path(export_dir or default_pdf_export_dir())
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / _output_name(note, filename_suffix)

    document = parse_meeting_markdown(
        markdown_override
        if markdown_override is not None
        else note.read_text(encoding="utf-8", errors="replace"),
        note.stem,
    )
    regular, bold = _font_files()
    unicode_font = regular is not None
    family = "BeyondMeetings" if unicode_font else "Helvetica"

    class BriefPDF(FPDF):
        document_title = document.title

        def rounded_rect(self, x, y, width, height, radius, style="F"):
            """Compatibility wrapper for fpdf2's rounded rectangle API."""
            self.rect(
                x, y, width, height, style=style,
                round_corners=True, corner_radius=radius,
            )

        def header(self):
            if self.page_no() == 1:
                return
            self.set_y(9)
            self.set_font(family, "B", 7.5)
            self.set_text_color(*INDIGO)
            self.cell(
                46, 5, _pdf_text("bM  BEYONDMEETINGS", unicode_font),
                new_x=XPos.RIGHT, new_y=YPos.TOP,
            )
            self.set_font(family, "", 7.5)
            self.set_text_color(*MUTED)
            short = self.document_title[:70] + ("…" if len(self.document_title) > 70 else "")
            self.cell(
                0, 5, _pdf_text(short, unicode_font), align="R",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            self.set_draw_color(*LINE)
            self.line(self.l_margin, 16, self.w - self.r_margin, 16)
            self.set_y(22)

        def footer(self):
            self.set_y(-12)
            self.set_draw_color(*LINE)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(2)
            self.set_font(family, "", 7)
            self.set_text_color(*MUTED)
            self.cell(
                120, 4,
                _pdf_text("AI-structured meeting brief · Stored locally", unicode_font),
                new_x=XPos.RIGHT, new_y=YPos.TOP,
            )
            self.cell(
                0, 4, f"{self.page_no()}/{{nb}}", align="R",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )

    pdf = BriefPDF(format="A4")
    pdf.set_margins(16, 20, 16)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_title(document.title)
    pdf.set_author("BeyondMeetings")
    pdf.alias_nb_pages()
    if regular is not None:
        pdf.add_font(family, style="", fname=str(regular))
        pdf.add_font(family, style="B", fname=str(bold))

    def font(size: float, bold_text: bool = False, color=INK):
        pdf.set_font(family, "B" if bold_text else "", size)
        pdf.set_text_color(*color)

    def wrap(text: str, width: float) -> list[str]:
        words = _pdf_text(text, unicode_font).split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and pdf.get_string_width(candidate) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines or [""]

    def ensure(height: float):
        if pdf.get_y() + height > pdf.h - pdf.b_margin:
            pdf.add_page()

    def paragraph(text: str, size=10, color=INK, leading=5.6, indent=0):
        font(size, color=color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(
            pdf.epw - indent, leading, _pdf_text(_plain(text), unicode_font),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )

    def card(
        text: str,
        fill,
        accent=INDIGO,
        size=9.5,
        bold_text=False,
        prefix="",
        meta="",
    ):
        font(size, bold_text, INK)
        content_width = pdf.epw - 16
        lines = wrap(f"{prefix}{_plain(text)}", content_width)
        meta_lines: list[str] = []
        if meta:
            font(8, False, MUTED)
            meta_lines = wrap(meta, content_width)
        height = 8 + len(lines) * 5.2 + (len(meta_lines) * 4.5 + 2 if meta_lines else 0)
        ensure(height + 3)
        x, y = pdf.l_margin, pdf.get_y()
        pdf.set_fill_color(*fill)
        pdf.rounded_rect(x, y, pdf.epw, height, 2.5, style="F")
        pdf.set_fill_color(*accent)
        pdf.rounded_rect(x, y, 2.2, height, 1, style="F")
        pdf.set_xy(x + 7, y + 4)
        font(size, bold_text, INK)
        for line in lines:
            pdf.cell(
                content_width, 5.2, line,
                new_x=XPos.LEFT, new_y=YPos.NEXT,
            )
        if meta_lines:
            pdf.ln(1)
            pdf.set_x(x + 7)
            font(8, False, MUTED)
            for line in meta_lines:
                pdf.cell(
                    content_width, 4.5, line,
                    new_x=XPos.LEFT, new_y=YPos.NEXT,
                )
        pdf.set_y(y + height + 3)

    def section_heading(title: str, count: int | None = None):
        ensure(15)
        pdf.ln(4)
        x, y = pdf.l_margin, pdf.get_y()
        pdf.set_fill_color(*INDIGO)
        pdf.rounded_rect(x, y + 1, 3, 8, 1.2, style="F")
        pdf.set_xy(x + 7, y)
        font(15, True, INK)
        pdf.cell(
            pdf.epw - 30, 10, _pdf_text(title, unicode_font),
            new_x=XPos.RIGHT, new_y=YPos.TOP,
        )
        if count is not None:
            label = str(count)
            font(8, True, INDIGO)
            badge_width = max(9, pdf.get_string_width(label) + 6)
            bx = pdf.w - pdf.r_margin - badge_width
            pdf.set_fill_color(*INDIGO_PALE)
            pdf.rounded_rect(bx, y + 1.5, badge_width, 7, 3.5, style="F")
            pdf.set_xy(bx, y + 2)
            pdf.cell(
                badge_width, 6, label, align="C",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        else:
            pdf.set_y(y + 10)

    # Cover and identity
    pdf.add_page()
    pdf.set_y(14)
    x = pdf.l_margin
    pdf.set_fill_color(*INDIGO)
    pdf.rounded_rect(x, 14, 11, 11, 3, style="F")
    pdf.set_xy(x, 15.5)
    font(8.5, True, WHITE)
    pdf.cell(11, 7, "bM", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_xy(x + 15, 14.5)
    font(9, True, INK)
    pdf.cell(50, 5, "BEYONDMEETINGS", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_x(x + 15)
    font(6.8, True, INDIGO)
    pdf.cell(
        70, 4, _pdf_text(brief_label.upper(), unicode_font),
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )

    date_value = str(document.metadata.get("recorded_at") or document.metadata.get("date") or "")
    date_label, time_label = _display_date(date_value)
    pdf.set_xy(pdf.w - pdf.r_margin - 45, 15)
    font(8, True, INK)
    pdf.cell(45, 4.5, _pdf_text(date_label, unicode_font), align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_x(pdf.w - pdf.r_margin - 45)
    font(7, False, MUTED)
    pdf.cell(45, 4, _pdf_text(time_label or "Saved meeting", unicode_font), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(36)
    font(25, True, INK)
    title_lines = wrap(document.title, pdf.epw)
    for line in title_lines:
        pdf.cell(pdf.epw, 10.5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_fill_color(*INDIGO)
    pdf.rounded_rect(pdf.l_margin, pdf.get_y(), 34, 2, 1, style="F")
    pdf.set_fill_color(*LINE)
    pdf.rounded_rect(pdf.l_margin + 38, pdf.get_y(), pdf.epw - 38, 2, 1, style="F")
    pdf.ln(10)

    decisions = document.section("Decisions Made")
    actions = document.section("Action Items")
    questions = document.section("Open Questions")
    risks = document.section("Risks / Concerns")
    if show_metrics:
        metrics = [
            (str(len(decisions.items) if decisions else 0), "DECISIONS"),
            (str(len(actions.items) if actions else 0), "ACTIONS"),
            (str(len(questions.items) if questions else 0), "QUESTIONS"),
            (str(len(risks.items) if risks else 0), "RISKS"),
        ]
        gap = 3
        metric_width = (pdf.epw - gap * 3) / 4
        metric_y = pdf.get_y()
        for index, (value, label) in enumerate(metrics):
            mx = pdf.l_margin + index * (metric_width + gap)
            pdf.set_fill_color(*(INDIGO_PALE if index < 2 else BLUE_PALE))
            pdf.rounded_rect(mx, metric_y, metric_width, 19, 3, style="F")
            pdf.set_xy(mx, metric_y + 3)
            font(15, True, INDIGO_DARK)
            pdf.cell(
                metric_width, 7, value, align="C",
                new_x=XPos.LEFT, new_y=YPos.NEXT,
            )
            pdf.set_x(mx)
            font(6.5, True, MUTED)
            pdf.cell(
                metric_width, 5, label, align="C",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        pdf.set_y(metric_y + 25)

    summary = document.section("Executive Summary")
    if summary and summary.paragraphs:
        summary_text = " ".join(_plain(part) for part in summary.paragraphs)
        font(10, False, INK)
        summary_lines = wrap(summary_text, pdf.epw - 14)
        summary_height = 17 + len(summary_lines) * 5.6
        ensure(summary_height)
        sy = pdf.get_y()
        pdf.set_fill_color(*INDIGO_PALE)
        pdf.rounded_rect(pdf.l_margin, sy, pdf.epw, summary_height, 4, style="F")
        pdf.set_xy(pdf.l_margin + 7, sy + 5)
        font(8, True, INDIGO_DARK)
        pdf.cell(pdf.epw - 14, 5, "EXECUTIVE SUMMARY", new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.ln(1)
        font(10, False, INK)
        for line in summary_lines:
            pdf.cell(pdf.epw - 14, 5.6, line, new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_y(sy + summary_height + 5)

    attendees = document.metadata.get("attendees", [])
    topics = document.metadata.get("tags", [])
    if isinstance(attendees, list) and attendees:
        ensure(20)
        font(7, True, MUTED)
        pdf.cell(25, 5, "ATTENDEES", new_x=XPos.RIGHT, new_y=YPos.TOP)
        font(8.5, False, INK)
        pdf.multi_cell(
            pdf.epw - 25, 5,
            _pdf_text(" · ".join(attendees), unicode_font),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        pdf.ln(2)
    if isinstance(topics, list) and topics:
        font(7, True, MUTED)
        pdf.cell(25, 6, "TOPICS", new_x=XPos.RIGHT, new_y=YPos.TOP)
        cx, cy = pdf.get_x(), pdf.get_y()
        font(7.2, False, INDIGO_DARK)
        for topic in topics:
            label = _pdf_text(topic, unicode_font)
            width = pdf.get_string_width(label) + 7
            if cx + width > pdf.w - pdf.r_margin:
                cx = pdf.l_margin + 25
                cy += 7
            pdf.set_fill_color(*INDIGO_PALE)
            pdf.rounded_rect(cx, cy, width, 5.5, 2.5, style="F")
            pdf.set_xy(cx, cy + .3)
            pdf.cell(width, 5, label, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
            cx += width + 2
        pdf.set_y(cy + 9)

    if document.follow_up:
        card(document.follow_up, BLUE_PALE, INDIGO, size=8.5, prefix="Follow-up · ")
    if document.warning:
        warning = re.sub(r"^Transcription quality:\s*", "", document.warning, flags=re.I)
        card(warning, AMBER_PALE, AMBER, size=8.5, prefix="Transcription quality · ")

    # Structured sections generated by the configured AI provider.
    for section in document.sections:
        if section.title.casefold() == "executive summary":
            continue
        section_heading(section.title, len(section.items) if section.items else None)
        title_key = section.title.casefold()
        for paragraph_text in section.paragraphs:
            paragraph(paragraph_text)
            pdf.ln(2)
        if title_key == "action items":
            for raw in section.items:
                task, owner, due = _action_parts(raw)
                meta = "  ·  ".join(filter(None, (
                    f"Owner: {owner}" if owner else "",
                    f"Due: {due}" if due else "",
                )))
                card(task, INDIGO_PALE, INDIGO, size=9.2, bold_text=True,
                     prefix="[ ]  ", meta=meta)
        elif title_key == "decisions made":
            for index, item in enumerate(section.items, 1):
                card(item, BLUE_PALE, INDIGO, size=9.4, prefix=f"{index:02d}  ")
        elif title_key == "open questions":
            for item in section.items:
                card(item, BLUE_PALE, INDIGO, size=9.3, prefix="?  ")
        elif title_key == "risks / concerns":
            for item in section.items:
                card(item, RED_PALE, RED, size=9.3, prefix="!  ")
        elif title_key == "follow-ups":
            for item in section.items:
                card(item, GREEN_PALE, GREEN, size=9.3, prefix="→  ")
        else:
            for item in section.items:
                card(item, (247, 249, 252), INDIGO, size=9.3, prefix="•  ")

    pdf.output(str(target))
    return target


def reveal_pdf_for_sharing(
    pdf_path: Path,
    platform: str | None = None,
    spawn=None,
) -> None:
    """Reveal a PDF in the OS file manager when no native share API exists."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    platform = platform if platform is not None else sys.platform
    spawn = spawn or subprocess.Popen

    if platform == "darwin":
        command = ["open", "-R", str(pdf_path)]
    elif platform == "win32":
        command = ["explorer", f"/select,{pdf_path}"]
    elif shutil.which("nautilus"):
        command = ["nautilus", "--select", str(pdf_path)]
    elif shutil.which("dolphin"):
        command = ["dolphin", "--select", str(pdf_path)]
    else:
        command = ["xdg-open", str(pdf_path.parent)]

    spawn(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=platform != "win32",
    )
