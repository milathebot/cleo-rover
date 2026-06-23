#!/usr/bin/env python3
"""Generate Pip shell v11: simplified PETG-safe U-cowl.

Redesign after real print fit/failure:
- Max shell width must be <= 100 mm because wheels begin immediately outside.
- Total shell length 200 mm, split into two 100 mm halves for Bambu A1 Mini.
- Open front face and open center: two side walls + rear wall only.
- No bottom crossbars across Pi/servo/electronics area.
- Height slopes front->rear: 100 mm at front, 130 mm at rear.
- Small lower side vent/RGB strip only, not full-wall grilles.
- Top insert hardpoints retained for future roof; holes are true open pilots.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v11_simple_u"
ZIP = ROOT / "models" / "pip_shell_v11_simple_u_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
L_TOTAL = 200.0
L_HALF = 100.0
W_OUTER = 98.0
HALF_W = W_OUTER / 2.0
WALL_T = 3.0
Z_FRONT = 100.0
Z_REAR = 130.0
INSERT_PILOT_D = 4.2
M3_CLEARANCE_D = 3.6


def height_at(x: float) -> float:
    return Z_FRONT + (Z_REAR - Z_FRONT) * (x / L_TOTAL)


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return []
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


def prism_xz(points: list[tuple[float, float]], y0: float, y1: float) -> list[Tri]:
    """Extrude a 2D x/z polygon along Y."""
    tris: list[Tri] = []
    n = len(points)
    # front/back faces, fan triangulation. Points should be convex-ish/order around perimeter.
    for i in range(1, n - 1):
        a = (points[0][0], y0, points[0][1]); b = (points[i][0], y0, points[i][1]); c = (points[i+1][0], y0, points[i+1][1])
        tris.append((a, b, c))
        a1 = (points[0][0], y1, points[0][1]); b1 = (points[i+1][0], y1, points[i+1][1]); c1 = (points[i][0], y1, points[i][1])
        tris.append((a1, b1, c1))
    for i in range(n):
        j = (i + 1) % n
        p0 = points[i]; p1 = points[j]
        a = (p0[0], y0, p0[1]); b = (p1[0], y0, p1[1]); c = (p1[0], y1, p1[1]); d = (p0[0], y1, p0[1])
        tris += [(a, b, c), (a, c, d)]
    return tris


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 64) -> list[Tri]:
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


def side_wall(x0: float, x1: float, y_outer: float) -> list[Tri]:
    """PETG-safe side wall with small lower vent strip and sloped top."""
    y0, y1 = (y_outer, y_outer + WALL_T) if y_outer < 0 else (y_outer - WALL_T, y_outer)
    tris: list[Tri] = []
    z0 = height_at(x0)
    z1 = height_at(x1)
    # Smooth upper wall as one sloped trapezoid, starting above grille band.
    tris += prism_xz([(x0, 36.0), (x1, 36.0), (x1, z1), (x0, z0)], y0, y1)
    # Bottom rail and vent-strip top/bottom rails.
    tris += box(x0, x1, y0, y1, 0, 10)
    tris += box(x0, x1, y0, y1, 31, 36)
    # Small lower RGB/vent strip: vertical posts leave real rectangular holes, no long bridges.
    slot_start = x0 + 14
    slot_end = x1 - 14
    slot_count = 6 if (x1 - x0) >= 90 else 5
    gap = (slot_end - slot_start) / slot_count
    post_w = 3.2
    # end posts
    tris += box(x0, x0 + 7, y0, y1, 10, 31)
    tris += box(x1 - 7, x1, y0, y1, 10, 31)
    for i in range(slot_count + 1):
        x = slot_start + i * gap
        tris += box(x - post_w / 2, x + post_w / 2, y0, y1, 10, 31)
    # Top rim for strength and a clean slope line.
    tris += prism_xz([(x0, z0 - 5), (x1, z1 - 5), (x1, z1), (x0, z0)], y0, y1)
    return tris


def roof_hardpoints(x_values: list[float]) -> list[Tri]:
    """Insert bosses for a future roof. True open vertical pilot holes."""
    tris: list[Tri] = []
    for x in x_values:
        z = height_at(x)
        for y in (-41.5, 41.5):
            tris += annular_cylinder(x, y, z - 1.0, z + 7.0, outer_d=12.0, inner_d=INSERT_PILOT_D)
            # tiny wall ribs that do not cover the center hole
            tris += box(x - 7.0, x + 7.0, y - 7.4, y - 5.7, z - 1.0, z + 3.5)
            tris += box(x - 7.0, x + 7.0, y + 5.7, y + 7.4, z - 1.0, z + 3.5)
    return tris


def seam_side_pads(x: float, direction: str) -> list[Tri]:
    """Short side-only seam pads. No center/bottom crossbar. Kept inside each half's 100 mm length."""
    tris: list[Tri] = []
    if direction == "front_inside":
        xa, xb = x - 4.0, x
    elif direction == "rear_inside":
        xa, xb = x, x + 4.0
    else:
        raise ValueError(direction)
    for y_outer in (-HALF_W, HALF_W):
        y0, y1 = (y_outer, y_outer + WALL_T + 2.0) if y_outer < 0 else (y_outer - WALL_T - 2.0, y_outer)
        tris += box(xa, xb, min(y0, y1), max(y0, y1), 42, height_at(x) - 5)
    return tris


