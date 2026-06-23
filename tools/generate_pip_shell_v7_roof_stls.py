#!/usr/bin/env python3
"""Generate Pip shell v7 bolt-on roof kit.

Designed to bolt onto the v6 open-top shell insert hardpoints.
- Existing shell insert centers:
  front half x=[22,78], rear half x=[122,178], y=[-47.5,47.5]
- Roof split into two A1 Mini friendly halves, 100 mm each.
- True M3 clearance holes in roof pads, aligned to v6 insert pilots.
- Styled roof with an oval 100 x 50 mm USB mic landing/rim, not a plain flat plate.

Print orientation: flat on bed, decorative side upward. Supports off.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v7_roof"
ZIP = ROOT / "models" / "pip_shell_v7_roof_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
L_TOTAL = 200.0
L_HALF = 100.0
WIDTH = 106.0
HALF_W = WIDTH / 2.0
ROOF_T = 3.2
DETAIL_H = 1.8
M3_CLEARANCE_D = 3.6  # slight clearance for M3 screws into heat-set inserts

SCREW_X_FRONT = [22.0, 78.0]
SCREW_X_REAR = [122.0, 178.0]
SCREW_YS = [-47.5, 47.5]


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    p000 = (x0, y0, z0); p100 = (x1, y0, z0); p110 = (x1, y1, z0); p010 = (x0, y1, z0)
    p001 = (x0, y0, z1); p101 = (x1, y0, z1); p111 = (x1, y1, z1); p011 = (x0, y1, z1)
    return [
        (p000, p110, p100), (p000, p010, p110),
        (p001, p101, p111), (p001, p111, p011),
        (p000, p001, p011), (p000, p011, p010),
        (p100, p110, p111), (p100, p111, p101),
        (p000, p100, p101), (p000, p101, p001),
        (p010, p011, p111), (p010, p111, p110),
    ]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 56) -> list[Tri]:
    tris: list[Tri] = []
    ro = outer_d / 2.0
    ri = inner_d / 2.0
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        o0b = (cx + ro * math.cos(a0), cy + ro * math.sin(a0), z0)
        o1b = (cx + ro * math.cos(a1), cy + ro * math.sin(a1), z0)
        o0t = (cx + ro * math.cos(a0), cy + ro * math.sin(a0), z1)
        o1t = (cx + ro * math.cos(a1), cy + ro * math.sin(a1), z1)
        i0b = (cx + ri * math.cos(a0), cy + ri * math.sin(a0), z0)
        i1b = (cx + ri * math.cos(a1), cy + ri * math.sin(a1), z0)
        i0t = (cx + ri * math.cos(a0), cy + ri * math.sin(a0), z1)
        i1t = (cx + ri * math.cos(a1), cy + ri * math.sin(a1), z1)
        tris += [(o0b, o1b, o1t), (o0b, o1t, o0t)]
        tris += [(i0b, i1t, i1b), (i0b, i0t, i1t)]
        tris += [(o0t, o1t, i1t), (o0t, i1t, i0t)]
        tris += [(o0b, i1b, o1b), (o0b, i0b, i1b)]
    return tris


def elliptical_ring(cx: float, cy: float, z0: float, z1: float, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float, segments: int = 96) -> list[Tri]:
    """Raised oval rim for the USB mic landing. Does not cut the roof base."""
    tris: list[Tri] = []
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        o0b = (cx + outer_rx * math.cos(a0), cy + outer_ry * math.sin(a0), z0)
        o1b = (cx + outer_rx * math.cos(a1), cy + outer_ry * math.sin(a1), z0)
        o0t = (cx + outer_rx * math.cos(a0), cy + outer_ry * math.sin(a0), z1)
        o1t = (cx + outer_rx * math.cos(a1), cy + outer_ry * math.sin(a1), z1)
        i0b = (cx + inner_rx * math.cos(a0), cy + inner_ry * math.sin(a0), z0)
        i1b = (cx + inner_rx * math.cos(a1), cy + inner_ry * math.sin(a1), z0)
        i0t = (cx + inner_rx * math.cos(a0), cy + inner_ry * math.sin(a0), z1)
        i1t = (cx + inner_rx * math.cos(a1), cy + inner_ry * math.sin(a1), z1)
        tris += [(o0b, o1b, o1t), (o0b, o1t, o0t)]
        tris += [(i0b, i1t, i1b), (i0b, i0t, i1t)]
        tris += [(o0t, o1t, i1t), (o0t, i1t, i0t)]
        tris += [(o0b, i1b, o1b), (o0b, i0b, i1b)]
    return tris


def triangular_prism_x(x0: float, x1: float, y0: float, y1: float, z_base: float, z_peak: float) -> list[Tri]:
    ym = (y0 + y1) / 2.0
    a0 = (x0, y0, z_base); b0 = (x0, y1, z_base); c0 = (x0, ym, z_peak)
    a1 = (x1, y0, z_base); b1 = (x1, y1, z_base); c1 = (x1, ym, z_peak)
    return [
        (a0, c0, b0), (a1, b1, c1),
        (a0, a1, c1), (a0, c1, c0),
        (b0, c0, c1), (b0, c1, b1),
        (a0, b0, b1), (a0, b1, a1),
    ]


def normal(a: Vec, b: Vec, c: Vec) -> Vec:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy*vz - uz*vy, uz*vx - ux*vz, ux*vy - uy*vx
    length = (nx*nx + ny*ny + nz*nz) ** 0.5 or 1.0
    return (nx/length, ny/length, nz/length)


def write_stl(path: Path, name: str, tris: Iterable[Tri]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"solid {name}\n")
        for a, b, c in tris:
            n = normal(a, b, c)
            f.write(f"  facet normal {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}\n")
            f.write("    outer loop\n")
            for p in (a, b, c):
                f.write(f"      vertex {p[0]:.6g} {p[1]:.6g} {p[2]:.6g}\n")
            f.write("    endloop\n  endfacet\n")
        f.write(f"endsolid {name}\n")


def bounds(tris: Iterable[Tri]) -> tuple[Vec, Vec, Vec]:
    xs: list[float] = []; ys: list[float] = []; zs: list[float] = []
    for tri in tris:
        for x, y, z in tri:
            xs.append(x); ys.append(y); zs.append(z)
    mn = (min(xs), min(ys), min(zs)); mx = (max(xs), max(ys), max(zs))
    return mn, mx, (mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2])


def screw_pad(cx: float, cy: float) -> list[Tri]:
    # True clearance hole, not a filled circle. The surrounding roof does not cover this pad.
    tris = annular_cylinder(cx, cy, 0, ROOF_T + DETAIL_H, outer_d=13.0, inner_d=M3_CLEARANCE_D)
    # small ribs to connect the pad to nearby roof rails without crossing the hole
    if cy < 0:
        tris += box(cx - 7, cx + 7, -53.0, -51.0, 0, ROOF_T)
        tris += box(cx - 7, cx - 4.2, -51.0, -43.0, 0, ROOF_T)
        tris += box(cx + 4.2, cx + 7, -51.0, -43.0, 0, ROOF_T)
    else:
        tris += box(cx - 7, cx + 7, 51.0, 53.0, 0, ROOF_T)
        tris += box(cx - 7, cx - 4.2, 43.0, 51.0, 0, ROOF_T)
        tris += box(cx + 4.2, cx + 7, 43.0, 51.0, 0, ROOF_T)
    return tris


def side_rail_segments(x0: float, x1: float, screw_xs: list[float], y_sign: int) -> list[Tri]:
    """Side roof rail split around screw holes so pads stay truly open."""
    tris: list[Tri] = []
    y_outer0, y_outer1 = (48.5, 53.0) if y_sign > 0 else (-53.0, -48.5)
    y_inner0, y_inner1 = (35.5, 40.0) if y_sign > 0 else (-40.0, -35.5)
    keepouts = [(x - 8.0, x + 8.0) for x in screw_xs]
    ranges = [(x0 + 4, x1 - 4)]
    for a, b in keepouts:
        new_ranges = []
        for r0, r1 in ranges:
            if b <= r0 or a >= r1:
                new_ranges.append((r0, r1))
            else:
                if r0 < a:
                    new_ranges.append((r0, a))
                if b < r1:
                    new_ranges.append((b, r1))
        ranges = new_ranges
    for a, b in ranges:
        if b - a > 1:
            tris += box(a, b, min(y_outer0, y_outer1), max(y_outer0, y_outer1), 0, ROOF_T)
            tris += box(a, b, min(y_inner0, y_inner1), max(y_inner0, y_inner1), 0, ROOF_T)
    return tris


def clipped_elliptical_ring(cx: float, cy: float, z0: float, z1: float, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float, clip_x0: float, clip_x1: float, segments: int = 128) -> list[Tri]:
    """Ellipse ring segments clipped to one roof half's x range."""
    tris: list[Tri] = []
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        xs = [cx + outer_rx * math.cos(a0), cx + outer_rx * math.cos(a1), cx + inner_rx * math.cos(a0), cx + inner_rx * math.cos(a1)]
        # Skip segments outside this half. This creates a clean split-line at x=100 rather than overlap.
        if max(xs) < clip_x0 or min(xs) > clip_x1:
            continue
        if min(xs) < clip_x0 or max(xs) > clip_x1:
            # Avoid triangles crossing the split boundary; the neighboring half supplies the continuation.
            continue
        o0b = (cx + outer_rx * math.cos(a0), cy + outer_ry * math.sin(a0), z0)
        o1b = (cx + outer_rx * math.cos(a1), cy + outer_ry * math.sin(a1), z0)
        o0t = (cx + outer_rx * math.cos(a0), cy + outer_ry * math.sin(a0), z1)
        o1t = (cx + outer_rx * math.cos(a1), cy + outer_ry * math.sin(a1), z1)
        i0b = (cx + inner_rx * math.cos(a0), cy + inner_ry * math.sin(a0), z0)
        i1b = (cx + inner_rx * math.cos(a1), cy + inner_ry * math.sin(a1), z0)
        i0t = (cx + inner_rx * math.cos(a0), cy + inner_ry * math.sin(a0), z1)
        i1t = (cx + inner_rx * math.cos(a1), cy + inner_ry * math.sin(a1), z1)
        tris += [(o0b, o1b, o1t), (o0b, o1t, o0t)]
        tris += [(i0b, i1t, i1b), (i0b, i0t, i1t)]
        tris += [(o0t, o1t, i1t), (o0t, i1t, i0t)]
        tris += [(o0b, i1b, o1b), (o0b, i0b, i1b)]
    return tris


