"""Progress charts drawn with Pillow, so the same image is shown in the app AND saved in backups."""
from __future__ import annotations

from PIL import Image, ImageDraw

from .fonts import get_font
from .streaks import WeekStat

GREEN = (34, 160, 90)
AMBER = (240, 170, 40)
GREY = (205, 210, 218)
GOLD = (214, 160, 0)
BLUE = (50, 110, 220)
INK = (30, 41, 59)
MUTED = (100, 116, 139)
GRID = (226, 232, 240)


def render_progress_chart(stats: list[WeekStat], title: str = "Weekly task completion",
                          size: tuple[int, int] = (920, 380)) -> Image.Image:
    W, H = size
    img = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((24, 18), title, font=get_font(22, True), fill=INK)

    left, right, top, bottom = 56, 20, 64, 82
    pw, ph = W - left - right, H - top - bottom
    for pct in (0, 50, 100):
        y = top + ph - int(ph * pct / 100)
        d.line((left, y, W - right, y), fill=GRID, width=1)
        d.text((left - 8, y), f"{pct}%", font=get_font(12), fill=MUTED, anchor="rm")

    if not stats:
        d.text((W // 2, H // 2), "No weeks to show yet", font=get_font(16), fill=MUTED, anchor="mm")
        return img

    slot = pw / len(stats)
    bw = max(8, int(slot * 0.58))
    for i, s in enumerate(stats):
        cx = int(left + slot * (i + 0.5))
        frac = s.required_done / s.required_total if s.required_total else 0
        col = GREEN if s.complete else (AMBER if frac > 0 else GREY)
        bh = max(4, int(ph * frac))
        d.rounded_rectangle((cx - bw // 2, top + ph - bh, cx + bw // 2, top + ph), radius=4, fill=col)
        if s.is_current:
            d.rounded_rectangle((cx - bw // 2 - 3, top - 3, cx + bw // 2 + 3, top + ph + 3), radius=6,
                                outline=BLUE, width=2)
        if s.friday_upload:  # gold diamond = uploaded on streak day
            y = top + ph - bh - 12
            d.polygon([(cx, y - 7), (cx + 7, y), (cx, y + 7), (cx - 7, y)], fill=GOLD)
        label = s.week_start.strftime("%d %b")
        d.text((cx, top + ph + 14), label, font=get_font(12, s.is_current), fill=INK if s.is_current else MUTED,
               anchor="mm")
        if s.social_done:
            d.ellipse((cx - 4, top + ph + 30, cx + 4, top + ph + 38), fill=BLUE)

    # legend
    lx, ly = left, H - 22
    for col, txt in ((GREEN, "Week complete"), (AMBER, "Partly done"), (GREY, "Nothing yet")):
        d.rounded_rectangle((lx, ly - 7, lx + 14, ly + 7), radius=3, fill=col)
        d.text((lx + 20, ly), txt, font=get_font(12), fill=MUTED, anchor="lm")
        lx += 20 + int(d.textlength(txt, font=get_font(12))) + 22
    d.polygon([(lx + 7, ly - 7), (lx + 14, ly), (lx + 7, ly + 7), (lx, ly)], fill=GOLD)
    d.text((lx + 20, ly), "Friday upload", font=get_font(12), fill=MUTED, anchor="lm")
    lx += 20 + int(d.textlength("Friday upload", font=get_font(12))) + 22
    d.ellipse((lx, ly - 5, lx + 10, ly + 5), fill=BLUE)
    d.text((lx + 16, ly), "Social card made", font=get_font(12), fill=MUTED, anchor="lm")
    return img


def render_cohort_chart(rows: list[tuple[str, int, int]], title: str = "Cohort overview",
                        width: int = 920) -> Image.Image:
    """rows = [(name, streak_weeks, completion_pct)] -> horizontal completion bars with streak labels."""
    row_h = 34
    H = 70 + max(1, len(rows)) * row_h + 20
    img = Image.new("RGB", (width, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((24, 18), title, font=get_font(22, True), fill=INK)
    d.text((width - 24, 24), "bar = completion %  |  right = streak (weeks)", font=get_font(12), fill=MUTED, anchor="rm")
    name_w, bar_x, bar_w = 220, 250, width - 250 - 120
    if not rows:
        d.text((width // 2, H // 2 + 10), "No students yet", font=get_font(16), fill=MUTED, anchor="mm")
    for i, (name, streak, pct) in enumerate(rows):
        y = 70 + i * row_h
        d.text((24, y + row_h // 2 - 4), name[:28], font=get_font(14), fill=INK, anchor="lm")
        d.rounded_rectangle((bar_x, y, bar_x + bar_w, y + 18), radius=6, fill=GRID)
        if pct > 0:
            d.rounded_rectangle((bar_x, y, bar_x + max(10, int(bar_w * pct / 100)), y + 18), radius=6,
                                fill=GREEN if pct >= 75 else AMBER)
        d.text((bar_x + bar_w + 10, y + 9), f"{pct}%", font=get_font(13, True), fill=INK, anchor="lm")
        d.text((width - 24, y + 9), f"{streak} wk", font=get_font(13, True), fill=GOLD if streak else MUTED, anchor="rm")
    return img
