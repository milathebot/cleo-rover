#!/usr/bin/env python3
"""Generate Pip final-ish velcro shell STL set.

Units: millimetres. Designed for Bambu A1 Mini (180 x 180 x 180 mm).
Target assembled rover shell envelope from prior prototype work: about 200 L x
100 W x 140 H, split into two printable halves. Front camera/ultrasonic/turret
sweep stays open. No display mount in this revision.

Heat-set inserts from user screenshot: M3 x 4.6 x 5.7 mm NICECRAFT knurled brass.
Bosses use 4.2 mm nominal pilot holes and >= 6.4 mm usable depth, with a coupon
for 4.1/4.2/4.3 mm pilots.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_final"
ZIP = ROOT / "models" / "pip_shell_final_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
INSERT_SPEC = "NICECRAFT M3 x 4.6 x 5.7 mm knurled brass heat-set insert"
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
    """Long low triangular armor ridge along X."""
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


def side_exo_panel(x0: float, x1: float, y_outer: float) -> list[Tri]:
    """Futuristic open side exoskeleton with vents and glow slots."""
    t = 2.8
    y0, y1 = (y_outer, y_outer + t) if y_outer < 0 else (y_outer - t, y_outer)
    tris: list[Tri] = []
    # Skeleton posts
    for xa, xb in [(x0, x0+5), (x0+28, x0+33), (x1-33, x1-28), (x1-5, x1)]:
        if xb > x0 and xa < x1:
            tris += box(max(x0, xa), min(x1, xb), y0, y1, 0, 130)
    # Top/bottom rails
    tris += box(x0, x1, y0, y1, 0, 7)
    tris += box(x0, x1, y0, y1, 112, 130)
    tris += box(x0+7, x1-7, y0, y1, 94, 100)
    # RGB/air vent slats
    for z in [18, 30, 42, 54, 66, 78]:
        tris += box(x0 + 5, x1 - 5, y0, y1, z, z + 3.2)
    # External angled-looking cyber armor bars (stepped, print friendly)
    for i, x in enumerate([x0 + 12, x0 + 46, x0 + 80]):
        if x + 16 <= x1:
            tris += box(x, x + 16, y0 - (1.8 if y_outer < 0 else 0), y1 + (1.8 if y_outer > 0 else 0), 82 - i*8, 86 - i*8)
            tris += box(x + 10, x + 16, y0 - (1.8 if y_outer < 0 else 0), y1 + (1.8 if y_outer > 0 else 0), 70 - i*8, 86 - i*8)
    return tris


def roof_base(x0: float, x1: float, y0: float = -48, y1: float = 48) -> list[Tri]:
    tris = box(x0, x1, y0, y1, 130, 133)
    # Under-roof rails
    tris += box(x0 + 6, x1 - 6, -39, -35, 125, 130)
    tris += box(x0 + 6, x1 - 6, 35, 39, 125, 130)
    # Futuristic raised center spine and side shoulders
    tris += triangular_prism_x(x0 + 8, x1 - 8, -12, 12, 133, 142)
    tris += box(x0 + 12, x1 - 12, -42, -38, 133, 137)
    tris += box(x0 + 12, x1 - 12, 38, 42, 133, 137)
    return tris


def insert_boss(cx: float, cy: float, z0: float = 133.0) -> list[Tri]:
    """Top boss for M3 x 4.6 x 5.7 insert. Pilot is through in mesh for slicer clarity."""
    tris = annular_cylinder(cx, cy, z0, z0 + INSERT_DEPTH, outer_d=12.0, inner_d=INSERT_PILOT_D)
    # small anti-twist square pad
    tris += box(cx - 7, cx + 7, cy - 7, cy + 7, z0 - 2.2, z0)
    return tris


def seam_insert_bosses(x_values: list[float]) -> list[Tri]:
    tris: list[Tri] = []
    for x in x_values:
        for y in (-31, 31):
            tris += insert_boss(x, y)
    return tris


def accessory_hardpoints(x_values: list[float]) -> list[Tri]:
    """Optional future hardpoints for antennas/top shells, not for chassis mounting."""
    tris: list[Tri] = []
    for x in x_values:
        for y in (-18, 18):
            tris += insert_boss(x, y, z0=133)
    return tris


def velcro_landing(x0: float, x1: float) -> list[Tri]:
    """Raised inner strips to give adhesive Velcro a flat landing without blocking sides."""
    tris: list[Tri] = []
    tris += box(x0, x1, -46.8, -42.6, 9, 15)
    tris += box(x0, x1, 42.6, 46.8, 9, 15)
    # small bottom cross ribs for peel resistance
    tris += box((x0+x1)/2 - 4, (x0+x1)/2 + 4, -42.6, 42.6, 8, 12)
    return tris


def rear_shell() -> list[Tri]:
    tris: list[Tri] = []
    # rear module x 0..100, open bottom, open cable rear
    tris += side_exo_panel(0, 100, -50)
    tris += side_exo_panel(0, 100, 50)
    tris += roof_base(0, 100)
    tris += seam_insert_bosses([8])
    tris += accessory_hardpoints([48])
    # rear portal frame, open center for Pi cables/USB/power/air
    tris += box(97.2, 100, -50, 50, 0, 13)
    tris += box(97.2, 100, -50, 50, 113, 133)
    tris += box(97.2, 100, -50, -42, 16, 113)
    tris += box(97.2, 100, 42, 50, 16, 113)
    # seam receiver pads
    tris += box(0, 5, -43, -34, 112, 129)
    tris += box(0, 5, 34, 43, 112, 129)
    tris += velcro_landing(20, 82)
    return tris


def front_shell() -> list[Tri]:
    tris: list[Tri] = []
    # keep x 0..55 open for ultrasonic/camera/servo sweep; module printable length 100
    tris += side_exo_panel(55, 100, -50)
    tris += side_exo_panel(55, 100, 50)
    tris += roof_base(68, 100)
    tris += seam_insert_bosses([92])
    # short brow rails that look like a shell without blocking the front sensors
    tris += box(55, 78, -45, -41, 118, 132)
    tris += box(55, 78, 41, 45, 118, 132)
    tris += box(64, 83, -28, -24, 126, 136)
    tris += box(64, 83, 24, 28, 126, 136)
    # rear seam tongues
    tris += box(96, 100, -42, -35, 112, 129)
    tris += box(96, 100, 35, 42, 112, 129)
    tris += velcro_landing(60, 94)
    return tris


def seam_bridge_pair() -> list[Tri]:
    tris: list[Tri] = []
    # Two top straps; screw clearance holes spaced for bosses at x 8 and 92 after halves meet.
    for y in (-31, 31):
        for cx in (-8, 8):
            tris += annular_cylinder(cx, y, 0, 4.0, outer_d=10.0, inner_d=M3_CLEARANCE_D)
        tris += box(-8, 8, y - 5.0, y - 2.2, 0, 4.0)
        tris += box(-8, 8, y + 2.2, y + 5.0, 0, 4.0)
        # small sci-fi rib on each bridge
        tris += triangular_prism_x(-6, 6, y - 1.8, y + 1.8, 4.0, 7.0)
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
        "# Pip rover shell final, Bambu A1 Mini",
        "",
        "Futuristic velcro-first shell for Pip/Cleo Rover. No display mount in this revision.",
        "The design keeps the front sensor/turret area open, leaves cable/port access at the rear, and uses open side exoskeleton panels for RGB glow and airflow.",
        "",
        "## Insert spec used",
        "",
        f"- {INSERT_SPEC}",
        f"- Final bosses use {INSERT_PILOT_D:.1f} mm nominal pilots with {INSERT_DEPTH:.1f} mm modeled depth.",
        "- Print the coupon first. Use the smallest pilot that melts in cleanly without splitting or bulging the boss.",
        "- If 4.2 mm feels too tight/loose for your filament and iron tip, adjust the source and regenerate before printing the shell.",
        "",
        "## Mounting plan",
        "",
        "- Shell attaches to rover with adhesive Velcro on the inner side landings. Do not drill into the rover yet.",
        "- Heat-set inserts are for the removable top seam bridges and optional future hardpoints, not for chassis mounting.",
        "- Use M3 x 6 or M3 x 8 screws for seam bridges after confirming insert depth; do not bottom out screws into electronics.",
        "",
        "## Print order",
        "",
        "1. `pip_m3x4p6x5p7_insert_coupon_final.stl`",
        "2. `pip_shell_front_open_half_final.stl`",
        "3. `pip_shell_rear_half_final.stl`",
        "4. `pip_shell_seam_bridge_pair_final.stl`",
        "",
        "## Suggested Bambu A1 Mini settings",
        "",
        "- Material: PLA or PETG; PLA easiest for first fit.",
        "- Nozzle: 0.4 mm, layer height 0.20 mm.",
        "- Walls: 3, top/bottom: 4, infill: 12-18% gyroid/cubic.",
        "- Brim: recommended on shell halves.",
        "- Supports: off or organic supports only if slicer flags the raised roof spine. Parts are intended to print upright.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    lines += [
        "",
        "## Fit notes",
        "",
        "- Front x=0..55 mm remains open for camera/ultrasonic pan/tilt sweep.",
        "- Rear wall is a frame only, leaving cables and Pi ports reachable.",
        "- Because the shell is velcro-first, final chassis hole positions are intentionally not guessed.",
        "- After first print, check sensor clearance, wheel clearance, cable exit, and heat after 15 minutes powered on.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_front_open_half_final.stl": front_shell(),
        "pip_shell_rear_half_final.stl": rear_shell(),
        "pip_shell_seam_bridge_pair_final.stl": seam_bridge_pair(),
        "pip_m3x4p6x5p7_insert_coupon_final.stl": heatset_coupon(),
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
            zf.write(path, arcname=f"pip_shell_final/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_final/generate_pip_shell_final_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
