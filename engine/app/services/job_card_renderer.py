"""Job Posting Renderer V5 — Fulltext job posting, scroll-ready, section highlights.

Renders job postings as tall PNG documents (1920x2400+) that simulate a real
job listing. FFmpeg scrolls through these during the video.

Also renders:
- Rating card (X/10 Döner, simplified)
- Ranking leaderboard (final ranking screen)
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.models import JobPosting

logger = logging.getLogger(__name__)

# ── Color Palette ────────────────────────────────────────
BG_COLOR = (13, 13, 13)
CARD_BG = (22, 22, 32)
SECTION_BG = (28, 28, 42)
NEON_RED = (255, 23, 68)
NEON_GREEN = (0, 230, 118)
NEON_YELLOW = (255, 221, 0)
TEXT_WHITE = (255, 255, 255)
TEXT_DIM = (160, 160, 175)
TEXT_MUTED = (90, 90, 110)
GOLD = (255, 215, 0)
SILVER = (192, 192, 192)
BRONZE = (205, 127, 50)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Section Y-positions are tracked dynamically during rendering
# and returned so FFmpeg knows where to scroll to per scene type.
SECTION_KEYS = ["header", "title", "salary", "description", "benefits", "requirements"]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if font.getbbox(test)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _company_color(company: str) -> tuple:
    colors = [
        (66, 133, 244), (234, 67, 53), (251, 188, 4), (52, 168, 83),
        (171, 71, 188), (255, 112, 67), (0, 172, 193), (124, 179, 66),
    ]
    h = int(hashlib.md5(company.encode()).hexdigest()[:8], 16)
    return colors[h % len(colors)]


# ═══════════════════════════════════════════════════════════
# FULLTEXT JOB POSTING — tall scrollable document
# ═══════════════════════════════════════════════════════════

async def render_job_posting(
    job: JobPosting,
    highlight_section: str = "",
) -> tuple[str, dict[str, tuple[int, int]]]:
    """Render a full job posting as a tall PNG document.

    Returns: (png_path, section_bounds) where section_bounds maps
    section names to (y_start, y_end) pixel positions for scroll targeting.
    """
    width = 1400
    margin = 60
    inner_w = width - 2 * margin

    # Fonts
    f_company = _font(FONT_BOLD, 28)
    f_location = _font(FONT_REGULAR, 22)
    f_title = _font(FONT_BOLD, 40)
    f_section_label = _font(FONT_BOLD, 24)
    f_salary = _font(FONT_BOLD, 36)
    f_body = _font(FONT_REGULAR, 24)
    f_bullet = _font(FONT_REGULAR, 24)

    # ── Pre-calculate total height ──
    y = 0
    sections: dict[str, tuple[int, int]] = {}

    # Header
    y += 50  # top padding
    header_start = y
    y += 70  # company + location
    y += 20  # gap
    sections["header"] = (header_start, y)

    # Title
    title_start = y
    title_lines = _wrap_text(job.title, f_title, inner_w)
    y += len(title_lines) * 50 + 30
    sections["title"] = (title_start, y)

    # Divider
    y += 30

    # Salary
    salary_start = y
    y += 60
    sections["salary"] = (salary_start, y)

    # Divider
    y += 30

    # Description
    desc_start = y
    if job.description:
        y += 40  # label
        desc_lines = _wrap_text(job.description, f_body, inner_w)
        y += len(desc_lines) * 32 + 20
    sections["description"] = (desc_start, y)

    y += 30

    # Benefits
    benefits_start = y
    if job.benefits:
        y += 40  # label
        for benefit in job.benefits:
            lines = _wrap_text(f"\u2022 {benefit}", f_bullet, inner_w - 20)
            y += len(lines) * 32
        y += 20
    sections["benefits"] = (benefits_start, y)

    y += 30

    # Requirements
    req_start = y
    if job.requirements:
        y += 40  # label
        for req in job.requirements:
            lines = _wrap_text(f"\u2022 {req}", f_bullet, inner_w - 20)
            y += len(lines) * 32
        y += 20
    sections["requirements"] = (req_start, y)

    y += 80  # bottom padding
    total_height = max(y, 1200)  # minimum height

    # ── Render ──
    img = Image.new("RGBA", (width, total_height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Card background
    draw.rounded_rectangle(
        (30, 30, width - 30, total_height - 30),
        radius=20, fill=(*CARD_BG, 240),
    )

    y = 50  # reset cursor

    # ── Company Header ──
    cc = _company_color(job.company)
    draw.ellipse([margin, y, margin + 50, y + 50], fill=cc)
    init = job.company[0].upper() if job.company else "?"
    ibbox = _font(FONT_BOLD, 26).getbbox(init)
    draw.text((margin + 25 - ibbox[2] // 2, y + 12), init,
              font=_font(FONT_BOLD, 26), fill=TEXT_WHITE)

    is_active = highlight_section in ("", "header")
    draw.text((margin + 65, y + 2), job.company,
              font=f_company, fill=TEXT_WHITE if is_active else TEXT_MUTED)
    if job.location:
        draw.text((margin + 65, y + 34), job.location,
                  font=f_location, fill=TEXT_DIM if is_active else TEXT_MUTED)
    y += 70 + 20

    # ── Title ──
    is_active = highlight_section in ("", "title")
    tc = TEXT_WHITE if is_active else TEXT_MUTED
    for line in title_lines:
        draw.text((margin, y), line, font=f_title, fill=tc)
        y += 50
    y += 30
    if highlight_section == "title":
        _draw_section_highlight(draw, margin - 15, sections["title"][0] - 10,
                                width - margin + 15, sections["title"][1] + 10)

    # ── Divider ──
    draw.line([(margin, y), (width - margin, y)], fill=(50, 50, 65), width=2)
    y += 30

    # ── Salary ──
    is_active = highlight_section in ("", "salary")
    draw.text((margin, y), "GEHALT", font=f_section_label,
              fill=NEON_GREEN if is_active else TEXT_MUTED)
    if job.salary:
        sal_color = NEON_GREEN if is_active else TEXT_MUTED
        draw.text((margin + 120, y - 4), job.salary, font=f_salary, fill=sal_color)
    else:
        sal_color = NEON_RED if is_active else TEXT_MUTED
        draw.text((margin + 120, y - 4), "Nicht angegeben", font=f_salary, fill=sal_color)
    y += 60
    if highlight_section == "salary":
        _draw_section_highlight(draw, margin - 15, sections["salary"][0] - 10,
                                width - margin + 15, sections["salary"][1] + 10)

    # ── Divider ──
    draw.line([(margin, y), (width - margin, y)], fill=(50, 50, 65), width=2)
    y += 30

    # ── Description ──
    if job.description:
        is_active = highlight_section in ("", "description")
        draw.text((margin, y), "\u00dcBER UNS", font=f_section_label,
                  fill=NEON_YELLOW if is_active else TEXT_MUTED)
        y += 40
        desc_color = TEXT_WHITE if is_active else TEXT_MUTED
        for line in _wrap_text(job.description, f_body, inner_w):
            draw.text((margin, y), line, font=f_body, fill=desc_color)
            y += 32
        y += 20
    y += 30

    # ── Benefits ──
    if job.benefits:
        is_active = highlight_section in ("", "benefits")
        label_color = NEON_GREEN if is_active else TEXT_MUTED
        draw.text((margin, y), "BENEFITS", font=f_section_label, fill=label_color)
        y += 40
        bullet_color = TEXT_WHITE if is_active else TEXT_MUTED
        for benefit in job.benefits:
            for line in _wrap_text(f"\u2022 {benefit}", f_bullet, inner_w - 20):
                draw.text((margin + 10, y), line, font=f_bullet, fill=bullet_color)
                y += 32
        y += 20
        if highlight_section == "benefits":
            _draw_section_highlight(draw, margin - 15, sections["benefits"][0] - 10,
                                    width - margin + 15, y + 10)
    y += 30

    # ── Requirements ──
    if job.requirements:
        is_active = highlight_section in ("", "requirements")
        label_color = NEON_RED if is_active else TEXT_MUTED
        draw.text((margin, y), "ANFORDERUNGEN", font=f_section_label, fill=label_color)
        y += 40
        bullet_color = TEXT_WHITE if is_active else TEXT_MUTED
        for req in job.requirements:
            for line in _wrap_text(f"\u2022 {req}", f_bullet, inner_w - 20):
                draw.text((margin + 10, y), line, font=f_bullet, fill=bullet_color)
                y += 32
        y += 20
        if highlight_section == "requirements":
            _draw_section_highlight(draw, margin - 15, sections["requirements"][0] - 10,
                                    width - margin + 15, y + 10)

    out = os.path.join(settings.output_dir, f"posting_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered posting: %s (%dx%d, highlight=%s)",
                out, width, total_height, highlight_section or "none")
    return out, sections


def _draw_section_highlight(draw: ImageDraw.Draw, x0: int, y0: int,
                            x1: int, y1: int) -> None:
    """Red glow highlight around a section."""
    for i, alpha in enumerate([30, 60, 100]):
        offset = (3 - i) * 4
        draw.rounded_rectangle(
            (x0 - offset, y0 - offset, x1 + offset, y1 + offset),
            radius=12, outline=(*NEON_RED, alpha), width=2,
        )
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=8,
        outline=(*NEON_RED, 180), width=3,
    )


# ═══════════════════════════════════════════════════════════
# RATING CARD — simplified, big number only
# ═══════════════════════════════════════════════════════════

async def render_rating_card(job: JobPosting, rating: int) -> str:
    """Render X/10 Döner rating — big number + verdict, no dots."""
    width, height = 1920, 1080
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Company + title (top)
    title_font = _font(FONT_REGULAR, 32)
    text = f"{job.company} \u2014 {job.title}"
    lines = _wrap_text(text, title_font, width - 200)
    for i, line in enumerate(lines[:2]):
        bbox = title_font.getbbox(line)
        draw.text(((width - bbox[2]) // 2, 120 + i * 42), line,
                  font=title_font, fill=TEXT_DIM)

    # Big rating
    rating_color = NEON_GREEN if rating >= 7 else NEON_YELLOW if rating >= 4 else NEON_RED
    big_font = _font(FONT_BOLD, 240)
    rating_text = f"{rating}/10"
    bbox = big_font.getbbox(rating_text)
    draw.text(((width - bbox[2]) // 2, 280), rating_text,
              font=big_font, fill=rating_color)

    # "DÖNER" label
    label_font = _font(FONT_BOLD, 48)
    bbox = label_font.getbbox("D\u00d6NER")
    draw.text(((width - bbox[2]) // 2, 560), "D\u00d6NER",
              font=label_font, fill=TEXT_DIM)

    # Verdict
    if rating <= 3:
        verdict = "Wallah traurig. Finger weg Bruder."
    elif rating <= 5:
        verdict = "Mittelmäßig. Kannste machen, musste aber nicht."
    elif rating <= 7:
        verdict = "Geht klar. Nicht schlecht, nicht geil."
    else:
        verdict = "Mashallah! Solider Job Bruder."
    verdict_font = _font(FONT_REGULAR, 36)
    bbox = verdict_font.getbbox(verdict)
    draw.text(((width - bbox[2]) // 2, 680), verdict,
              font=verdict_font, fill=TEXT_WHITE)

    out = os.path.join(settings.output_dir, f"rating_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered rating: %s (%d/10)", out, rating)
    return out


# ═══════════════════════════════════════════════════════════
# RANKING LEADERBOARD
# ═══════════════════════════════════════════════════════════

async def render_ranking_leaderboard(
    jobs: list[JobPosting],
    ratings: list[int],
    ranking_order: list[int],
) -> str:
    """Render final ranking (1920x1080)."""
    width, height = 1920, 1080
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    header_font = _font(FONT_BOLD, 72)
    header = "FINAL RANKING"
    bbox = header_font.getbbox(header)
    draw.text(((width - bbox[2]) // 2, 60), header, font=header_font, fill=NEON_RED)

    sub_font = _font(FONT_REGULAR, 28)
    sub = "Vom Besten zum Schlechtesten"
    bbox = sub_font.getbbox(sub)
    draw.text(((width - bbox[2]) // 2, 150), sub, font=sub_font, fill=TEXT_DIM)

    rank_colors = [NEON_GREEN, NEON_YELLOW, NEON_RED]
    medal_colors = [GOLD, SILVER, BRONZE]
    row_h = 220
    start_y = 240

    for pos, job_idx in enumerate(ranking_order[:3]):
        if job_idx >= len(jobs):
            continue
        job = jobs[job_idx]
        rating = ratings[job_idx] if job_idx < len(ratings) else 5
        y = start_y + pos * row_h

        draw.rounded_rectangle(
            (100, y, width - 100, y + row_h - 20),
            radius=16, fill=(*CARD_BG, 200),
            outline=(*rank_colors[pos], 100),
        )

        rank_font = _font(FONT_BOLD, 80)
        draw.text((140, y + 50), f"#{pos + 1}",
                  font=rank_font, fill=medal_colors[pos])

        cc = _company_color(job.company)
        cx, cy = 360, y + row_h // 2 - 10
        draw.ellipse([cx - 35, cy - 35, cx + 35, cy + 35], fill=cc)

        company_font = _font(FONT_BOLD, 32)
        title_font = _font(FONT_REGULAR, 26)
        draw.text((420, y + 40), job.company, font=company_font, fill=TEXT_WHITE)
        title_lines = _wrap_text(job.title, title_font, 800)
        draw.text((420, y + 82), title_lines[0], font=title_font, fill=TEXT_DIM)

        r_font = _font(FONT_BOLD, 64)
        r_color = NEON_GREEN if rating >= 7 else NEON_YELLOW if rating >= 4 else NEON_RED
        rbbox = r_font.getbbox(f"{rating}/10")
        draw.text((width - 250 - rbbox[2] // 2, y + 55),
                  f"{rating}/10", font=r_font, fill=r_color)

    out = os.path.join(settings.output_dir, f"ranking_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered ranking: %s", out)
    return out
