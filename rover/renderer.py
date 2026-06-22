from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import ExpressionCommand, ExpressionMode

WAVESHARE_W = 240
WAVESHARE_H = 320

Palette = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]

PALETTES: dict[ExpressionMode, Palette] = {
    ExpressionMode.idle: ((86, 42, 180), (16, 210, 220), (230, 68, 190)),
    ExpressionMode.happy: ((40, 230, 170), (90, 255, 230), (255, 120, 230)),
    ExpressionMode.sad: ((12, 22, 70), (35, 80, 180), (110, 80, 160)),
    ExpressionMode.listening: ((20, 130, 255), (40, 230, 255), (110, 90, 255)),
    ExpressionMode.thinking: ((92, 35, 180), (180, 70, 255), (45, 210, 235)),
    ExpressionMode.confused: ((255, 170, 45), (140, 75, 255), (60, 230, 255)),
    ExpressionMode.speaking: ((250, 58, 190), (60, 220, 255), (170, 80, 255)),
    ExpressionMode.alert: ((255, 132, 32), (255, 72, 72), (250, 210, 90)),
    ExpressionMode.mad: ((255, 20, 45), (120, 0, 20), (255, 130, 40)),
    ExpressionMode.focused: ((20, 70, 170), (60, 210, 255), (230, 245, 255)),
    ExpressionMode.laugh: ((255, 120, 230), (255, 210, 80), (80, 245, 255)),
    ExpressionMode.charging: ((50, 230, 160), (72, 170, 255), (160, 90, 255)),
    ExpressionMode.disconnected: ((55, 70, 100), (120, 145, 190), (20, 30, 50)),
    ExpressionMode.manual: ((50, 255, 130), (80, 220, 255), (30, 160, 80)),
    ExpressionMode.curious: ((120, 70, 255), (50, 245, 230), (245, 90, 200)),
    ExpressionMode.watching: ((30, 100, 210), (80, 230, 255), (40, 60, 120)),
    ExpressionMode.seeking: ((255, 90, 180), (120, 240, 255), (160, 90, 255)),
    ExpressionMode.sleeping: ((20, 20, 55), (90, 80, 150), (10, 12, 28)),
    ExpressionMode.shy: ((145, 70, 180), (255, 120, 190), (60, 50, 120)),
    ExpressionMode.proud: ((255, 180, 65), (250, 90, 210), (80, 220, 255)),
    ExpressionMode.low_power: ((120, 80, 40), (255, 90, 70), (50, 40, 35)),
}

LABELS: dict[ExpressionMode, str] = {
    ExpressionMode.idle: "CLEO",
    ExpressionMode.happy: "HAPPY",
    ExpressionMode.sad: "QUIET",
    ExpressionMode.listening: "LISTENING",
    ExpressionMode.thinking: "THINKING",
    ExpressionMode.confused: "CONFUSED",
    ExpressionMode.speaking: "SPEAKING",
    ExpressionMode.alert: "ALERT",
    ExpressionMode.mad: "NOPE",
    ExpressionMode.focused: "FOCUSED",
    ExpressionMode.laugh: "HEHE",
    ExpressionMode.charging: "CHARGING",
    ExpressionMode.disconnected: "OFFLINE",
    ExpressionMode.manual: "MANUAL",
    ExpressionMode.curious: "CURIOUS",
    ExpressionMode.watching: "WATCHING",
    ExpressionMode.seeking: "SEEKING",
    ExpressionMode.sleeping: "SLEEPING",
    ExpressionMode.shy: "QUIET",
    ExpressionMode.proud: "GOOD",
    ExpressionMode.low_power: "LOW POWER",
}


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


@dataclass(frozen=True)
class ExpressionFrame:
    image: Image.Image

    def png_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        return buf.getvalue()


