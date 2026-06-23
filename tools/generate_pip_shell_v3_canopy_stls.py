#!/usr/bin/env python3
"""Generate Pip shell v3: closed canopy with open front face.

Design intent from fit photos/user notes:
- Freenove/Pip rover approximate chassis envelope from previous work: ~200 L x 100 W.
- Front face must be open for ultrasonic/camera/turret visibility, but a roof over
  the turret section is OK if it gives about 100 mm internal clearance.
- Shell should feel like a finished futuristic canopy, not random ladder holes.
- Fine horizontal side vent grilles for smooth look/RGB glow/airflow.
- Rear extends ~50 mm past the Pi/port area as a cable shroud, not a fully open back.
- Velcro-first attachment. Heat-set inserts only for removable seam/top service
  bridges and future hardpoints.

Units: mm. Generated parts fit Bambu A1 Mini 180 x 180 x 180.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v3_canopy"
ZIP = ROOT / "models" / "pip_shell_v3_canopy_bambu_a1_mini.zip"
BUILD_VOLUME = (180.0, 180.0, 180.0)

# PETG clear, NICECRAFT M3 x 4.6 x 5.7 mm insert from user screenshot.
# 4.2 remains conservative for PETG until the user confirms the v2 coupon result.
INSERT_PILOT_D = 4.2
INSERT_DEPTH = 6.4
M3_CLEARANCE_D = 3.4

# Coordinate system: x=front to rear. Full shell spans 0..250 mm.
# Rover body is about 0..200; rear cable shroud extends to 250.
WIDTH = 108.0
Y_OUT = WIDTH / 2
WALL = 2.8
ROOF_Z = 100.0          # about 10 cm turret internal clearance
TOP_Z = 108.0           # exterior armor/spine height
LOWER_Z = 8.0           # above low chassis/wheel clutter


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


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 64) -> list[Tri]:
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


def side_wall_with_fine_grille(x0: float, x1: float, y_outer: float) -> list[Tri]:
    """Mostly closed side wall, but visually smooth fine vent grilles."""
    tris: list[Tri] = []
    if y_outer < 0:
        y0, y1 = y_outer, y_outer + WALL
        accent_y0, accent_y1 = y_outer - 1.2, y_outer
    else:
        y0, y1 = y_outer - WALL, y_outer
        accent_y0, accent_y1 = y_outer, y_outer + 1.2

    # Solid front/rear posts and top/bottom belts make it a proper finished shell.
    tris += box(x0, x1, y0, y1, LOWER_Z, LOWER_Z + 6)
    tris += box(x0, x1, y0, y1, ROOF_Z - 8, ROOF_Z)
    for px in [x0, x0 + 36, x0 + 72, x1 - 5]:
        if px + 5 <= x1:
            tris += box(px, px + 5, y0, y1, LOWER_Z, ROOF_Z)

    # Fine grille: many thin slats in a recessed-looking side panel.
    # Leaving gaps between slats creates real vents without big random holes.
    vent_x0 = x0 + 8
    vent_x1 = x1 - 8
    for z in [24, 31, 38, 45, 52, 59, 66, 73, 80]:
        tris += box(vent_x0, vent_x1, y0, y1, z, z + 1.8)

    # Smooth outer accent rails make the side look deliberate/futuristic.
    tris += box(x0 + 10, x1 - 10, accent_y0, accent_y1, 88, 91)
    tris += box(x0 + 16, x1 - 16, accent_y0, accent_y1, 18, 20)
    tris += box(x0 + 20, x0 + 48, accent_y0, accent_y1, 82, 88)
    if x1 - x0 > 92:
        tris += box(x1 - 52, x1 - 24, accent_y0, accent_y1, 82, 88)
    return tris


def roof_canopy(x0: float, x1: float) -> list[Tri]:
    tris: list[Tri] = []
    # Main roof panel, intentionally closed over turret with ~100 mm clearance.
    tris += box(x0, x1, -Y_OUT + 4, Y_OUT - 4, ROOF_Z, ROOF_Z + 3.0)
    # Rounded-ish layered roof rails/spine via prisms and low steps.
    tris += triangular_prism_x(x0 + 8, x1 - 8, -18, 18, ROOF_Z + 3, TOP_Z)
    tris += box(x0 + 10, x1 - 10, -Y_OUT + 10, -Y_OUT + 14, ROOF_Z + 3, ROOF_Z + 7)
    tris += box(x0 + 10, x1 - 10, Y_OUT - 14, Y_OUT - 10, ROOF_Z + 3, ROOF_Z + 7)
    # Under-roof rails to fight PETG wobble on tall print.
    tris += box(x0 + 8, x1 - 8, -Y_OUT + 16, -Y_OUT + 20, ROOF_Z - 5, ROOF_Z)
    tris += box(x0 + 8, x1 - 8, Y_OUT - 20, Y_OUT - 16, ROOF_Z - 5, ROOF_Z)
    return tris


def front_face_open_frame() -> list[Tri]:
    """U-front: side pillars + top brow, no center/front face obstruction."""
    tris: list[Tri] = []
    # Front side pillars/frame, set wide so camera/ultrasonic can see forward.
    tris += box(0, 4, -Y_OUT, -34, LOWER_Z, ROOF_Z)
    tris += box(0, 4, 34, Y_OUT, LOWER_Z, ROOF_Z)
    # Roof brow only, open below.
    tris += box(0, 5, -Y_OUT, Y_OUT, ROOF_Z - 9, ROOF_Z + 3)
    # Chin rails are only side stubs, not a front blocker.
    tris += box(0, 8, -Y_OUT, -37, LOWER_Z, LOWER_Z + 7)
    tris += box(0, 8, 37, Y_OUT, LOWER_Z, LOWER_Z + 7)
    return tris


def rear_cable_shroud() -> list[Tri]:
    """Closed-looking rear extension with controlled cable exits."""
    tris: list[Tri] = []
    # Rear wall mostly closed, but with bottom/side cable relief channels.
    tris += box(247, 250, -Y_OUT, Y_OUT, LOWER_Z, 30)
    tris += box(247, 250, -Y_OUT, -22, 30, ROOF_Z)
    tris += box(247, 250, 22, Y_OUT, 30, ROOF_Z)
    tris += box(247, 250, -Y_OUT, Y_OUT, ROOF_Z - 10, ROOF_Z + 3)
    # Rear roof overhang and lower cable hood sides.
    tris += box(205, 250, -Y_OUT + 6, Y_OUT - 6, ROOF_Z, ROOF_Z + 3)
    # Cable tunnel top ribs under rear shroud.
    tris += box(215, 248, -20, -16, 30, 46)
    tris += box(215, 248, 16, 20, 30, 46)
    return tris


def insert_boss(cx: float, cy: float, z0: float = ROOF_Z + 3.0) -> list[Tri]:
    tris = annular_cylinder(cx, cy, z0, z0 + INSERT_DEPTH, outer_d=12.0, inner_d=INSERT_PILOT_D)
    tris += box(cx - 7, cx + 7, cy - 7, cy + 7, z0 - 2.2, z0)
    return tris


def seam_bosses(x_values: list[float]) -> list[Tri]:
    tris: list[Tri] = []
    for x in x_values:
        for y in (-32, 32):
            tris += insert_boss(x, y)
    return tris


def velcro_landing(x0: float, x1: float) -> list[Tri]:
    tris: list[Tri] = []
    # Flat internal pads along side/top-board zones, kept above wheels.
    tris += box(x0, x1, -Y_OUT + 6, -Y_OUT + 11, LOWER_Z, LOWER_Z + 6)
    tris += box(x0, x1, Y_OUT - 11, Y_OUT - 6, LOWER_Z, LOWER_Z + 6)
    # Rear/center cross pad for another velcro strip if it clears Pi/cables.
    if x1 - x0 > 80:
        tris += box(x0 + 30, x1 - 30, -16, 16, LOWER_Z, LOWER_Z + 4)
    return tris


def front_canopy_half() -> list[Tri]:
    tris: list[Tri] = []
    # Printable part spans x=0..125. It has the open face and roof over turret.
    tris += side_wall_with_fine_grille(0, 125, -Y_OUT)
    tris += side_wall_with_fine_grille(0, 125, Y_OUT)
    tris += roof_canopy(0, 125)
    tris += front_face_open_frame()
    tris += seam_bosses([116])
    tris += velcro_landing(18, 116)
    # Seam tongue pads for alignment with rear part.
    tris += box(121, 125, -42, -34, 82, ROOF_Z - 4)
    tris += box(121, 125, 34, 42, 82, ROOF_Z - 4)
    return tris


def rear_canopy_half() -> list[Tri]:
    tris: list[Tri] = []
    # Printable part spans x=125..250, includes ~50 mm rear cable shroud.
    tris += side_wall_with_fine_grille(125, 250, -Y_OUT)
    tris += side_wall_with_fine_grille(125, 250, Y_OUT)
    tris += roof_canopy(125, 250)
    tris += rear_cable_shroud()
    tris += seam_bosses([134])
    # Optional rear/top accessory hardpoints for future antenna/handle, same insert spec.
    for x in (182, 224):
        for y in (-18, 18):
            tris += insert_boss(x, y)
    tris += velcro_landing(134, 232)
    # Seam receiver pads.
    tris += box(125, 130, -43, -34, 82, ROOF_Z - 4)
    tris += box(125, 130, 34, 43, 82, ROOF_Z - 4)
    return tris


def seam_bridge_pair() -> list[Tri]:
    tris: list[Tri] = []
    # Boss spacing across seam: 116 on front part and 134 on rear part -> 18 mm apart assembled.
    for y in (-32, 32):
        for cx in (-9, 9):
            tris += annular_cylinder(cx, y, 0, 4.2, outer_d=10.5, inner_d=M3_CLEARANCE_D)
        tris += box(-9, 9, y - 5.2, y - 2.4, 0, 4.2)
        tris += box(-9, 9, y + 2.4, y + 5.2, 0, 4.2)
        tris += triangular_prism_x(-7, 7, y - 1.8, y + 1.8, 4.2, 7.2)
    return tris


def heatset_coupon() -> list[Tri]:
    tris: list[Tri] = []
    centers = [(-24, 0, 4.1), (0, 0, 4.2), (24, 0, 4.3)]
    tris += box(-36, 36, -10, -6.5, 0, 2.4)
    tris += box(-36, 36, 6.5, 10, 0, 2.4)
    for cx, cy, hole in centers:
        tris += annular_cylinder(cx, cy, 0, INSERT_DEPTH, outer_d=12.0, inner_d=hole)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v3 canopy, Bambu A1 Mini",
        "",
        "Closed futuristic canopy shell for Pip/Cleo Rover with an open front face and ~100 mm turret clearance under the roof.",
        "This revision replaces the earlier open exoframe look with a smoother, more finished body: mostly closed side walls, fine vent grilles, roof spine, and rear cable shroud.",
        "",
        "## Shape notes",
        "",
        "- Overall assembled shell envelope: about 250 L x 108 W x 108 H mm.",
        "- Rover body coverage target: ~200 mm length plus ~50 mm rear cable shroud.",
        "- Front face is open in the middle for camera/ultrasonic/turret line-of-sight.",
        "- Roof is closed over the turret area with about 100 mm internal clearance.",
        "- Side walls use fine horizontal vent grilles, not random large holes.",
        "- Bottom remains open and Velcro-first. Do not screw into the rover chassis yet.",
        "",
        "## Insert spec used",
        "",
        "- NICECRAFT M3 x 4.6 x 5.7 mm brass heat-set insert.",
        f"- Modeled boss pilot: {INSERT_PILOT_D:.1f} mm, depth {INSERT_DEPTH:.1f} mm.",
        "- PETG clear note: test the coupon first. If 4.0 from the old v2 coupon fits best, regenerate with a smaller pilot before printing shell halves.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v3_insert_coupon_4p1_4p2_4p3.stl` if insert fit is still unconfirmed.",
        "2. `pip_shell_v3_front_open_canopy_half.stl`.",
        "3. `pip_shell_v3_rear_cable_canopy_half.stl`.",
        "4. `pip_shell_v3_seam_bridge_pair.stl`.",
        "",
        "## Suggested PETG clear settings",
        "",
        "- 0.20 mm layer height, 3 walls, 12-18% gyroid/cubic infill.",
        "- Brim recommended on both tall canopy halves.",
        "- Slower PETG profile preferred over high-speed mode for transparency and layer adhesion.",
        "- Supports should be off or organic-only if slicer insists; model is designed around vertical walls and short bridges.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    lines += [
        "",
        "## Fit checks before long print commitment",
        "",
        "- In Bambu Studio, verify the front central face is open and no panel blocks ultrasonic/camera view.",
        "- Check the first 20-30 minutes for PETG brim adhesion and wobble.",
        "- After print, place shell on rover without Velcro first and swing turret left/right manually before powering motors.",
        "- Confirm rear shroud covers cables without pressing on USB/Ethernet/power plugs.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v3_front_open_canopy_half.stl": front_canopy_half(),
        "pip_shell_v3_rear_cable_canopy_half.stl": rear_canopy_half(),
        "pip_shell_v3_seam_bridge_pair.stl": seam_bridge_pair(),
        "pip_shell_v3_insert_coupon_4p1_4p2_4p3.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_v3_canopy/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v3_canopy/generate_pip_shell_v3_canopy_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
