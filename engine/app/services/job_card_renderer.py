"""Job Posting Renderer V5.3 — 2027 Dark Glass Aesthetic.

Premium YouTube visual design:
- Deep blue-black backgrounds with layered surfaces
- Cyan/red accent system with left-border indicators
- Progress bar ratings, pill-style benefits
- Clean typography hierarchy on DejaVuSans
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

# ── 2027 Color Palette ───────────────────────────────────
BG_COLOR = (8, 8, 12)              # Deep blue-black
CARD_BG = (18, 18, 28)             # Card background
CARD_SURFACE = (28, 28, 44)        # Elevated surface (sections, pills)
ACCENT_RED = (255, 45, 85)         # Roast accent
ACCENT_CYAN = (0, 210, 255)        # Section labels, cool accent
ACCENT_GREEN = (0, 220, 130)       # Salary/positive
ACCENT_YELLOW = (255, 200, 40)     # Warnings/quotes
TEXT_PRIMARY = (240, 240, 245)      # Off-white (less harsh)
TEXT_SECONDARY = (140, 140, 160)    # Mid-gray
TEXT_TERTIARY = (65, 65, 85)        # Dimmed/inactive
DIVIDER_COLOR = (38, 38, 55)       # Subtle dividers
GOLD = (255, 215, 0)
SILVER = (180, 180, 195)
BRONZE = (205, 140, 65)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


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


def _left_accent(draw: ImageDraw.Draw, x: int, y_start: int, y_end: int,
                 color: tuple, width: int = 4) -> None:
    """Draw a thin vertical accent line on the left side of a section."""
    draw.rectangle([(x, y_start), (x + width, y_end)], fill=(*color, 200))


# ═══════════════════════════════════════════════════════════
# FULLTEXT JOB POSTING
# ═══════════════════════════════════════════════════════════

async def render_job_posting(
    job: JobPosting,
    highlight_section: str = "",
) -> tuple[str, dict[str, tuple[int, int]]]:
    """Render a full job posting as a tall PNG — fullscreen 1920px wide."""
    width = 1920
    margin = 100
    inner_w = width - 2 * margin
    accent_x = margin - 14

    f_company = _font(FONT_BOLD, 36)
    f_location = _font(FONT_REGULAR, 26)
    f_title = _font(FONT_BOLD, 52)
    f_section = _font(FONT_BOLD, 26)
    f_salary_label = _font(FONT_BOLD, 26)
    f_salary = _font(FONT_BOLD, 46)
    f_body = _font(FONT_REGULAR, 28)
    f_pill = _font(FONT_REGULAR, 24)
    f_num = _font(FONT_BOLD, 28)
    f_watermark = _font(FONT_REGULAR, 18)

    # ── Pre-calculate heights ──
    sections: dict[str, tuple[int, int]] = {}
    y = 60

    # Header
    header_start = y
    y += 95
    sections["header"] = (header_start, y)

    # Title
    y += 20
    title_start = y
    title_lines = _wrap_text(job.title, f_title, inner_w)
    y += len(title_lines) * 64 + 25
    sections["title"] = (title_start, y)

    y += 25  # divider gap

    # Salary
    salary_start = y
    y += 110  # card-in-card
    sections["salary"] = (salary_start, y)

    y += 30

    # Description
    desc_start = y
    if job.description:
        y += 42  # label
        desc_lines = _wrap_text(job.description, f_body, inner_w - 20)
        y += len(desc_lines) * 32 + 15
    sections["description"] = (desc_start, y)

    y += 25

    # Benefits
    benefits_start = y
    if job.benefits:
        y += 42  # label
        # Pills layout: estimate rows
        pill_x = 0
        for b in job.benefits:
            pw = f_pill.getbbox(b)[2] + 32
            if pill_x + pw > inner_w:
                pill_x = 0
                y += 42
            pill_x += pw + 10
        y += 50  # last row + gap
    sections["benefits"] = (benefits_start, y)

    y += 25

    # Requirements
    req_start = y
    if job.requirements:
        y += 42  # label
        for req in job.requirements:
            lines = _wrap_text(req, f_body, inner_w - 50)
            y += len(lines) * 32 + 8
        y += 15
    sections["requirements"] = (req_start, y)

    y += 50  # watermark + bottom padding
    total_height = max(y + 40, 1200)

    # ── Render ──
    img = Image.new("RGBA", (width, total_height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Main card
    draw.rounded_rectangle(
        (35, 35, width - 35, total_height - 35),
        radius=16, fill=(*CARD_BG, 245),
    )

    y = 60

    # ── Company Header ──
    cc = _company_color(job.company)
    # Avatar circle (larger)
    draw.ellipse([margin, y, margin + 70, y + 70], fill=cc)
    init = job.company[0].upper() if job.company else "?"
    ibbox = _font(FONT_BOLD, 34).getbbox(init)
    draw.text((margin + 35 - ibbox[2] // 2, y + 17), init,
              font=_font(FONT_BOLD, 34), fill=TEXT_PRIMARY)

    is_active = highlight_section in ("", "header")
    draw.text((margin + 90, y + 8), job.company,
              font=f_company, fill=TEXT_PRIMARY if is_active else TEXT_TERTIARY)
    if job.location:
        draw.text((margin + 90, y + 46), job.location,
                  font=f_location, fill=TEXT_SECONDARY if is_active else TEXT_TERTIARY)
    y += 95 + 20

    # ── Title ──
    is_active = highlight_section in ("", "title")
    tc = TEXT_PRIMARY if is_active else TEXT_TERTIARY
    title_y_start = y
    for line in title_lines:
        draw.text((margin, y), line, font=f_title, fill=tc)
        y += 64
    # Underline accent
    if is_active:
        draw.rectangle([(margin, y + 2), (margin + 200, y + 5)], fill=(*ACCENT_CYAN, 150))
    y += 20

    if highlight_section == "title":
        _left_accent(draw, accent_x, title_y_start - 8, y, ACCENT_RED, 5)
        draw.rounded_rectangle(
            (margin - 15, title_y_start - 10, width - margin + 15, y + 5),
            radius=8, fill=(*CARD_SURFACE, 100),
        )
        # Re-draw title on top of highlight bg
        ry = title_y_start
        for line in title_lines:
            draw.text((margin, ry), line, font=f_title, fill=TEXT_PRIMARY)
            ry += 64

    # ── Divider ──
    draw.rectangle([(margin, y), (width - margin, y + 1)], fill=(*DIVIDER_COLOR, 180))
    y += 20

    # ── Salary (card-in-card) ──
    salary_y_start = y
    is_active = highlight_section in ("", "salary")
    # Elevated surface background
    sal_bg = CARD_SURFACE if is_active else CARD_BG
    draw.rounded_rectangle(
        (margin, y, width - margin, y + 90),
        radius=12, fill=(*sal_bg, 200),
    )
    draw.text((margin + 24, y + 14), "GEHALT",
              font=f_salary_label, fill=ACCENT_CYAN if is_active else TEXT_TERTIARY)
    if job.salary:
        sal_color = ACCENT_GREEN if is_active else TEXT_TERTIARY
        draw.text((margin + 24, y + 42), job.salary, font=f_salary, fill=sal_color)
    else:
        sal_color = ACCENT_RED if is_active else TEXT_TERTIARY
        draw.text((margin + 24, y + 42), "Nicht angegeben", font=f_salary, fill=sal_color)
    y += 90

    if highlight_section == "salary":
        _left_accent(draw, accent_x, salary_y_start, y, ACCENT_RED, 5)

    y += 25

    # ── Description ──
    if job.description:
        desc_y_start = y
        is_active = highlight_section in ("", "description")
        lc = ACCENT_CYAN if is_active else TEXT_TERTIARY
        _left_accent(draw, accent_x, y, y + 28, lc, 3)
        draw.text((margin, y), "\u00dcBER DAS UNTERNEHMEN", font=f_section, fill=lc)
        y += 35
        dc = TEXT_PRIMARY if is_active else TEXT_TERTIARY
        for line in _wrap_text(job.description, f_body, inner_w - 20):
            draw.text((margin + 10, y), line, font=f_body, fill=dc)
            y += 32
        y += 15

    y += 25

    # ── Benefits (pills) ──
    if job.benefits:
        benefits_y_start = y
        is_active = highlight_section in ("", "benefits")
        lc = ACCENT_GREEN if is_active else TEXT_TERTIARY
        _left_accent(draw, accent_x, y, y + 28, lc, 3)
        draw.text((margin, y), "BENEFITS", font=f_section, fill=lc)
        y += 35
        pill_x = margin
        for benefit in job.benefits:
            pw = f_pill.getbbox(benefit)[2] + 32
            ph = 34
            if pill_x + pw > width - margin:
                pill_x = margin
                y += 42
            pill_bg = CARD_SURFACE if is_active else (30, 30, 40)
            pill_tc = ACCENT_GREEN if is_active else TEXT_TERTIARY
            draw.rounded_rectangle(
                (pill_x, y, pill_x + pw, y + ph),
                radius=17, fill=(*pill_bg, 220),
            )
            draw.text((pill_x + 16, y + 6), benefit, font=f_pill, fill=pill_tc)
            pill_x += pw + 10
        y += 50

        if highlight_section == "benefits":
            _left_accent(draw, accent_x, benefits_y_start, y, ACCENT_RED, 5)

    y += 25

    # ── Requirements (numbered) ──
    if job.requirements:
        req_y_start = y
        is_active = highlight_section in ("", "requirements")
        lc = ACCENT_RED if is_active else TEXT_TERTIARY
        _left_accent(draw, accent_x, y, y + 28, lc, 3)
        draw.text((margin, y), "ANFORDERUNGEN", font=f_section, fill=lc)
        y += 35
        for i, req in enumerate(job.requirements, 1):
            num_color = ACCENT_CYAN if is_active else TEXT_TERTIARY
            draw.text((margin + 10, y), f"{i}.", font=f_num, fill=num_color)
            rc = TEXT_PRIMARY if is_active else TEXT_TERTIARY
            for line in _wrap_text(req, f_body, inner_w - 50):
                draw.text((margin + 42, y), line, font=f_body, fill=rc)
                y += 32
            y += 8
        y += 15

        if highlight_section == "requirements":
            _left_accent(draw, accent_x, req_y_start, y, ACCENT_RED, 5)

    # ── Watermark ──
    y += 20
    draw.text((margin, y), "Quelle: Stellenanzeige 2026",
              font=f_watermark, fill=(*TEXT_TERTIARY, 120))

    out = os.path.join(settings.output_dir, f"posting_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered posting: %s (%dx%d, hl=%s)", out, width, total_height, highlight_section or "none")
    return out, sections


# ═══════════════════════════════════════════════════════════
# RATING CARD — progress bar + squares
# ═══════════════════════════════════════════════════════════

async def render_rating_card(job: JobPosting, rating: int) -> str:
    """Render X/10 rating with progress bar and square indicators."""
    width, height = 1920, 1080
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Company + title
    tf = _font(FONT_REGULAR, 30)
    text = f"{job.company} \u2014 {job.title}"
    lines = _wrap_text(text, tf, width - 200)
    for i, line in enumerate(lines[:2]):
        bbox = tf.getbbox(line)
        draw.text(((width - bbox[2]) // 2, 100 + i * 38), line, font=tf, fill=TEXT_SECONDARY)

    # Shadow layer for big number
    big_font = _font(FONT_BOLD, 220)
    rating_text = f"{rating}/10"
    bbox = big_font.getbbox(rating_text)
    cx = (width - bbox[2]) // 2
    draw.text((cx + 4, 224), rating_text, font=big_font, fill=(20, 20, 30))

    # Big rating number
    r_color = ACCENT_GREEN if rating >= 7 else ACCENT_YELLOW if rating >= 4 else ACCENT_RED
    draw.text((cx, 220), rating_text, font=big_font, fill=r_color)

    # Progress bar
    bar_w, bar_h = 900, 30
    bar_x = (width - bar_w) // 2
    bar_y = 500
    # Background
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=15, fill=(*CARD_SURFACE, 200),
    )
    # Fill
    fill_w = int(bar_w * rating / 10)
    if fill_w > 0:
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
            radius=15, fill=(*r_color, 230),
        )

    # 10 square indicators
    sq_size = 36
    sq_gap = 16
    total_sq = 10 * sq_size + 9 * sq_gap
    sq_x = (width - total_sq) // 2
    sq_y = bar_y + bar_h + 30
    for i in range(10):
        x = sq_x + i * (sq_size + sq_gap)
        if i < rating:
            draw.rounded_rectangle(
                (x, sq_y, x + sq_size, sq_y + sq_size),
                radius=6, fill=r_color,
            )
        else:
            draw.rounded_rectangle(
                (x, sq_y, x + sq_size, sq_y + sq_size),
                radius=6, fill=(*CARD_SURFACE, 180),
                outline=(*DIVIDER_COLOR, 150),
            )

    # Verdict
    if rating <= 3:
        verdict = "Wallah traurig. Finger weg Bruder."
    elif rating <= 5:
        verdict = "Mittelmäßig. Kannste machen, musste aber nicht."
    elif rating <= 7:
        verdict = "Geht klar. Nicht schlecht, nicht geil."
    else:
        verdict = "Mashallah! Solider Job Bruder."
    vf = _font(FONT_REGULAR, 34)
    bbox = vf.getbbox(verdict)
    draw.text(((width - bbox[2]) // 2, 650), verdict, font=vf, fill=TEXT_PRIMARY)

    # Bottom label
    lf = _font(FONT_BOLD, 22)
    label = f"{rating} von 10 D\u00f6nern"
    bbox = lf.getbbox(label)
    draw.text(((width - bbox[2]) // 2, height - 100), label, font=lf, fill=r_color)

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
    """Render final ranking (1920x1080) with 2027 glass aesthetic."""
    width, height = 1920, 1080
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Header
    hf = _font(FONT_BOLD, 68)
    header = "FINAL RANKING"
    bbox = hf.getbbox(header)
    draw.text(((width - bbox[2]) // 2, 55), header, font=hf, fill=ACCENT_RED)

    # Thin accent line under header
    line_w = 300
    draw.rectangle(
        ((width - line_w) // 2, 138, (width + line_w) // 2, 140),
        fill=(*ACCENT_RED, 120),
    )

    sf = _font(FONT_REGULAR, 24)
    sub = "Vom Besten zum Schlechtesten"
    bbox = sf.getbbox(sub)
    draw.text(((width - bbox[2]) // 2, 155), sub, font=sf, fill=TEXT_SECONDARY)

    rank_colors = [ACCENT_GREEN, ACCENT_YELLOW, ACCENT_RED]
    medal_colors = [GOLD, SILVER, BRONZE]
    row_h = 200
    start_y = 220

    for pos, job_idx in enumerate(ranking_order[:3]):
        if job_idx >= len(jobs):
            continue
        job = jobs[job_idx]
        rating = ratings[job_idx] if job_idx < len(ratings) else 5
        y = start_y + pos * row_h

        # Row card
        draw.rounded_rectangle(
            (120, y, width - 120, y + row_h - 16),
            radius=14, fill=(*CARD_BG, 220),
        )
        # Left accent border
        _left_accent(draw, 120, y, y + row_h - 16, rank_colors[pos], 5)

        # Rank medal (circle bg)
        medal_cx, medal_cy = 185, y + (row_h - 16) // 2
        draw.ellipse(
            [medal_cx - 32, medal_cy - 32, medal_cx + 32, medal_cy + 32],
            fill=(*medal_colors[pos], 40), outline=(*medal_colors[pos], 180),
        )
        rf = _font(FONT_BOLD, 36)
        rt = f"#{pos + 1}"
        rbbox = rf.getbbox(rt)
        draw.text((medal_cx - rbbox[2] // 2, medal_cy - rbbox[3] // 2 - 2),
                  rt, font=rf, fill=medal_colors[pos])

        # Company circle
        cc = _company_color(job.company)
        ccx = 280
        draw.ellipse([ccx - 28, medal_cy - 28, ccx + 28, medal_cy + 28], fill=cc)

        # Job info
        cf = _font(FONT_BOLD, 30)
        tf = _font(FONT_REGULAR, 24)
        draw.text((330, y + 35), job.company, font=cf, fill=TEXT_PRIMARY)
        title_lines = _wrap_text(job.title, tf, 700)
        draw.text((330, y + 72), title_lines[0], font=tf, fill=TEXT_SECONDARY)

        # Mini rating bar (right side)
        bar_w, bar_h = 180, 16
        bar_x = width - 300
        bar_y_pos = y + 45
        draw.rounded_rectangle(
            (bar_x, bar_y_pos, bar_x + bar_w, bar_y_pos + bar_h),
            radius=8, fill=(*CARD_SURFACE, 200),
        )
        fill_w = int(bar_w * rating / 10)
        if fill_w > 0:
            r_c = ACCENT_GREEN if rating >= 7 else ACCENT_YELLOW if rating >= 4 else ACCENT_RED
            draw.rounded_rectangle(
                (bar_x, bar_y_pos, bar_x + fill_w, bar_y_pos + bar_h),
                radius=8, fill=r_c,
            )

        # Rating number
        rrf = _font(FONT_BOLD, 48)
        r_text = f"{rating}/10"
        r_color = ACCENT_GREEN if rating >= 7 else ACCENT_YELLOW if rating >= 4 else ACCENT_RED
        rrbbox = rrf.getbbox(r_text)
        draw.text((bar_x + (bar_w - rrbbox[2]) // 2, bar_y_pos + bar_h + 10),
                  r_text, font=rrf, fill=r_color)

    out = os.path.join(settings.output_dir, f"ranking_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered ranking: %s", out)
    return out
