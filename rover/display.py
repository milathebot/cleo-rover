from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .config import DisplayConfig


@dataclass
class DisplayResult:
    ok: bool
    ready: bool
    reason: str


class NullDisplay:
    ready = False
    last_error: str | None = None

    def show(self, image: Image.Image) -> DisplayResult:
        self.last_error = "display not initialized"
        return DisplayResult(ok=False, ready=False, reason=self.last_error)

    def close(self) -> None:
        return None


def rgb565_bytes(image: Image.Image) -> bytes:
    """Convert a PIL image to big-endian RGB565 bytes for ST7789 displays."""
    rgb = image.convert("RGB")
    out = bytearray(rgb.width * rgb.height * 2)
    idx = 0
    raw = rgb.tobytes()
    for pos in range(0, len(raw), 3):
        red, green, blue = raw[pos], raw[pos + 1], raw[pos + 2]
        value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        out[idx] = (value >> 8) & 0xFF
        out[idx + 1] = value & 0xFF
        idx += 2
    return bytes(out)


class ST7789Display:
    """Tiny ST7789 SPI display driver for Waveshare-style 2inch 240x320 LCDs.

    Uses only optional Pi packages (`spidev`, `gpiozero`) so importing this module on
    a dev machine remains safe. Hardware initialization happens only when this class
    is instantiated in hardware mode.
    """

    def __init__(self, config: DisplayConfig) -> None:
        self.config = config
        self.ready = False
        self.last_error: str | None = None
        self._spi: Any | None = None
        self._dc: Any | None = None
        self._rst: Any | None = None
        self._bl: Any | None = None
        try:
            import spidev  # type: ignore
            from gpiozero import OutputDevice  # type: ignore

            self._dc = OutputDevice(config.dc_pin or 25, active_high=True, initial_value=False)
            if config.reset_pin is not None:
                self._rst = OutputDevice(config.reset_pin, active_high=True, initial_value=True)
            if config.backlight_pin is not None:
                self._bl = OutputDevice(config.backlight_pin, active_high=True, initial_value=True)
            spi = spidev.SpiDev()
            spi.open(config.spi_bus, config.spi_device)
            spi.max_speed_hz = 40_000_000
            spi.mode = 0
            self._spi = spi
            self._reset()
            self._init_panel()
            self.ready = True
        except Exception as exc:  # pragma: no cover - depends on Pi hardware/libs
            self.last_error = repr(exc)
            self.close()

    def _reset(self) -> None:
        if self._rst is None:
            return
        self._rst.on()
        time.sleep(0.05)
        self._rst.off()
        time.sleep(0.05)
        self._rst.on()
        time.sleep(0.12)

    def _write(self, values: list[int] | bytes, *, data: bool) -> None:
        if self._spi is None or self._dc is None:
            raise RuntimeError("display SPI/DC not initialized")
        self._dc.on() if data else self._dc.off()
        if isinstance(values, bytes):
            for start in range(0, len(values), 4096):
                self._spi.writebytes2(values[start : start + 4096])
        else:
            self._spi.writebytes(values)

    def _cmd(self, command: int, data: list[int] | bytes | None = None) -> None:
        self._write([command], data=False)
        if data:
            self._write(data, data=True)

    def _init_panel(self) -> None:
        # ST7789V basic init sequence for 240x320 Waveshare-style panels.
        self._cmd(0x36, [0x00])  # MADCTL: portrait RGB order
        self._cmd(0x3A, [0x55])  # 16-bit RGB565
        self._cmd(0xB2, [0x0C, 0x0C, 0x00, 0x33, 0x33])
        self._cmd(0xB7, [0x35])
        self._cmd(0xBB, [0x19])
        self._cmd(0xC0, [0x2C])
        self._cmd(0xC2, [0x01])
        self._cmd(0xC3, [0x12])
        self._cmd(0xC4, [0x20])
        self._cmd(0xC6, [0x0F])
        self._cmd(0xD0, [0xA4, 0xA1])
        self._cmd(0xE0, [0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23])
        self._cmd(0xE1, [0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23])
        self._cmd(0x21)  # display inversion on, typical for ST7789 modules
        self._cmd(0x11)  # sleep out
        time.sleep(0.12)
        self._cmd(0x29)  # display on
        time.sleep(0.02)

    def _set_window(self, width: int, height: int) -> None:
        x0 = 0
        y0 = 0
        x1 = width - 1
        y1 = height - 1
        self._cmd(0x2A, [x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._cmd(0x2B, [y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._cmd(0x2C)

    def show(self, image: Image.Image) -> DisplayResult:
        if not self.ready:
            return DisplayResult(ok=False, ready=False, reason=self.last_error or "display not ready")
        try:
            frame = image.resize((self.config.width, self.config.height)).convert("RGB")
            if self.config.rotation:
                frame = frame.rotate(self.config.rotation, expand=False)
            self._set_window(frame.width, frame.height)
            self._write(rgb565_bytes(frame), data=True)
            return DisplayResult(ok=True, ready=True, reason="display updated")
        except Exception as exc:  # pragma: no cover - depends on Pi hardware/libs
            self.ready = False
            self.last_error = repr(exc)
            return DisplayResult(ok=False, ready=False, reason=self.last_error)

    def close(self) -> None:
        for device in (self._bl, self._rst, self._dc):
            try:
                if device is not None:
                    device.close()
            except Exception:
                pass
        try:
            if self._spi is not None:
                self._spi.close()
        except Exception:
            pass
        self._spi = None
        self._dc = None
        self._rst = None
        self._bl = None
