"""Job Card Renderer V4 — Neon dark theme, section highlights, ratings, leaderboard.

Renders multiple card variants per job as PNGs using Pillow:
- Full card (for JOB_REVEAL scenes)
- Section-highlighted cards (for TITEL/BENEFITS/ANFORDERUNGEN/GEHALT roasts)
- Rating card (X/10 Doener graphic)
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

# ── Color Palette (Neon Dark) ────────────────────────────
BG_COLOR = (13, 13, 13)          # #0D0D0D
CARD_BG = (26, 26, 46)           # #1A1A2E
CARD_BORDER = (44, 44, 70)       # #2C2C46
NEON_RED = (255, 23, 68)         # #FF1744
NEON_GREEN = (0, 230, 118)       # #00E676
NEON_YELLOW = (255, 221, 0)      # #FFDD00
TEXT_WHITE = (255, 255, 255)
TEXT_DIM = (120, 120, 140)       # #78788C
TEXT_MUTED = (80, 80, 100)       # #505064
GOLD = (255, 215, 0)
SILVER = (192, 192, 192)
BRONZE = (205, 127, 50)

# ── Font Loading ─────────────────────────────────────────
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ── Shared Helpers ───────────────────────────────────────

def _draw_rounded_rect(draw: ImageDraw.Draw, rect: tuple, fill: tuple,
                        radius: int = 20, outline: tuple | None = None) -> None:
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] <= max_width:
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


# ── Full Job Card ────────────────────────────────────────

async def render_job_card(job: JobPosting) -> str:
    """Render the full job card (no highlights). Used for JOB_REVEAL."""
    return _render_card(job, highlight_section="")


async def render_job_card_highlighted(job: JobPosting, section: str) -> str:
    """Render card with one section highlighted red, others dimmed."""
    return _render_card(job, highlight_section=section)


def _render_card(job: JobPosting, highlight_section: str = "",
                 width: int = 1600, height: int = 1000) -> str:
    """Core card renderer with optional section highlighting."""
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)
    margin = 50
    card_x0, card_y0 = margin, margin
    card_x1, card_y1 = width - margin, height - margin

    # Card background
    _draw_rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1),
                        fill=(*CARD_BG, 230), radius=24, outline=(*CARD_BORDER, 255))

    inner_left = card_x0 + 40
    inner_right = card_x1 - 40

    # ── Company header ──
    color = _company_color(job.company)
    cx, cy = inner_left + 30, card_y0 + 60
    draw.ellipse([cx - 25, cy - 25, cx + 25, cy + 25], fill=color)
    initial_font = _font(FONT_BOLD, 28)
    initial = job.company[0].upper() if job.company else "?"
    bbox = initial_font.getbbox(initial)
    draw.text((cx - bbox[2] // 2, cy - bbox[3] // 2 - 2), initial,
              font=initial_font, fill=TEXT_WHITE)

    company_font = _font(FONT_REGULAR, 24)
    draw.text((inner_left + 70, card_y0 + 38), job.company,
              font=company_font, fill=TEXT_WHITE if highlight_section == "" else TEXT_DIM)
    if job.location:
        loc_font = _font(FONT_REGULAR, 20)
        draw.text((inner_left + 70, card_y0 + 68), job.location,
                  font=loc_font, fill=TEXT_DIM)

    # Section Y positions (relative to card_y0)
    title_y = card_y0 + 140
    salary_y = card_y0 + 280
    benefits_y = card_y0 + 370
    req_y = card_y0 + 600

    # ── Title Section ──
    title_active = highlight_section in ("", "title")
    title_color = TEXT_WHITE if title_active else TEXT_MUTED
    title_font = _font(FONT_BOLD, 42)
    lines = _wrap_text(job.title, title_font, inner_right - inner_left)
    for i, line in enumerate(lines[:2]):
        draw.text((inner_left, title_y + i * 52), line,
                  font=title_font, fill=title_color)
    title_end = title_y + len(lines[:2]) * 52 + 10

    if highlight_section == "title":
        _draw_highlight_border(draw, inner_left - 10, title_y - 10,
                               inner_right + 10, title_end)

    # ── Salary Section ──
    salary_active = highlight_section in ("", "salary")
    salary_font = _font(FONT_BOLD, 34)
    if job.salary:
        salary_color = NEON_GREEN if salary_active else TEXT_MUTED
        draw.text((inner_left, salary_y), f"Gehalt: {job.salary}",
                  font=salary_font, fill=salary_color)
    else:
        salary_color = NEON_RED if salary_active else TEXT_MUTED
        draw.text((inner_left, salary_y), "Gehalt: Nicht angegeben",
                  font=salary_font, fill=salary_color)

    if highlight_section == "salary":
        _draw_highlight_border(draw, inner_left - 10, salary_y - 10,
                               inner_right + 10, salary_y + 44)

    # ── Benefits Section ──
    benefits_active = highlight_section in ("", "benefits")
    section_font = _font(FONT_BOLD, 22)
    label_color = NEON_GREEN if benefits_active else TEXT_MUTED
    draw.text((inner_left, benefits_y), "BENEFITS", font=section_font, fill=label_color)

    tag_font = _font(FONT_REGULAR, 22)
    tag_x, tag_y = inner_left, benefits_y + 35
    for benefit in job.benefits[:8]:
        text_w = tag_font.getbbox(benefit)[2] + 24
        if tag_x + text_w > inner_right:
            tag_x = inner_left
            tag_y += 40
        pill_color = (30, 80, 50) if benefits_active else (40, 40, 50)
        text_color = NEON_GREEN if benefits_active else TEXT_MUTED
        _draw_rounded_rect(draw, (tag_x, tag_y, tag_x + text_w, tag_y + 32),
                            fill=pill_color, radius=16)
        draw.text((tag_x + 12, tag_y + 4), benefit, font=tag_font, fill=text_color)
        tag_x += text_w + 10
    benefits_end = tag_y + 50

    if highlight_section == "benefits":
        _draw_highlight_border(draw, inner_left - 10, benefits_y - 10,
                               inner_right + 10, benefits_end)

    # ── Requirements Section ──
    req_active = highlight_section in ("", "requirements")
    label_color = NEON_RED if req_active else TEXT_MUTED
    draw.text((inner_left, req_y), "ANFORDERUNGEN", font=section_font, fill=label_color)

    req_font = _font(FONT_REGULAR, 22)
    ry = req_y + 35
    for req in job.requirements[:5]:
        bullet_color = TEXT_WHITE if req_active else TEXT_MUTED
        wrapped = _wrap_text(req, req_font, inner_right - inner_left - 30)
        for line in wrapped[:2]:
            draw.text((inner_left + 20, ry), f"\u2022 {line}",
                      font=req_font, fill=bullet_color)
            ry += 30
    req_end = ry + 10

    if highlight_section == "requirements":
        _draw_highlight_border(draw, inner_left - 10, req_y - 10,
                               inner_right + 10, req_end)

    out = os.path.join(settings.output_dir, f"card_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered job card: %s (highlight=%s)", out, highlight_section or "none")
    return out


def _draw_highlight_border(draw: ImageDraw.Draw, x0: int, y0: int,
                           x1: int, y1: int) -> None:
    """Draw neon red glow border around a section."""
    for i, alpha in enumerate([40, 70, 120]):
        offset = (3 - i) * 3
        draw.rounded_rectangle(
            (x0 - offset, y0 - offset, x1 + offset, y1 + offset),
            radius=12, outline=(*NEON_RED, alpha), width=2,
        )
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=8,
        outline=(*NEON_RED, 200), width=3,
    )


# ── Rating Card ──────────────────────────────────────────

async def render_rating_card(job: JobPosting, rating: int) -> str:
    """Render X/10 Doener rating graphic."""
    width, height = 1400, 900
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    _draw_rounded_rect(draw, (40, 40, width - 40, height - 40),
                        fill=(*CARD_BG, 230), radius=24)

    # Job title (smaller, top)
    title_font = _font(FONT_REGULAR, 28)
    lines = _wrap_text(f"{job.company} \u2014 {job.title}", title_font, width - 160)
    for i, line in enumerate(lines[:2]):
        bbox = title_font.getbbox(line)
        x = (width - bbox[2]) // 2
        draw.text((x, 80 + i * 36), line, font=title_font, fill=TEXT_DIM)

    # Big rating number
    rating_color = NEON_GREEN if rating >= 7 else NEON_YELLOW if rating >= 4 else NEON_RED
    big_font = _font(FONT_BOLD, 180)
    rating_text = f"{rating}/10"
    bbox = big_font.getbbox(rating_text)
    rx = (width - bbox[2]) // 2
    draw.text((rx, 200), rating_text, font=big_font, fill=rating_color)

    # Doener dots
    dot_size = 40
    dot_gap = 16
    total_w = 10 * dot_size + 9 * dot_gap
    start_x = (width - total_w) // 2
    dot_y = 460

    for i in range(10):
        x = start_x + i * (dot_size + dot_gap)
        if i < rating:
            draw.ellipse([x, dot_y, x + dot_size, dot_y + dot_size],
                         fill=rating_color)
        else:
            draw.ellipse([x, dot_y, x + dot_size, dot_y + dot_size],
                         fill=(50, 50, 60), outline=(70, 70, 80))

    label_font = _font(FONT_BOLD, 36)
    bbox = label_font.getbbox("DOENER")
    draw.text(((width - bbox[2]) // 2, dot_y + dot_size + 30),
              "DOENER", font=label_font, fill=TEXT_DIM)

    # Verdict
    if rating <= 3:
        verdict = "Wallah traurig. Finger weg Bruder."
    elif rating <= 5:
        verdict = "Mittelmaessig. Kannste machen, musste aber nicht."
    elif rating <= 7:
        verdict = "Geht klar. Nicht schlecht, nicht geil."
    else:
        verdict = "Mashallah! Solider Job Bruder."
    verdict_font = _font(FONT_REGULAR, 28)
    bbox = verdict_font.getbbox(verdict)
    draw.text(((width - bbox[2]) // 2, 620), verdict, font=verdict_font, fill=TEXT_WHITE)

    sub_font = _font(FONT_REGULAR, 24)
    sub = f"{rating} von 10 Doenern"
    bbox = sub_font.getbbox(sub)
    draw.text(((width - bbox[2]) // 2, height - 120), sub, font=sub_font, fill=rating_color)

    out = os.path.join(settings.output_dir, f"rating_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered rating card: %s (%d/10)", out, rating)
    return out


# ── Ranking Leaderboard ──────────────────────────────────

async def render_ranking_leaderboard(
    jobs: list[JobPosting],
    ratings: list[int],
    ranking_order: list[int],
) -> str:
    """Render final ranking screen (1920x1080, full-screen graphic)."""
    width, height = 1920, 1080
    img = Image.new("RGBA", (width, height), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Header
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
    row_height = 220
    start_y = 240

    for rank_pos, job_idx in enumerate(ranking_order[:3]):
        if job_idx >= len(jobs):
            continue
        job = jobs[job_idx]
        rating = ratings[job_idx] if job_idx < len(ratings) else 5

        y = start_y + rank_pos * row_height

        _draw_rounded_rect(draw, (100, y, width - 100, y + row_height - 20),
                            fill=(*CARD_BG, 200), radius=16,
                            outline=(*rank_colors[rank_pos], 100))

        # Rank number
        rank_font = _font(FONT_BOLD, 80)
        draw.text((140, y + 50), f"#{rank_pos + 1}",
                  font=rank_font, fill=medal_colors[rank_pos])

        # Company circle
        cc = _company_color(job.company)
        ccx = 360
        ccy = y + row_height // 2 - 10
        draw.ellipse([ccx - 35, ccy - 35, ccx + 35, ccy + 35], fill=cc)
        init_font = _font(FONT_BOLD, 32)
        init = job.company[0].upper()
        ibbox = init_font.getbbox(init)
        draw.text((ccx - ibbox[2] // 2, ccy - ibbox[3] // 2 - 2), init,
                  font=init_font, fill=TEXT_WHITE)

        # Job info
        company_font = _font(FONT_BOLD, 32)
        title_font = _font(FONT_REGULAR, 26)
        draw.text((420, y + 40), job.company, font=company_font, fill=TEXT_WHITE)
        title_lines = _wrap_text(job.title, title_font, 800)
        draw.text((420, y + 82), title_lines[0], font=title_font, fill=TEXT_DIM)

        # Rating on right
        r_font = _font(FONT_BOLD, 64)
        r_text = f"{rating}/10"
        r_color = NEON_GREEN if rating >= 7 else NEON_YELLOW if rating >= 4 else NEON_RED
        rbbox = r_font.getbbox(r_text)
        draw.text((width - 250 - rbbox[2] // 2, y + 55), r_text,
                  font=r_font, fill=r_color)

        d_font = _font(FONT_REGULAR, 20)
        dbbox = d_font.getbbox("DOENER")
        draw.text((width - 250 - dbbox[2] // 2, y + 135), "DOENER",
                  font=d_font, fill=TEXT_DIM)

    out = os.path.join(settings.output_dir, f"ranking_{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    logger.info("Rendered ranking leaderboard: %s", out)
    return out