def render_expression(command: ExpressionCommand, *, width: int = WAVESHARE_W, height: int = WAVESHARE_H, t: float | None = None) -> ExpressionFrame:
    """Render Cleo's non-human astral expression panel.

    Default orientation is portrait 240x320 for the Waveshare 2-inch ST7789.
    The physical shell can mount this behind a landscape slit/window if desired,
    but rendering portrait first matches the hardware module.
    """

    t = time.time() if t is None else t
    palette = PALETTES[command.mode]
    brightness = max(0.05, min(1.0, command.brightness))

    img = Image.new("RGB", (width, height), (3, 4, 10))
    px = img.load()

    # Soft vertical astral gradient with a moving wave field.
    phase = t * 0.55
    for y in range(height):
        gy = y / max(1, height - 1)
        base = _mix(palette[0], palette[1], 0.5 + 0.5 * math.sin(gy * math.pi * 1.2 + phase))
        for x in range(width):
            gx = x / max(1, width - 1)
            wave = 0.5 + 0.5 * math.sin(gx * math.tau * 1.7 + gy * math.tau * 2.2 + phase)
            pulse = 0.5 + 0.5 * math.sin((gx - gy) * math.tau + phase * 1.7)
            c = _mix(base, palette[2], wave * 0.35 + pulse * 0.15)
            vignette = 1.0 - 0.62 * math.hypot(gx - 0.5, gy - 0.5)
            scale = brightness * max(0.18, vignette) * (0.42 + 0.58 * wave)
            px[x, y] = tuple(max(0, min(255, int(v * scale))) for v in c)

    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    draw = ImageDraw.Draw(img, "RGBA")

    # Central luminous slit/presence band.
    band_h = max(36, height // 7)
    band_y = height // 2 - band_h // 2
    for i in range(10):
        alpha = max(0, 90 - i * 8)
        draw.rounded_rectangle(
            [18 - i, band_y - i, width - 18 + i, band_y + band_h + i],
            radius=18 + i,
            outline=(*palette[1], alpha),
            width=1,
        )
    draw.rounded_rectangle([20, band_y, width - 20, band_y + band_h], radius=18, fill=(0, 0, 0, 70), outline=(*palette[1], 130), width=2)

    # Mode-specific inner motion language.
    if command.mode == ExpressionMode.speaking:
        bars = 22
        for i in range(bars):
            x = 30 + i * ((width - 60) / (bars - 1))
            amp = 0.25 + 0.75 * abs(math.sin(phase * 5 + i * 0.75))
            h = 8 + amp * (band_h - 14)
            draw.rounded_rectangle([x - 2, height / 2 - h / 2, x + 2, height / 2 + h / 2], radius=2, fill=(*palette[1], 210))
    elif command.mode == ExpressionMode.listening:
        sweep_x = 28 + ((math.sin(phase * 2.2) + 1) / 2) * (width - 56)
        draw.ellipse([sweep_x - 10, height / 2 - 10, sweep_x + 10, height / 2 + 10], fill=(*palette[1], 210))
        draw.line([width / 2, band_y + 9, sweep_x, height / 2], fill=(*palette[1], 110), width=2)
    elif command.mode == ExpressionMode.thinking:
        for i in range(7):
            x = 36 + i * 28
            y = height / 2 + math.sin(phase * 2 + i) * 10
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(*palette[2], 190))
    elif command.mode == ExpressionMode.alert:
        draw.rounded_rectangle([28, band_y + 9, width - 28, band_y + band_h - 9], radius=10, fill=(*palette[0], 190))
    else:
        # Calm horizontal energy line.
        for i in range(3):
            y = height / 2 + (i - 1) * 7 + math.sin(phase + i) * 2
            draw.line([34, y, width - 34, y], fill=(*palette[(i + 1) % 3], 150), width=2)

    # Label and optional short text.
    label = command.text or LABELS[command.mode]
    label = label[:24]
    font = _font(18)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) / 2, height - 38), label, font=font, fill=(235, 245, 255, 210))

    # Tiny top status line.
    top = command.mode.value.upper()
    small = _font(11)
    bbox = draw.textbbox((0, 0), top, font=small)
    draw.text(((width - (bbox[2] - bbox[0])) / 2, 12), top, font=small, fill=(210, 230, 255, 135))

    return ExpressionFrame(img)


def render_all_modes(out_dir: str) -> list[str]:
    from pathlib import Path

    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for mode in ExpressionMode:
        cmd = ExpressionCommand(mode=mode, text=None, brightness=0.78)
        frame = render_expression(cmd, t=123.45)
        out = p / f"{mode.value}.png"
        frame.image.save(out)
        paths.append(str(out))
    return paths
