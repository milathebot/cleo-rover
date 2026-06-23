#!/usr/bin/env python3
"""Generate Pip shell v5: roof-down PETG-friendly canopy.

Design goal from print failure audit:
- Overall assembled length: 200 mm front-to-back.
- Height from installed shell bottom to roof: 80 mm.
- Front face open for turret/camera/ultrasonic view.
- Closed-looking roof/canopy, but printable without giant internal supports.
- Fine futuristic vent styling without unsupported through-grate bridges.

Print orientation: ROOF-DOWN. The roof is the flat first layer on the bed; side
walls rise upward from it during printing. After printing, flip the shell over
and install it on Pip. This avoids spanning a roof over an air cavity.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v5_roofdown"
ZIP = ROOT / "models" / "pip_shell_v5_roofdown_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
INSERT_PILOTS = [4.1, 4.2, 4.3]

# Installed envelope is 200 L x about 110 W x 80 H.
# STL is intentionally roof-down: z=0 is roof/outside during printing.
HALF_LEN = 100.0
WIDTH = 110.0
HALF_W = WIDTH / 2.0
HEIGHT = 80.0
ROOF_T = 3.0
WALL_T = 2.8


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
    ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
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


def roof_panel(x0: float, x1: float) -> list[Tri]:
    """Flat roof-down print base with raised styling that prints as later layers."""
    tris: list[Tri] = []
    tris += box(x0, x1, -50, 50, 0, ROOF_T)
    # Shallow raised roof spine on inner side while printing; cosmetic once flipped.
    tris += triangular_prism_x(x0 + 8, x1 - 8, -9, 9, ROOF_T, ROOF_T + 4.5)
    # Fine top grooves/ridges as printable-on-base details, not bridges.
    for y in (-36, -28, 28, 36):
        tris += box(x0 + 10, x1 - 10, y - 0.7, y + 0.7, ROOF_T, ROOF_T + 1.4)
    return tris


def fine_fake_grille(x0: float, x1: float, y_outer: float, z0: float = 22, z1: float = 66) -> list[Tri]:
    """Raised decorative vent ribs on a solid wall: no through holes, no drooping bridges."""
    tris: list[Tri] = []
    outward = -1 if y_outer < 0 else 1
    # These thin bars are attached to solid wall, so PETG cannot sag across an open slot.
    y0 = y_outer + outward * 0.1
    y1 = y_outer + outward * 1.7
    if y0 > y1:
        y0, y1 = y1, y0
    z = z0
    while z <= z1:
        tris += box(x0, x1, y0, y1, z, z + 1.15)
        z += 4.0
    # vertical interrupters make it look intentional and add stiffness
    for x in [x0 + 16, x0 + 42, x1 - 42, x1 - 16]:
        if x0 < x < x1:
            tris += box(x - 0.8, x + 0.8, y0, y1, z0 - 1, z1 + 2)
    return tris


def side_wall(x0: float, x1: float, y_outer: float) -> list[Tri]:
    tris: list[Tri] = []
    y0, y1 = (y_outer, y_outer + WALL_T) if y_outer < 0 else (y_outer - WALL_T, y_outer)
    tris += box(x0, x1, y0, y1, ROOF_T, HEIGHT)
    # Velcro landings are inside lip pads, printable and functional after flip.
    inside_y0, inside_y1 = (y1, y1 + 3.8) if y_outer < 0 else (y0 - 3.8, y0)
    tris += box(x0 + 8, x1 - 8, min(inside_y0, inside_y1), max(inside_y0, inside_y1), HEIGHT - 7, HEIGHT - 3)
    tris += fine_fake_grille(x0 + 9, x1 - 9, y_outer, z0=24, z1=60)
    # Smooth futuristic lower belt and upper crease.
    tris += box(x0 + 4, x1 - 4, min(y0, y1), max(y0, y1), 67, 72)
    tris += box(x0 + 4, x1 - 4, min(y0, y1), max(y0, y1), 10, 13)
    return tris


def front_body() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = 0.0, HALF_LEN
    tris += roof_panel(x0, x1)
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    # Front face open: only side cheek/brow corners, no center wall.
    tris += box(x0, x0 + 4.0, -HALF_W, -37, ROOF_T, HEIGHT)
    tris += box(x0, x0 + 4.0, 37, HALF_W, ROOF_T, HEIGHT)
    tris += box(x0, x0 + 4.0, -HALF_W, HALF_W, ROOF_T, 13)
    # seam lip at rear half joint
    tris += box(x1 - 4.0, x1, -HALF_W, HALF_W, ROOF_T, 11)
    tris += box(x1 - 4.0, x1, -HALF_W, -43, ROOF_T, HEIGHT)
    tris += box(x1 - 4.0, x1, 43, HALF_W, ROOF_T, HEIGHT)
    return tris


def rear_body() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = HALF_LEN, 2 * HALF_LEN
    tris += roof_panel(x0, x1)
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    # Rear mostly closed for cable coverage, with bottom cable arch/notch after flipping.
    tris += box(x1 - 4.0, x1, -HALF_W, HALF_W, ROOF_T, 52)
    tris += box(x1 - 4.0, x1, -HALF_W, -34, 52, HEIGHT)
    tris += box(x1 - 4.0, x1, 34, HALF_W, 52, HEIGHT)
    # seam lip at front joint
    tris += box(x0, x0 + 4.0, -HALF_W, HALF_W, ROOF_T, 11)
    tris += box(x0, x0 + 4.0, -HALF_W, -43, ROOF_T, HEIGHT)
    tris += box(x0, x0 + 4.0, 43, HALF_W, ROOF_T, HEIGHT)
    # rear faux grille on closed rear face
    for y in [-28, -20, -12, 12, 20, 28]:
        tris += box(x1 - 5.7, x1 - 4.1, y - 0.65, y + 0.65, 24, 50)
    return tris


def seam_clip_pair() -> list[Tri]:
    """Tiny low-profile clips/straps. Tape/Velcro first; holes are M3 clearance if using screws later."""
    tris: list[Tri] = []
    for y in (-31, 31):
        for cx in (-8, 8):
            tris += annular_cylinder(cx, y, 0, 3.2, outer_d=9.2, inner_d=3.4)
        tris += box(-8, 8, y - 4.4, y - 2.3, 0, 3.2)
        tris += box(-8, 8, y + 2.3, y + 4.4, 0, 3.2)
    return tris


def heatset_coupon() -> list[Tri]:
    tris: list[Tri] = []
    tris += box(-36, 36, -10, -6.5, 0, 2.4)
    tris += box(-36, 36, 6.5, 10, 0, 2.4)
    for cx, hole in zip([-24, 0, 24], INSERT_PILOTS):
        tris += annular_cylinder(cx, 0, 0, 6.4, outer_d=12.0, inner_d=hole)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v5 roof-down PETG canopy",
        "",
        "This is the printability audit revision after the clear PETG grate failure.",
        "It keeps the closed futuristic canopy idea, but removes unsupported vent holes and avoids printing a roof over empty air.",
        "",
        "## Dimensions",
        "",
        "- Assembled length: 200 mm front-to-back.",
        "- Width: about 110 mm.",
        "- Installed height, shell bottom to roof: 80 mm.",
        "- Front face remains open for turret/camera/ultrasonic view.",
        "",
        "## Critical print orientation",
        "",
        "Print both body halves ROOF-DOWN, exactly as generated. The large flat roof face goes on the build plate.",
        "After printing, flip the part over and install it on Pip. This makes the roof the first layer instead of an unsupported bridge.",
        "",
        "## What changed from v4",
        "",
        "- No through-hole side grates: the previous slot/grate bridges sagged in PETG.",
        "- Fine grille details are raised ribs on solid walls, so they have material underneath.",
        "- Height reduced from ~95 mm to 80 mm.",
        "- Length reduced/locked to 200 mm total.",
        "- Rear is mostly closed, with a cable notch/arch instead of a long extension.",
        "- Body is split into two 100 mm halves for A1 Mini reliability.",
        "",
        "## Suggested Bambu/PETG clear settings",
        "",
        "- Supports: off for the roof-down halves; use support blockers if Bambu tries to fill the interior.",
        "- Brim: 5-8 mm.",
        "- Layer height: 0.20 mm.",
        "- Walls: 3.",
        "- Infill: 10-15% gyroid/cubic.",
        "- Speed: slow PETG profile, not sport/ludicrous. PETG clear likes stable flow.",
        "- Bed: 75-80 C if adhesion allows; glue stick/release agent on PEI if PETG bonds too hard.",
        "- Dry filament if you see bubbling, excessive strings, or cloudy weak layers.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v5_front_roofdown_body.stl` as the fit/printability test.",
        "2. `pip_shell_v5_rear_roofdown_body.stl`.",
        "3. `pip_shell_v5_seam_clip_pair.stl` only if useful.",
        "4. `pip_shell_v5_insert_coupon_4p1_4p2_4p3.stl` if insert pilot is still unconfirmed.",
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
        "pip_shell_v5_front_roofdown_body.stl": front_body(),
        "pip_shell_v5_rear_roofdown_body.stl": rear_body(),
        "pip_shell_v5_seam_clip_pair.stl": seam_clip_pair(),
        "pip_shell_v5_insert_coupon_4p1_4p2_4p3.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_v5_roofdown/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v5_roofdown/generate_pip_shell_v5_roofdown_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
