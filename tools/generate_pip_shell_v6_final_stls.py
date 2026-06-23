#!/usr/bin/env python3
"""Generate Pip shell v6 final: support-safe U-shell with real grilles.

Final design direction:
- Main body prints WITHOUT an integrated roof: faster, easier, less support risk.
- Optional thin roof skins print separately flat and attach with Velcro/VHB after fit.
- Assembled shell length: 200 mm front-to-back.
- Shell body height: 80 mm from lower lip to optional roof plane.
- Front face is open for camera/ultrasonic/turret line of sight.
- Sides are mostly covered but use REAL vertical fine grille openings, not fake ribs.
- Grille openings are vertical slots between ribs, avoiding long horizontal PETG bridges.
- Two 100 mm halves fit Bambu A1 Mini comfortably.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v6_final"
ZIP = ROOT / "models" / "pip_shell_v6_final_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
LEN_TOTAL = 200.0
HALF_LEN = 100.0
WIDTH = 110.0
HALF_W = WIDTH / 2.0
HEIGHT = 80.0
WALL_T = 2.8
ROOF_SKIN_T = 2.4
M3_CLEARANCE_D = 3.4
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


def top_lip(x0: float, x1: float) -> list[Tri]:
    """Thin top ledges for optional roof skin, not a roof."""
    tris: list[Tri] = []
    tris += box(x0, x1, -HALF_W, -HALF_W + 8, HEIGHT - 4, HEIGHT)
    tris += box(x0, x1, HALF_W - 8, HALF_W, HEIGHT - 4, HEIGHT)
    # rear/front cross ledges at the seam only, not across turret/front face
    return tris


def vertical_grille_side(x0: float, x1: float, y_outer: float) -> list[Tri]:
    """Side panel made from real vertical ribs and open slots.

    Ribs run vertically, so there are no long horizontal bridges over open holes.
    Top/bottom rails are continuous; slots are open space between ribs.
    """
    tris: list[Tri] = []
    y0, y1 = (y_outer, y_outer + WALL_T) if y_outer < 0 else (y_outer - WALL_T, y_outer)
    # structural rails
    tris += box(x0, x1, y0, y1, 0, 9)
    tris += box(x0, x1, y0, y1, HEIGHT - 11, HEIGHT)
    tris += box(x0, x1, y0, y1, 36, 40)  # mid belt breaks long ribs and looks intentional
    # end posts
    tris += box(x0, x0 + 5, y0, y1, 0, HEIGHT)
    tris += box(x1 - 5, x1, y0, y1, 0, HEIGHT)
    # fine vertical grille ribs, actual spaces between them
    rib_w = 2.0
    pitch = 6.0
    x = x0 + 10
    while x + rib_w <= x1 - 10:
        tris += box(x, x + rib_w, y0, y1, 9, HEIGHT - 11)
        x += pitch
    # smooth outer belt over the grille for futuristic paneling
    yb0 = y0 - 1.4 if y_outer < 0 else y0
    yb1 = y1 if y_outer < 0 else y1 + 1.4
    tris += box(x0 + 8, x1 - 8, yb0, yb1, 58, 61)
    tris += box(x0 + 8, x1 - 8, yb0, yb1, 22, 25)
    # inner velcro landing strip near lower edge after installation
    inner0, inner1 = (y1, y1 + 4) if y_outer < 0 else (y0 - 4, y0)
    tris += box(x0 + 10, x1 - 10, min(inner0, inner1), max(inner0, inner1), 5, 11)
    return tris


def front_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = 0.0, HALF_LEN
    tris += vertical_grille_side(x0, x1, -HALF_W)
    tris += vertical_grille_side(x0, x1, HALF_W)
    tris += top_lip(x0, x1)
    # Open front face: side cheek posts and low lower tie only, center remains open.
    tris += box(x0, x0 + 5, -HALF_W, -38, 0, HEIGHT)
    tris += box(x0, x0 + 5, 38, HALF_W, 0, HEIGHT)
    tris += box(x0, x0 + 5, -HALF_W, HALF_W, 0, 10)
    # Seam structure at rear of front half
    tris += box(x1 - 5, x1, -HALF_W, -43, 0, HEIGHT)
    tris += box(x1 - 5, x1, 43, HALF_W, 0, HEIGHT)
    tris += box(x1 - 5, x1, -HALF_W, HALF_W, 0, 10)
    return tris


def rear_half() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = HALF_LEN, LEN_TOTAL
    tris += vertical_grille_side(x0, x1, -HALF_W)
    tris += vertical_grille_side(x0, x1, HALF_W)
    tris += top_lip(x0, x1)
    # Seam structure at front of rear half
    tris += box(x0, x0 + 5, -HALF_W, -43, 0, HEIGHT)
    tris += box(x0, x0 + 5, 43, HALF_W, 0, HEIGHT)
    tris += box(x0, x0 + 5, -HALF_W, HALF_W, 0, 10)
    # Rear mostly closed but with central cable window.
    tris += box(x1 - 5, x1, -HALF_W, HALF_W, 0, 12)
    tris += box(x1 - 5, x1, -HALF_W, HALF_W, HEIGHT - 15, HEIGHT)
    tris += box(x1 - 5, x1, -HALF_W, -34, 12, HEIGHT - 15)
    tris += box(x1 - 5, x1, 34, HALF_W, 12, HEIGHT - 15)
    # Rear vertical grille ribs around cable window
    for y in [-28, -20, -12, 12, 20, 28]:
        tris += box(x1 - 6.8, x1 - 5.0, y - 0.8, y + 0.8, 16, HEIGHT - 20)
    return tris


def roof_skin(name: str, x0: float, x1: float) -> list[Tri]:
    """Optional separate flat roof skin, prints flat and fast."""
    tris: list[Tri] = []
    tris += box(x0, x1, -47, 47, 0, ROOF_SKIN_T)
    # shallow raised center spine and two fine groove rails, all supported by the plate
    tris += box(x0 + 8, x1 - 8, -7, 7, ROOF_SKIN_T, ROOF_SKIN_T + 2.8)
    tris += box(x0 + 14, x1 - 14, -34, -32.2, ROOF_SKIN_T, ROOF_SKIN_T + 1.2)
    tris += box(x0 + 14, x1 - 14, 32.2, 34, ROOF_SKIN_T, ROOF_SKIN_T + 1.2)
    # small notches indicate front/rear orientation as visible grooves
    if name == "front":
        tris += box(x0 + 6, x0 + 18, -2, 2, ROOF_SKIN_T, ROOF_SKIN_T + 1.4)
    else:
        tris += box(x1 - 18, x1 - 6, -2, 2, ROOF_SKIN_T, ROOF_SKIN_T + 1.4)
    return tris


def seam_clip_pair() -> list[Tri]:
    tris: list[Tri] = []
    for y in (-31, 31):
        for cx in (-8, 8):
            tris += annular_cylinder(cx, y, 0, 3.2, outer_d=9.2, inner_d=M3_CLEARANCE_D)
        tris += box(-8, 8, y - 4.3, y - 2.2, 0, 3.2)
        tris += box(-8, 8, y + 2.2, y + 4.3, 0, 3.2)
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
        "# Pip shell v6 final, support-safe U-shell",
        "",
        "This is the finalized correction after v4/v5 printability issues.",
        "The main shell body has NO integrated roof, so it prints faster and avoids roof-cavity supports.",
        "Optional roof skins are separate flat plates that can be printed later and attached with Velcro/VHB after fit is proven.",
        "",
        "## Dimensions",
        "",
        "- Assembled main body length: 200 mm.",
        "- Body height: 80 mm from lower lip to top ledge.",
        "- Width: about 114 mm including small outer grille/belt details.",
        "- Front face: open center for turret/camera/ultrasonic view.",
        "",
        "## Printability choices",
        "",
        "- Real grille openings are vertical slots between ribs, not horizontal through-slots.",
        "- Vertical ribs avoid long PETG bridge spans and should join cleanly.",
        "- Top is open on the main body; roof prints as optional separate flat skins.",
        "- Body halves are only 100 mm long each for A1 Mini reliability.",
        "",
        "## PETG clear settings",
        "",
        "- Supports: off for main body halves. If Bambu adds supports, use support blockers.",
        "- Brim: 5-8 mm on body halves.",
        "- Layer height: 0.20 mm.",
        "- Walls: 3.",
        "- Infill: 10-15% gyroid/cubic.",
        "- Speed: normal/slow PETG, not sport/ludicrous.",
        "- Dry filament if grilles string or bubble.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v6_front_u_body_real_grilles.stl` as fit/print test.",
        "2. `pip_shell_v6_rear_u_body_real_grilles.stl`.",
        "3. Optional: `pip_shell_v6_front_roof_skin_flat.stl` and `pip_shell_v6_rear_roof_skin_flat.stl`.",
        "4. Optional: seam clips and insert coupon.",
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
        "pip_shell_v6_front_u_body_real_grilles.stl": front_half(),
        "pip_shell_v6_rear_u_body_real_grilles.stl": rear_half(),
        "pip_shell_v6_front_roof_skin_flat.stl": roof_skin("front", 0, HALF_LEN),
        "pip_shell_v6_rear_roof_skin_flat.stl": roof_skin("rear", HALF_LEN, LEN_TOTAL),
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
            zf.write(path, arcname=f"pip_shell_v6_final/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v6_final/generate_pip_shell_v6_final_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