def mic_landing_details(x0: float, x1: float) -> list[Tri]:
    """Aesthetic raised oval mic landing, split cleanly across front/rear roof halves."""
    tris: list[Tri] = []
    # Full mic footprint is centered at x=100 and y=0: 100 x 50 mm oval.
    tris += clipped_elliptical_ring(100.0, 0.0, ROOF_T, ROOF_T + 1.4, outer_rx=52.0, outer_ry=27.0, inner_rx=48.0, inner_ry=23.0, clip_x0=x0, clip_x1=x1)
    # low cable guide channel toward rear for USB mic cable; does not cut through the roof.
    if x1 > 150:
        tris += box(151, min(x1 - 8, 194), -4.5, -2.0, ROOF_T, ROOF_T + 1.2)
        tris += box(151, min(x1 - 8, 194), 2.0, 4.5, ROOF_T, ROOF_T + 1.2)
    return tris


def roof_half(name: str, x0: float, x1: float, screw_xs: list[float]) -> list[Tri]:
    tris: list[Tri] = []
    # Four main panels around the mic landing. This avoids being a boring flat sheet while leaving a clear mic footprint.
    tris += box(x0 + 5, x1 - 5, -34, -28, 0, ROOF_T)
    tris += box(x0 + 5, x1 - 5, 28, 34, 0, ROOF_T)
    # front/rear armor panels outside mic oval footprint
    if x0 < 50:
        tris += box(x0 + 6, min(x1 - 6, 48), -28, 28, 0, ROOF_T)
    if x1 > 150:
        tris += box(max(x0 + 6, 152), x1 - 6, -28, 28, 0, ROOF_T)
    # side rails and screw pads
    tris += side_rail_segments(x0, x1, screw_xs, y_sign=-1)
    tris += side_rail_segments(x0, x1, screw_xs, y_sign=1)
    for sx in screw_xs:
        for sy in SCREW_YS:
            tris += screw_pad(sx, sy)
    # styled roof spine/creases, low and printable flat
    tris += triangular_prism_x(x0 + 12, x1 - 12, -9, 9, ROOF_T, ROOF_T + 3.6)
    for y in [-43, -37, 37, 43]:
        tris += box(x0 + 14, x1 - 14, y - 0.7, y + 0.7, ROOF_T, ROOF_T + 1.2)
    tris += mic_landing_details(x0, x1)
    # Trim geometry to half bounds would need boolean; instead all generated details are within or intentionally at split.
    return tris


def front_roof() -> list[Tri]:
    return roof_half("front", 0.0, 100.0, SCREW_X_FRONT)


def rear_roof() -> list[Tri]:
    return roof_half("rear", 100.0, 200.0, SCREW_X_REAR)


def mic_fit_template() -> list[Tri]:
    """Tiny outline-only template for checking the 100 x 50 mm mic footprint on the physical USB mic."""
    tris: list[Tri] = []
    tris += elliptical_ring(0, 0, 0, 1.6, outer_rx=50.0, outer_ry=25.0, inner_rx=47.5, inner_ry=22.5)
    tris += box(-50, 50, -1.0, 1.0, 0, 1.6)
    tris += box(-1.0, 1.0, -25, 25, 0, 1.6)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v7 bolt-on roof kit",
        "",
        "Styled roof kit for the v6 open-top Pip shell. This is the finishing-touch roof, not a flat cap.",
        "It bolts to the M3 heat-set insert hardpoints already added to the v6 side-wall top rims.",
        "",
        "## Alignment",
        "",
        "- Front roof screw centers: x=22 and 78 mm, y=±47.5 mm.",
        "- Rear roof screw centers: x=122 and 178 mm, y=±47.5 mm.",
        "- Roof screw holes are true 3.6 mm M3 clearance holes.",
        "- These line up with v6 shell insert pilots/heat-set insert bosses.",
        "",
        "## USB mic landing",
        "",
        "- Oval raised mic landing/rim is centered across the assembled roof.",
        "- Nominal mic footprint: 100 x 50 mm.",
        "- Use thin Velcro/VHB inside the oval rim. The rear half includes a small cable-guide detail.",
        "",
        "## Print settings",
        "",
        "- Print flat on bed, decorative side up.",
        "- Supports: off.",
        "- Brim: optional; use if PETG corners lift.",
        "- PETG clear: 0.20 mm, 3 walls, 10-15% infill, normal/slow speed.",
        "",
        "## Install notes",
        "",
        "- Test-fit roof on the shell before melting inserts if possible.",
        "- Use M3 x 6 screws first. Avoid bottoming out into inserts/electronics.",
        "- If holes feel tight, lightly clean with a 3.5-3.6 mm drill by hand.",
        "- Keep the mic cable loose enough that it does not tug the roof or turret wiring.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v7_front_styled_roof.stl": front_roof(),
        "pip_shell_v7_rear_styled_roof.stl": rear_roof(),
        "pip_shell_v7_usb_mic_100x50_fit_template.stl": mic_fit_template(),
    }
    results: list[tuple[str, Vec]] = []
    for filename, tris in parts.items():
        _, _, size = bounds(tris)
        results.append((filename, size))
        write_stl(OUT / filename, filename.removesuffix(".stl"), tris)
    readme = readme_text(results)
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    with ZipFile(ZIP, "w", ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f"pip_shell_v7_roof/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v7_roof/generate_pip_shell_v7_roof_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
