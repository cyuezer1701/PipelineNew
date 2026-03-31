"""Job Card Renderer — renders job postings as styled PNG images.

Creates LinkedIn/Indeed-style job posting cards with a red "ROAST" stamp overlay.
Uses Pillow (PIL) for pure-Python image generation (no external API needed).
"""
from __future__ import annotations

import logging
import os
import uuid

from app.config import settings
from app.models import JobPosting

logger = logging.getLogger(__name__)


async def render_job_card(
    job: JobPosting,
    width: int = 1400,
    height: int = 800,
) -> str:
    """Render a job posting as a styled PNG card image."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None, _render_card_sync, job, width, height
    )


def _render_card_sync(job: JobPosting, width: int, height: int) -> str:
    """Synchronous card rendering with Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    # Create canvas
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Card background (LinkedIn-style light gray with rounded corners)
    card_margin = 40
    card_rect = [card_margin, card_margin, width - card_margin, height - card_margin]
    _draw_rounded_rect(draw, card_rect, radius=20, fill=(39, 39, 41, 230))  # Dark mode card

    # Fonts (use system DejaVu since it's installed in Docker)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_path_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        font_title = ImageFont.truetype(font_path, 36)
        font_company = ImageFont.truetype(font_path_regular, 24)
        font_body = ImageFont.truetype(font_path_regular, 22)
        font_tag = ImageFont.truetype(font_path, 18)
        font_salary = ImageFont.truetype(font_path, 32)
        font_stamp = ImageFont.truetype(font_path, 72)
    except OSError:
        font_title = ImageFont.load_default()
        font_company = font_title
        font_body = font_title
        font_tag = font_title
        font_salary = font_title
        font_stamp = font_title

    x_start = card_margin + 40
    y = card_margin + 40

    # Company logo placeholder (colored circle with initial)
    logo_size = 50
    logo_color = _company_color(job.company)
    draw.ellipse([x_start, y, x_start + logo_size, y + logo_size], fill=logo_color)
    initial = job.company[0].upper() if job.company else "?"
    bbox = draw.textbbox((0, 0), initial, font=font_title)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x_start + (logo_size - iw) // 2, y + (logo_size - ih) // 2 - 4),
              initial, fill=(255, 255, 255), font=font_title)

    # Company name + location
    text_x = x_start + logo_size + 20
    draw.text((text_x, y), job.company, fill=(180, 180, 185), font=font_company)
    y += 30
    if job.location:
        draw.text((text_x, y), job.location, fill=(130, 131, 132), font=font_body)
    y += 50

    # Job title
    title_wrapped = _wrap_text(job.title, font_title, width - 2 * (card_margin + 40) - 20, draw)
    for line in title_wrapped[:2]:
        draw.text((x_start, y), line, fill=(255, 255, 255), font=font_title)
        y += 44
    y += 15

    # Salary (if available)
    if job.salary:
        draw.text((x_start, y), job.salary, fill=(76, 175, 80), font=font_salary)
        y += 50
    else:
        draw.text((x_start, y), "Gehalt: Verhandlungsbasis", fill=(255, 100, 100), font=font_company)
        y += 40

    # Benefits as pills/tags
    if job.benefits:
        tag_x = x_start
        y += 10
        for benefit in job.benefits[:6]:
            tag_w = draw.textlength(benefit, font=font_tag) + 24
            if tag_x + tag_w > width - card_margin - 40:
                tag_x = x_start
                y += 38
            # Green pill background
            _draw_rounded_rect(draw, [tag_x, y, tag_x + tag_w, y + 30],
                             radius=15, fill=(30, 70, 32, 200))
            draw.text((tag_x + 12, y + 4), benefit, fill=(130, 220, 130), font=font_tag)
            tag_x += tag_w + 10
        y += 45

    # Requirements (bullet points)
    if job.requirements:
        y += 5
        draw.text((x_start, y), "Anforderungen:", fill=(150, 150, 155), font=font_company)
        y += 32
        for req in job.requirements[:4]:
            req_text = f"  •  {req}"
            req_wrapped = _wrap_text(req_text, font_body, width - 2 * (card_margin + 40) - 20, draw)
            for line in req_wrapped[:1]:
                draw.text((x_start, y), line, fill=(200, 200, 205), font=font_body)
                y += 28

    # Red "ROAST" stamp (diagonal, semi-transparent)
    stamp_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    stamp_draw = ImageDraw.Draw(stamp_img)
    stamp_draw.text((width // 2 - 120, height // 2 - 80), "ROAST",
                    fill=(255, 40, 40, 90), font=font_stamp)
    stamp_rotated = stamp_img.rotate(-25, expand=False, center=(width // 2, height // 2))
    img = Image.alpha_composite(img, stamp_rotated)

    # Save
    output_path = os.path.join(settings.output_dir, f"jobcard_{uuid.uuid4().hex[:8]}.png")
    img.save(output_path, "PNG")

    logger.info("Job card rendered: %s (%s at %s)", output_path, job.title, job.company)
    return output_path


def _draw_rounded_rect(draw, rect, radius, fill):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = rect
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.pieslice([x1, y1, x1 + 2 * radius, y1 + 2 * radius], 180, 270, fill=fill)
    draw.pieslice([x2 - 2 * radius, y1, x2, y1 + 2 * radius], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - 2 * radius, x1 + 2 * radius, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - 2 * radius, y2 - 2 * radius, x2, y2], 0, 90, fill=fill)


def _company_color(name: str) -> tuple:
    """Generate a consistent color from company name."""
    colors = [
        (66, 133, 244), (219, 68, 55), (244, 180, 0), (15, 157, 88),
        (171, 71, 188), (0, 172, 193), (255, 112, 67), (92, 107, 192),
    ]
    return colors[hash(name) % len(colors)]


def _wrap_text(text: str, font, max_width: float, draw) -> list[str]:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines
