#!/usr/bin/env python3
"""Generate Pip shell v6: open-top PETG-friendly cowl.

Finalized after user feedback:
- No roof. Open top makes it faster/easier and avoids roof supports.
- 200 mm assembled length front-to-back.
- 80 mm shell height.
- Mostly closed, smooth futuristic side walls.
- Front face open/U-shaped for camera/ultrasonic/turret view.
- Only a small lower vent/RGB glow strip near chassis attachment, not full-wall grilles.
- PETG-friendly vertical-wall printing, supports off/minimal.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v6_open_top"
ZIP = ROOT / "models" / "pip_shell_v6_open_top_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
L_TOTAL = 200.0
L_HALF = 100.0
WIDTH = 110.0
HALF_W = WIDTH / 2.0
HEIGHT = 80.0
WALL_T = 2.8
M3_CLEARANCE_D = 3.4
INSERT_PILOT_D = 4.2
INSERT_PILOTS = [4.1, 4.2, 4.3]


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


def lower_vent_band(x0: float, x1: float, y_outer: float) -> list[Tri]:
    """Small real vent/light strip low on the side. Limited and print-friendly."""
    tris: list[Tri] = []
    y0, y1 = (y_outer, y_outer + WALL_T) if y_outer < 0 else (y_outer - WALL_T, y_outer)
    # bottom/top rails of only the lower vent strip
    z_bottom, z_top = 11.0, 28.0
    tris += box(x0, x1, y0, y1, 0, 8.0)
    tris += box(x0, x1, y0, y1, z_top, z_top + 4.0)
    # vertical posts create narrow slots. Slot tops bridge only ~3.5 mm, PETG-safe.
    post_w = 2.2
    pitch = 7.0
    x = x0
    while x < x1:
        tris += box(x, min(x + post_w, x1), y0, y1, z_bottom, z_top)
        x += pitch
    # end caps
    tris += box(x0, x0 + 3.0, y0, y1, 0, z_top + 4.0)
    tris += box(x1 - 3.0, x1, y0, y1, 0, z_top + 4.0)
    return tris


def smooth_upper_wall(x0: float, x1: float, y_outer: float) -> list[Tri]:
    tris: list[Tri] = []
    y0, y1 = (y_outer, y_outer + WALL_T) if y_outer < 0 else (y_outer - WALL_T, y_outer)
    # Mostly closed upper side, no grilles here.
    tris += box(x0, x1, y0, y1, 32.0, HEIGHT)
    # top rim and mid crease for finished look
    tris += box(x0, x1, y0, y1, HEIGHT - 4.0, HEIGHT)
    tris += box(x0 + 5, x1 - 5, y0, y1, 52.0, 55.0)
    # outside shallow armor strip, attached to wall
    offset = -1.6 if y_outer < 0 else 1.6
    yo0 = min(y0 + offset, y1 + offset)
    yo1 = max(y0 + offset, y1 + offset)
    tris += box(x0 + 12, x1 - 12, yo0, yo1, 42.0, 46.0)
    return tris


def side_wall(x0: float, x1: float, y_outer: float) -> list[Tri]:
    # lower vent is only a narrow bottom strip, upper wall smooth/closed
    return lower_vent_band(x0 + 12, x1 - 12, y_outer) + smooth_upper_wall(x0, x1, y_outer)


def roof_insert_hardpoints(x_positions: list[float]) -> list[Tri]:
    """M3 heat-set insert bosses on the top side walls for a future roof panel.

    Important: do not put a solid shelf under the pilot hole. The first roof
    hardpoint revision used a rectangular pad plus an annular boss, which made
    slicers display the insert holes as filled circular marks. These bosses are
    true annular cylinders tied into the side wall by small outside ribs that do
    not cover the 4.2 mm center pilot.
    """
    tris: list[Tri] = []
    for x in x_positions:
        for y in (-47.5, 47.5):
            # True vertical pilot hole for the M3 x 4.6 x 5.7 insert.
            tris += annular_cylinder(x, y, HEIGHT - 8.0, HEIGHT, outer_d=13.0, inner_d=INSERT_PILOT_D)
            # Tie ribs connect the boss to the outer wall/rim without crossing the hole.
            if y < 0:
                tris += box(x - 7.0, x + 7.0, -55.0, -53.0, HEIGHT - 8.0, HEIGHT)
                tris += box(x - 7.0, x - 4.0, -53.0, -47.5, HEIGHT - 8.0, HEIGHT)
                tris += box(x + 4.0, x + 7.0, -53.0, -47.5, HEIGHT - 8.0, HEIGHT)
            else:
                tris += box(x - 7.0, x + 7.0, 53.0, 55.0, HEIGHT - 8.0, HEIGHT)
                tris += box(x - 7.0, x - 4.0, 47.5, 53.0, HEIGHT - 8.0, HEIGHT)
                tris += box(x + 4.0, x + 7.0, 47.5, 53.0, HEIGHT - 8.0, HEIGHT)
    return tris


def front_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = 0.0, L_HALF
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    tris += roof_insert_hardpoints([22.0, 78.0])
    # front face open/U-shaped: corner cheeks only, center empty
    tris += box(x0, x0 + 4.0, -HALF_W, -41.0, 0, HEIGHT)
    tris += box(x0, x0 + 4.0, 41.0, HALF_W, 0, HEIGHT)
    # low front bumper/rim, not blocking sensors
    tris += box(x0, x0 + 4.0, -HALF_W, HALF_W, 0, 10.0)
    # seam face at rear of front half
    tris += box(x1 - 4.0, x1, -HALF_W, -43.0, 0, HEIGHT)
    tris += box(x1 - 4.0, x1, 43.0, HALF_W, 0, HEIGHT)
    tris += box(x1 - 4.0, x1, -HALF_W, HALF_W, 0, 9.0)
    # inside velcro landings, low and flat
    tris += box(x0 + 18, x1 - 12, -48.0, -44.0, 8.0, 13.0)
    tris += box(x0 + 18, x1 - 12, 44.0, 48.0, 8.0, 13.0)
    return tris


def rear_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = L_HALF, L_TOTAL
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    tris += roof_insert_hardpoints([122.0, 178.0])
    # rear mostly closed but with a broad lower cable relief notch
    tris += box(x1 - 4.0, x1, -HALF_W, HALF_W, 32.0, HEIGHT)
    tris += box(x1 - 4.0, x1, -HALF_W, -38.0, 0, 32.0)
    tris += box(x1 - 4.0, x1, 38.0, HALF_W, 0, 32.0)
    tris += box(x1 - 4.0, x1, -HALF_W, HALF_W, 0, 8.0)
    # seam face at front of rear half
    tris += box(x0, x0 + 4.0, -HALF_W, -43.0, 0, HEIGHT)
    tris += box(x0, x0 + 4.0, 43.0, HALF_W, 0, HEIGHT)
    tris += box(x0, x0 + 4.0, -HALF_W, HALF_W, 0, 9.0)
    # small rear lower light/vent detail only
    for y in [-28, -20, -12, 12, 20, 28]:
        tris += box(x1 - 5.8, x1 - 4.2, y - 0.7, y + 0.7, 12.0, 28.0)
    # inside velcro landings
    tris += box(x0 + 12, x1 - 18, -48.0, -44.0, 8.0, 13.0)
    tris += box(x0 + 12, x1 - 18, 44.0, 48.0, 8.0, 13.0)
    return tris


def seam_clip_pair() -> list[Tri]:
    tris: list[Tri] = []
    # Optional flat clips. Can also just use thin VHB/Velcro across seam.
    for y in (-31, 31):
        for cx in (-8, 8):
            tris += annular_cylinder(cx, y, 0, 3.2, outer_d=9.2, inner_d=M3_CLEARANCE_D)
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
        "# Pip shell v6 open-top PETG cowl",
        "",
        "Finalized after print feedback: no roof, smoother sides, and only a small lower RGB/vent strip.",
        "This is intended to print upright with supports off or minimal, in clear PETG on a Bambu A1 Mini.",
        "",
        "## Dimensions",
        "",
        "- Assembled length: 200 mm front-to-back.",
        "- Width: about 110-114 mm including small exterior details.",
        "- Height: 80 mm from bottom to top rim.",
        "- Open top and open front face for turret/camera/ultrasonic clearance.",
        "- Top side walls include M3 heat-set insert hardpoints for a future bolt-on roof.",
        "",
        "## Design changes from failed v4/v5 attempts",
        "",
        "- Removed roof entirely to reduce time/supports.",
        "- Removed full-wall grilles.",
        "- Added only one small lower side vent/RGB glow strip per side.",
        "- Lower slots are narrow, vertical, and limited to a short band so PETG bridges are tiny.",
        "- Upper shell is mostly smooth closed wall with a top rim and subtle armor crease.",
        "- Rear is mostly closed with a lower cable-relief opening.",
        "",
        "## Suggested PETG clear settings",
        "",
        "- Supports: off first. If Bambu insists, use organic/tree only and block supports inside side vents.",
        "- Brim: 5-8 mm on both body halves.",
        "- Layer height: 0.20 mm.",
        "- Walls: 3.",
        "- Infill: 10-15% gyroid/cubic.",
        "- Slow/default PETG profile, not sport/ludicrous.",
        "- Bed: 75-80 C, with release agent if PETG sticks too hard to PEI.",
        "- Dry filament if clear PETG strings/bubbles badly.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v6_front_open_top_body.stl` as the fit/clearance test.",
        "2. `pip_shell_v6_rear_open_top_body.stl`.",
        "3. Optional: `pip_shell_v6_seam_clip_pair.stl`.",
        "4. Optional: `pip_shell_v6_insert_coupon_4p1_4p2_4p3.stl`.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    lines += [
        "",
        "## Fit checks",
        "",
        "- Test front half on Pip before printing rear half.",
        "- Manually swing turret/camera/ultrasonic through full travel with power off.",
        "- Confirm wheels do not rub and Velcro pads sit on flat chassis areas.",
        "- Confirm RGB shines through the lower vent strip without the strip touching wheels.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v6_front_open_top_body.stl": front_half(),
        "pip_shell_v6_rear_open_top_body.stl": rear_half(),
        "pip_shell_v6_seam_clip_pair.stl": seam_clip_pair(),
        "pip_shell_v6_insert_coupon_4p1_4p2_4p3.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_v6_open_top/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v6_open_top/generate_pip_shell_v6_open_top_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
