from PIL import Image

from rover.display import NullDisplay, rgb565_bytes


def test_rgb565_conversion_known_pixels():
    image = Image.new("RGB", (3, 1))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert rgb565_bytes(image) == bytes([0xF8, 0x00, 0x07, 0xE0, 0x00, 0x1F])


def test_null_display_is_safe_without_pi_hardware():
    display = NullDisplay()
    result = display.show(Image.new("RGB", (2, 2)))
    assert result.ok is False
    assert result.ready is False
    assert "not initialized" in result.reason
