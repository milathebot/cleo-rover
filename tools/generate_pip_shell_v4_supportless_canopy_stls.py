#!/usr/bin/env python3
"""Generate Pip shell v4: support-light modular canopy.

Why v4 exists: the v3 one-piece front canopy needs lots of slicer support under
the roof, causing ~14 hour PETG prints. This revision keeps the same finished
closed-canopy idea, but splits the roof into flat separate panels so the tall
side bodies print without roof support.

Design intent:
- Front face remains open for ultrasonic/camera/turret view.
- Roof over turret still exists after assembly, with ~100 mm clearance.
- Side walls are smoother and mostly closed, using fine horizontal grille slats.
- Rear extends ~50 mm as a cable shroud.
- Velcro-first attachment to rover and roof panels; heat-set inserts retained
  only for optional seam bridges/hardpoints.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v4_supportless_canopy"
ZIP = ROOT / "models" / "pip_shell_v4_supportless_canopy_bambu_a1_mini.zip"
BUILD_VOLUME = (180.0, 180.0, 180.0)

WIDTH = 108.0
Y_OUT = WIDTH / 2
WALL = 2.8
LOWER_Z = 8.0
ROOF_CLEAR_Z = 100.0
TOP_RAIL_Z = 97.0
INSERT_PILOT_D = 4.2
INSERT_DEPTH = 6.4
M3_CLEARANCE_D = 3.4


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


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 48) -> list[Tri]:
    tris: list[Tri] = []
    ro = outer_d / 2
    ri = inner_d / 2
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
    ym = (y0 + y1) / 2
    a0 = (x0, y0, z_base); b0 = (x0, y1, z_base); c0 = (x0, ym, z_peak)
    a1 = (x1, y0, z_base); b1 = (x1, y1, z_base); c1 = (x1, ym, z_peak)
    return [(a0,c0,b0), (a1,b1,c1), (a0,a1,c1), (a0,c1,c0), (b0,c0,c1), (b0,c1,b1), (a0,b0,b1), (a0,b1,a1)]


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


def side_wall_with_fine_grille(x0: float, x1: float, y_outer: float) -> list[Tri]:
    tris: list[Tri] = []
    if y_outer < 0:
        y0, y1 = y_outer, y_outer + WALL
        accent_y0, accent_y1 = y_outer - 1.0, y_outer
    else:
        y0, y1 = y_outer - WALL, y_outer
        accent_y0, accent_y1 = y_outer, y_outer + 1.0
    # bottom/top belts and vertical hidden ribs
    tris += box(x0, x1, y0, y1, LOWER_Z, LOWER_Z + 7)
    tris += box(x0, x1, y0, y1, TOP_RAIL_Z - 9, TOP_RAIL_Z)
    for px in [x0, x0 + 30, x0 + 60, x0 + 90, x1 - 5]:
        if px + 5 <= x1:
            tris += box(px, px + 5, y0, y1, LOWER_Z, TOP_RAIL_Z)
    # Fine vent slats: thin, even, deliberate.
    vent_x0 = x0 + 8
    vent_x1 = x1 - 8
    for z in [23, 29, 35, 41, 47, 53, 59, 65, 71, 77]:
        tris += box(vent_x0, vent_x1, y0, y1, z, z + 1.45)
    # Smooth outside styling rails.
    tris += box(x0 + 10, x1 - 10, accent_y0, accent_y1, 84, 87)
    tris += box(x0 + 14, x1 - 14, accent_y0, accent_y1, 18, 20)
    tris += box(x0 + 18, x0 + 46, accent_y0, accent_y1, 78, 83)
    if x1 - x0 > 90:
        tris += box(x1 - 50, x1 - 22, accent_y0, accent_y1, 78, 83)
    return tris


def front_open_face_frame() -> list[Tri]:
    tris: list[Tri] = []
    # Open central face. Only side pillars and a top receiving rail for the separate roof.
    tris += box(0, 5, -Y_OUT, -34, LOWER_Z, TOP_RAIL_Z)
    tris += box(0, 5, 34, Y_OUT, LOWER_Z, TOP_RAIL_Z)
    tris += box(0, 7, -Y_OUT, Y_OUT, TOP_RAIL_Z - 10, TOP_RAIL_Z)
    tris += box(0, 9, -Y_OUT, -38, LOWER_Z, LOWER_Z + 7)
    tris += box(0, 9, 38, Y_OUT, LOWER_Z, LOWER_Z + 7)
    return tris


def rear_cable_wall() -> list[Tri]:
    tris: list[Tri] = []
    # Mostly closed rear, but lower center and bottom stay relieved for cable bend radius.
    tris += box(247, 250, -Y_OUT, Y_OUT, LOWER_Z, 24)
    tris += box(247, 250, -Y_OUT, -25, 24, TOP_RAIL_Z)
    tris += box(247, 250, 25, Y_OUT, 24, TOP_RAIL_Z)
    tris += box(247, 250, -Y_OUT, Y_OUT, TOP_RAIL_Z - 10, TOP_RAIL_Z)
    return tris


def velcro_landing(x0: float, x1: float) -> list[Tri]:
    tris: list[Tri] = []
    tris += box(x0, x1, -Y_OUT + 7, -Y_OUT + 12, LOWER_Z, LOWER_Z + 6)
    tris += box(x0, x1, Y_OUT - 12, Y_OUT - 7, LOWER_Z, LOWER_Z + 6)
    return tris


def insert_boss(cx: float, cy: float, z0: float = TOP_RAIL_Z) -> list[Tri]:
    tris = annular_cylinder(cx, cy, z0, z0 + INSERT_DEPTH, 12.0, INSERT_PILOT_D)
    tris += box(cx - 7, cx + 7, cy - 7, cy + 7, z0 - 2.2, z0)
    return tris


def seam_bosses(x_values: list[float]) -> list[Tri]:
    tris: list[Tri] = []
    for x in x_values:
        for y in (-32, 32):
            tris += insert_boss(x, y)
    return tris


def front_body() -> list[Tri]:
    tris: list[Tri] = []
    tris += side_wall_with_fine_grille(0, 125, -Y_OUT)
    tris += side_wall_with_fine_grille(0, 125, Y_OUT)
    tris += front_open_face_frame()
    tris += seam_bosses([116])
    tris += velcro_landing(18, 116)
    # Roof ledges for separate roof panel to sit on, no large horizontal span.
    tris += box(5, 125, -Y_OUT + 4, -Y_OUT + 13, TOP_RAIL_Z, TOP_RAIL_Z + 3)
    tris += box(5, 125, Y_OUT - 13, Y_OUT - 4, TOP_RAIL_Z, TOP_RAIL_Z + 3)
    # seam tongue pads
    tris += box(121, 125, -42, -34, 80, TOP_RAIL_Z - 4)
    tris += box(121, 125, 34, 42, 80, TOP_RAIL_Z - 4)
    return tris


def rear_body() -> list[Tri]:
    tris: list[Tri] = []
    tris += side_wall_with_fine_grille(125, 250, -Y_OUT)
    tris += side_wall_with_fine_grille(125, 250, Y_OUT)
    tris += rear_cable_wall()
    tris += seam_bosses([134])
    tris += velcro_landing(134, 232)
    tris += box(125, 250, -Y_OUT + 4, -Y_OUT + 13, TOP_RAIL_Z, TOP_RAIL_Z + 3)
    tris += box(125, 250, Y_OUT - 13, Y_OUT - 4, TOP_RAIL_Z, TOP_RAIL_Z + 3)
    tris += box(125, 130, -43, -34, 80, TOP_RAIL_Z - 4)
    tris += box(125, 130, 34, 43, 80, TOP_RAIL_Z - 4)
    return tris


def roof_panel(x0: float, x1: float, name: str) -> list[Tri]:
    """Separate flat roof. Print flat on bed, then Velcro/CA/screw to top rails."""
    tris: list[Tri] = []
    # local coordinates so panels load centered-ish in slicer
    length = x1 - x0
    lx0, lx1 = 0.0, length
    # main flat panel
    tris += box(lx0, lx1, -Y_OUT + 4, Y_OUT - 4, 0, 3.0)
    # raised futuristic center spine and side rails on top side
    tris += triangular_prism_x(lx0 + 8, lx1 - 8, -18, 18, 3.0, 8.0)
    tris += box(lx0 + 10, lx1 - 10, -Y_OUT + 10, -Y_OUT + 14, 3.0, 6.2)
    tris += box(lx0 + 10, lx1 - 10, Y_OUT - 14, Y_OUT - 10, 3.0, 6.2)
    # fine top grooves/ribs for a finished look
    for yy in [-30, -24, 24, 30]:
        tris += box(lx0 + 18, lx1 - 18, yy - 0.8, yy + 0.8, 6.2, 7.4)
    # small rear lip on rear panel for cable shroud impression
    if "rear" in name:
        tris += box(lx1 - 10, lx1, -Y_OUT + 6, Y_OUT - 6, 3.0, 13.0)
    return tris


def seam_bridge_pair() -> list[Tri]:
    tris: list[Tri] = []
    for y in (-32, 32):
        for cx in (-9, 9):
            tris += annular_cylinder(cx, y, 0, 4.0, 10.5, M3_CLEARANCE_D)
        tris += box(-9, 9, y - 5.0, y - 2.2, 0, 4.0)
        tris += box(-9, 9, y + 2.2, y + 5.0, 0, 4.0)
        tris += triangular_prism_x(-7, 7, y - 1.8, y + 1.8, 4.0, 7.2)
    return tris


def heatset_coupon() -> list[Tri]:
    tris: list[Tri] = []
    centers = [(-24, 0, 4.1), (0, 0, 4.2), (24, 0, 4.3)]
    tris += box(-36, 36, -10, -6.5, 0, 2.4)
    tris += box(-36, 36, 6.5, 10, 0, 2.4)
    for cx, cy, hole in centers:
        tris += annular_cylinder(cx, cy, 0, INSERT_DEPTH, 12.0, hole)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v4 support-light modular canopy",
        "",
        "This replaces v3's one-piece roofed canopy, which needed heavy supports in Bambu Studio.",
        "The shell is now a modular kit: two tall side/body halves plus two flat roof panels that print separately without large support structures.",
        "After assembly, Pip still gets a closed-looking roof over the turret with ~100 mm clearance and an open front face.",
        "",
        "## Why this is faster",
        "",
        "- The front/rear bodies have no large horizontal roof span, so they should print with supports disabled or minimal tree support only for slicer edge cases.",
        "- Roof panels print flat on the bed as shallow plates.",
        "- PETG clear should have much lower risk than the 14-hour supported v3 front half.",
        "",
        "## Assembly",
        "",
        "- Attach body halves to Pip with adhesive Velcro on the inner side landings.",
        "- Attach roof panels to the top ledges with thin Velcro, VHB tape, or small dots of CA after fit is confirmed.",
        "- Use seam bridge pair with M3 screws/heat-set inserts only after insert coupon fit is confirmed.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v4_front_body_supportless.stl` as the fit test.",
        "2. `pip_shell_v4_front_roof_flat.stl` to check roof clearance/fit.",
        "3. `pip_shell_v4_rear_body_supportless.stl`.",
        "4. `pip_shell_v4_rear_roof_flat.stl`.",
        "5. `pip_shell_v4_seam_bridge_pair.stl` if using inserts.",
        "",
        "## Suggested PETG clear settings",
        "",
        "- Supports: off first. If Bambu insists, use organic/tree only and paint/block supports away from vent grilles.",
        "- Brim: 5-8 mm on tall body halves.",
        "- 0.20 mm layer height, 3 walls, 12-18% gyroid/cubic infill.",
        "- Slower PETG profile preferred over speed mode.",
        "",
        "## Verified bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    lines += [
        "",
        "## Fit checks",
        "",
        "- Confirm front face stays open for camera/ultrasonic view.",
        "- Manually swing turret before powering motors.",
        "- Confirm roof panels do not press on sensor stack, camera ribbon, Pi headers, or USB/Ethernet cables.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v4_front_body_supportless.stl": front_body(),
        "pip_shell_v4_rear_body_supportless.stl": rear_body(),
        "pip_shell_v4_front_roof_flat.stl": roof_panel(0, 125, "front"),
        "pip_shell_v4_rear_roof_flat.stl": roof_panel(125, 250, "rear"),
        "pip_shell_v4_seam_bridge_pair.stl": seam_bridge_pair(),
        "pip_shell_v4_insert_coupon_4p1_4p2_4p3.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_v4_supportless_canopy/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v4_supportless_canopy/generate_pip_shell_v4_supportless_canopy_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
