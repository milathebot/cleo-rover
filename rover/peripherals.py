from __future__ import annotations

import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

FREENOVE_ADC_ADDRESS = 0x48
FREENOVE_RGB_LED_COUNT = 8
FREENOVE_RGB_SPI_BUS = 0
FREENOVE_RGB_SPI_DEVICE = 0
FREENOVE_RGB_ORDER = "GRB"
FREENOVE_RGB_BRIGHTNESS = 24


def _import_smbus() -> Any:
    try:
        from smbus2 import SMBus  # type: ignore
    except ImportError:  # pragma: no cover - Raspberry Pi apt package fallback
        from smbus import SMBus  # type: ignore
    return SMBus


def _import_gpiozero() -> tuple[Any, Any]:
    from gpiozero import DigitalInputDevice, DistanceSensor  # type: ignore

    return DigitalInputDevice, DistanceSensor


class ADS7830:
    """Small ADS7830 reader for the Freenove board ADC at 0x48."""

    def __init__(self, address: int = FREENOVE_ADC_ADDRESS, bus_id: int = 1, voltage_coefficient: float = 5.2) -> None:
        SMBus = _import_smbus()
        self.address = address
        self.voltage_coefficient = voltage_coefficient
        self.bus = SMBus(bus_id)

    def read_channel(self, channel: int) -> float:
        command = 0x84 | ((((channel << 2) | (channel >> 1)) & 0x07) << 4)
        self.bus.write_byte(self.address, command)
        first = int(self.bus.read_byte(self.address))
        second = int(self.bus.read_byte(self.address))
        value = second if first != second else first
        return round(value / 255.0 * self.voltage_coefficient, 3)

    def read_all(self) -> dict[int, float]:
        return {channel: self.read_channel(channel) for channel in range(8)}

    def close(self) -> None:
        self.bus.close()


def estimate_battery_percent(voltage: float | None) -> float | None:
    if voltage is None:
        return None
    # Conservative 2S Li-ion estimate for the Freenove 2x18650 pack.
    low = 6.4
    high = 8.4
    return round(max(0.0, min(1.0, (voltage - low) / (high - low))) * 100, 1)


class FreenoveSensorReader:
    def __init__(self, front_stop_distance_cm: float, adc_voltage_coefficient: float = 5.2) -> None:
        self.front_stop_distance_cm = front_stop_distance_cm
        self.adc_voltage_coefficient = adc_voltage_coefficient

    def read_line_sensors(self) -> dict[str, int] | None:
        DigitalInputDevice, _ = _import_gpiozero()
        pins = {"left": 14, "center": 15, "right": 23}
        devices = {}
        try:
            # Pull-up matched the user's focused test; sensors are optional.
            devices = {name: DigitalInputDevice(pin, pull_up=True) for name, pin in pins.items()}
            return {name: int(device.value) for name, device in devices.items()}
        finally:
            for device in devices.values():
                device.close()

    def read_front_distance_cm(self) -> float | None:
        _, DistanceSensor = _import_gpiozero()
        sensor = None
        try:
            sensor = DistanceSensor(echo=22, trigger=27, max_distance=3.0)
            time.sleep(0.05)
            return round(float(sensor.distance) * 100, 1)
        finally:
            if sensor is not None:
                sensor.close()

    def read_adc(self) -> dict[int, float]:
        adc = ADS7830(voltage_coefficient=self.adc_voltage_coefficient)
        try:
            return adc.read_all()
        finally:
            adc.close()

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "front_distance_cm": None,
            "front_stop_distance_cm": self.front_stop_distance_cm,
            "line_sensors": None,
            "line_sensors_ready": False,
            "adc_channels": None,
            "adc_ready": False,
            "battery_voltage": None,
            "battery_percent": None,
            "errors": {},
        }
        try:
            out["front_distance_cm"] = self.read_front_distance_cm()
            out["ultrasonic_ready"] = out["front_distance_cm"] is not None
        except Exception as exc:  # pragma: no cover - hardware-dependent
            out["ultrasonic_ready"] = False
            out["errors"]["ultrasonic"] = repr(exc)
        try:
            line = self.read_line_sensors()
            out["line_sensors"] = line
            out["line_sensors_ready"] = line is not None
        except Exception as exc:  # pragma: no cover - hardware-dependent
            out["errors"]["line_sensors"] = repr(exc)
        try:
            adc = self.read_adc()
            out["adc_channels"] = {str(k): v for k, v in adc.items()}
            out["adc_ready"] = True
            # Freenove ADS7830 channel 2 is the board power sense in the vendor code.
            battery_voltage = round(adc.get(2, 0.0) * 2, 2)
            out["battery_voltage"] = battery_voltage
            out["battery_percent"] = estimate_battery_percent(battery_voltage)
        except Exception as exc:  # pragma: no cover - hardware-dependent
            out["errors"]["adc"] = repr(exc)
        return out


def audio_devices() -> dict[str, Any]:
    def run(cmd: list[str]) -> dict[str, Any]:
        if not shutil.which(cmd[0]):
            return {"ok": False, "error": f"{cmd[0]} not found"}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=6, check=False)
        return {"ok": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-1000:]}

    return {"playback": run(["aplay", "-l"]), "capture": run(["arecord", "-l"])}