def front_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = 0.0, L_HALF
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    tris += roof_hardpoints([22.0, 78.0])
    tris += seam_side_pads(x1, "front_inside")
    # Very small front corner cheeks only. Center/front face remains open.
    for y_outer in (-HALF_W, HALF_W):
        y0, y1 = (y_outer, y_outer + WALL_T + 2.0) if y_outer < 0 else (y_outer - WALL_T - 2.0, y_outer)
        tris += box(0, 4.0, min(y0, y1), max(y0, y1), 0, height_at(0) - 8)
    return tris


def rear_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = L_HALF, L_TOTAL
    tris += side_wall(x0, x1, -HALF_W)
    tris += side_wall(x0, x1, HALF_W)
    tris += roof_hardpoints([122.0, 178.0])
    tris += seam_side_pads(x0, "rear_inside")
    # Rear wall: mostly closed, but only at the rear; lower center cable relief.
    back_x0, back_x1 = x1 - 3.0, x1
    tris += box(back_x0, back_x1, -HALF_W, HALF_W, 40, height_at(x1))
    tris += box(back_x0, back_x1, -HALF_W, -34.0, 0, 40)
    tris += box(back_x0, back_x1, 34.0, HALF_W, 0, 40)
    # rear lower side vents for RGB/cooling, again no center/bottom bar across internals
    for y0, y1 in [(-HALF_W, -HALF_W + WALL_T), (HALF_W - WALL_T, HALF_W)]:
        for z in [16, 24, 32]:
            # small horizontal rear detail strips on side edges, attached to wall
            tris += box(back_x0 - 0.2, back_x1, y0, y1, z, z + 1.2)
    return tris


def seam_clip_pair() -> list[Tri]:
    tris: list[Tri] = []
    for y in (-41.5, 41.5):
        for cx in (-8, 8):
            tris += annular_cylinder(cx, y, 0, 3.2, outer_d=9.0, inner_d=M3_CLEARANCE_D)
        tris += box(-8, 8, y - 4.3, y - 2.3, 0, 3.2)
        tris += box(-8, 8, y + 2.3, y + 4.3, 0, 3.2)
    return tris


def heatset_coupon() -> list[Tri]:
    tris: list[Tri] = []
    tris += box(-36, 36, -10, -6.5, 0, 2.4)
    tris += box(-36, 36, 6.5, 10, 0, 2.4)
    for cx, hole in [(-24, 4.1), (0, 4.2), (24, 4.3)]:
        tris += annular_cylinder(cx, 0, 0, 6.4, outer_d=12.0, inner_d=hole)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v11 simple U-cowl",
        "",
        "Hard simplification after the real PETG shell print was too wide and fragile.",
        "This version prioritizes fit and successful printing over styling complexity.",
        "",
        "## Geometry",
        "",
        "- Max outer width: 98 mm, below the 100 mm hard limit before the wheels.",
        "- Total length: 200 mm, split into 100 mm front and rear halves.",
        "- Height slopes from 100 mm at the front to 130 mm at the rear.",
        "- True U shape: left wall, right wall, rear wall only. Front and center are open.",
        "- No bottom crossbars across the Pi/servo/electronics area.",
        "- Small lower side RGB/vent strip only, with robust vertical posts.",
        "- Top hardpoints use true 4.2 mm heat-set insert pilot holes for a future roof.",
        "",
        "## Print settings for clear PETG",
        "",
        "- Supports: OFF first. This design should not need the support forest that broke v6.",
        "- Brim: 5-8 mm.",
        "- Layer height: 0.20 mm.",
        "- Walls: 3.",
        "- Infill: 10-15% gyroid/cubic.",
        "- Slow/default PETG profile, not sport/ludicrous.",
        "- Dry filament if you see bubbling, clouding, or heavy strings.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v11_front_simple_u_half.stl` as the fit test.",
        "2. `pip_shell_v11_rear_simple_u_half.stl` if front width/clearance are good.",
        "3. Optional: `pip_shell_v11_seam_clip_pair.stl`.",
        "4. Optional: insert coupon if you still need pilot confirmation.",
        "",
        "## Verified bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    lines += [
        "",
        "## Fit checklist",
        "",
        "- Confirm outer width clears wheels before printing rear half.",
        "- Confirm front sensor/turret/camera face is unobstructed.",
        "- Confirm lower vent strip is above wheel rub line.",
        "- Confirm no shell wall presses on Pi, GPIO, camera ribbon, or servo wires.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v11_front_simple_u_half.stl": front_half(),
        "pip_shell_v11_rear_simple_u_half.stl": rear_half(),
        "pip_shell_v11_seam_clip_pair.stl": seam_clip_pair(),
        "pip_shell_v11_insert_coupon_4p1_4p2_4p3.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_v11_simple_u/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v11_simple_u/generate_pip_shell_v11_simple_u_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