def play_tone(seconds: float = 0.35, hz: int = 880) -> dict[str, Any]:
    if not shutil.which("aplay"):
        return {"ok": False, "error": "aplay not found"}
    seconds = max(0.05, min(2.0, float(seconds)))
    rate = 22050
    path = Path("/tmp/cleo-rover-tone.wav")
    frames = int(rate * seconds)
    import math
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for i in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * hz * i / rate))
            wf.writeframesraw(sample.to_bytes(2, "little", signed=True))
    result = subprocess.run(["aplay", str(path)], capture_output=True, text=True, timeout=5, check=False)
    return {"ok": result.returncode == 0, "path": str(path), "returncode": result.returncode, "stderr_tail": result.stderr[-500:]}


def speak_text(text: str) -> dict[str, Any]:
    text = str(text)[:240]
    if shutil.which("espeak-ng"):
        cmd = ["espeak-ng", text]
    elif shutil.which("espeak"):
        cmd = ["espeak", text]
    else:
        tone = play_tone(0.2, 660)
        return {"ok": False, "error": "no espeak/espeak-ng found", "tone": tone, "text": text}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
    return {"ok": result.returncode == 0, "tool": cmd[0], "text": text, "returncode": result.returncode, "stderr_tail": result.stderr[-500:]}


def camera_tool() -> str | None:
    return shutil.which("rpicam-still") or shutil.which("libcamera-still")


def camera_ready() -> bool:
    tool = camera_tool()
    if not tool:
        return False
    try:
        result = subprocess.run([tool, "--list-cameras"], capture_output=True, text=True, timeout=6, check=False)
    except Exception:
        return False
    return result.returncode == 0 and "Available cameras" in (result.stdout + result.stderr)


def capture_camera_snapshot(output_dir: str | Path = "captures", width: int = 1296, height: int = 972) -> dict[str, Any]:
    tool = camera_tool()
    if not tool:
        return {"ok": False, "error": "no rpicam-still/libcamera-still command found"}
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"snapshot-{int(time.time())}.jpg"
    cmd = [tool, "-o", str(path), "--width", str(width), "--height", str(height), "--timeout", "1000", "--nopreview"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
    ok = result.returncode == 0 and path.exists() and path.stat().st_size > 0
    return {
        "ok": ok,
        "path": str(path),
        "width": width,
        "height": height,
        "bytes": path.stat().st_size if path.exists() else 0,
        "returncode": result.returncode,
        "stderr_tail": result.stderr[-1000:],
    }


class FreenoveRGBStrip:
    """SPI WS2812/NeoPixel control for the Freenove 8-LED board strip."""

    def __init__(self, count: int = FREENOVE_RGB_LED_COUNT, brightness: int = FREENOVE_RGB_BRIGHTNESS, bus: int = FREENOVE_RGB_SPI_BUS, device: int = FREENOVE_RGB_SPI_DEVICE, order: str = FREENOVE_RGB_ORDER) -> None:
        import spidev  # type: ignore

        self.count = count
        self.brightness = max(0, min(255, int(brightness)))
        self.order = order.upper()
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 2_400_000
        self.spi.mode = 0

    def _scale(self, value: int) -> int:
        return int(max(0, min(255, int(value))) * self.brightness / 255)

    @staticmethod
    def _encode_byte(byte: int) -> list[int]:
        bits: list[int] = []
        for bit in range(7, -1, -1):
            bits.extend([1, 1, 0] if byte & (1 << bit) else [1, 0, 0])
        return bits

    @staticmethod
    def _bits_to_bytes(bits: list[int]) -> list[int]:
        data: list[int] = []
        current = 0
        for index, bit in enumerate(bits):
            current = (current << 1) | bit
            if (index + 1) % 8 == 0:
                data.append(current)
                current = 0
        if len(bits) % 8:
            current <<= 8 - (len(bits) % 8)
            data.append(current)
        return data

    def _ordered(self, red: int, green: int, blue: int) -> list[int]:
        colors = {"R": self._scale(red), "G": self._scale(green), "B": self._scale(blue)}
        return [colors[channel] for channel in self.order]

    def set_all(self, red: int, green: int, blue: int) -> None:
        bits: list[int] = []
        for _ in range(self.count):
            for byte in self._ordered(red, green, blue):
                bits.extend(self._encode_byte(byte))
        self.spi.xfer2(self._bits_to_bytes(bits) + [0] * 80)

    def close(self) -> None:
        self.spi.close()


def set_rgb(red: int, green: int, blue: int, brightness: int = FREENOVE_RGB_BRIGHTNESS, count: int = FREENOVE_RGB_LED_COUNT) -> dict[str, Any]:
    strip = FreenoveRGBStrip(count=count, brightness=brightness)
    try:
        strip.set_all(red, green, blue)
    finally:
        strip.close()
    return {"ok": True, "count": count, "red": red, "green": green, "blue": blue, "brightness": brightness, "order": FREENOVE_RGB_ORDER}


def rgb_ready() -> bool:
    try:
        import spidev  # noqa: F401  # type: ignore
    except Exception:
        return False
    return Path("/dev/spidev0.0").exists()
