#!/usr/bin/env python3
"""Generate Pip shell v12: printable-first modular U shell.

This revision follows the post-failure print audit and public FDM/PETG design
rules:
- max shell width under 100 mm
- no unsupported decorative cantilevers
- no full-width bottom crossbars over electronics
- no roof in the base shell
- lower RGB vents only, with short spans
- heat-set insert hardpoints are simple vertical boss/pillars, not tabbed bars

Parts are modular for print reliability:
- two front side rails, printed separately
- one rear U-cowl with rear wall connecting the sides
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v12_printable_u"
ZIP = ROOT / "models" / "pip_shell_v12_printable_u_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
WIDTH = 98.0
HALF_W = WIDTH / 2.0
WALL_T = 3.0
L_FRONT = 100.0
L_REAR = 100.0
INSERT_PILOT_D = 4.2
BOSS_OD = 10.0


def height_at_x(x: float) -> float:
    # 100 mm at front, 130 mm at rear over total 200 mm length.
    return 100.0 + (max(0.0, min(200.0, x)) / 200.0) * 30.0


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def wedge_panel(x0: float, x1: float, y0: float, y1: float, z0: float, h0: float, h1: float) -> list[Tri]:
    """Solid wall section with sloped top from h0 to h1."""
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,h0); p101=(x1,y0,h1); p111=(x1,y1,h1); p011=(x0,y1,h0)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 64) -> list[Tri]:
    tris: list[Tri] = []
    ro=outer_d/2.0; ri=inner_d/2.0
    for i in range(segments):
        a0=2*math.pi*i/segments; a1=2*math.pi*(i+1)/segments
        o0b=(cx+ro*math.cos(a0), cy+ro*math.sin(a0), z0); o1b=(cx+ro*math.cos(a1), cy+ro*math.sin(a1), z0)
        o0t=(cx+ro*math.cos(a0), cy+ro*math.sin(a0), z1); o1t=(cx+ro*math.cos(a1), cy+ro*math.sin(a1), z1)
        i0b=(cx+ri*math.cos(a0), cy+ri*math.sin(a0), z0); i1b=(cx+ri*math.cos(a1), cy+ri*math.sin(a1), z0)
        i0t=(cx+ri*math.cos(a0), cy+ri*math.sin(a0), z1); i1t=(cx+ri*math.cos(a1), cy+ri*math.sin(a1), z1)
        tris += [(o0b,o1b,o1t),(o0b,o1t,o0t)]
        tris += [(i0b,i1t,i1b),(i0b,i0t,i1t)]
        tris += [(o0t,o1t,i1t),(o0t,i1t,i0t)]
        tris += [(o0b,i1b,o1b),(o0b,i0b,i1b)]
    return tris


def normal(a: Vec, b: Vec, c: Vec) -> Vec:
    ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2]
    vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
    nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
    length=(nx*nx+ny*ny+nz*nz)**0.5 or 1.0
    return (nx/length,ny/length,nz/length)


def write_stl(path: Path, name: str, tris: Iterable[Tri]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"solid {name}\n")
        for a,b,c in tris:
            n=normal(a,b,c)
            f.write(f"  facet normal {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}\n")
            f.write("    outer loop\n")
            for p in (a,b,c):
                f.write(f"      vertex {p[0]:.6g} {p[1]:.6g} {p[2]:.6g}\n")
            f.write("    endloop\n  endfacet\n")
        f.write(f"endsolid {name}\n")


def bounds(tris: Iterable[Tri]) -> tuple[Vec, Vec, Vec]:
    xs=[]; ys=[]; zs=[]
    for tri in tris:
        for x,y,z in tri:
            xs.append(x); ys.append(y); zs.append(z)
    mn=(min(xs),min(ys),min(zs)); mx=(max(xs),max(ys),max(zs))
    return mn,mx,(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])


def side_y(sign: int) -> tuple[float, float, float]:
    if sign < 0:
        return (-HALF_W, -HALF_W + WALL_T, -41.5)
    return (HALF_W - WALL_T, HALF_W, 41.5)


def lower_vent_strip(x0: float, x1: float, y0: float, y1: float) -> list[Tri]:
    """Small lower RGB strip. 6 mm openings max; no fragile bars."""
    tris: list[Tri] = []
    # solid bottom rail and top rail
    tris += box(x0, x1, y0, y1, 0, 10)
    tris += box(x0, x1, y0, y1, 31, 36)
    # robust posts create vertical vent windows; openings <= 6 mm.
    post_w = 4.0
    pitch = 10.0
    x = x0
    while x < x1 - 0.1:
        tris += box(x, min(x + post_w, x1), y0, y1, 10, 31)
        x += pitch
    return tris


def side_rail(x0: float, x1: float, sign: int) -> list[Tri]:
    y0,y1,boss_y=side_y(sign)
    h0=height_at_x(x0); h1=height_at_x(x1)
    tris: list[Tri] = []
    # upper solid wall above vent band, sloped top. No overhangs.
    tris += wedge_panel(x0, x1, y0, y1, 36, h0, h1)
    tris += lower_vent_strip(x0, x1, y0, y1)
    # inner velcro ledge: simple vertical strip, supported from bed, not a cantilever tab.
    inner0, inner1 = (y1, min(y1 + 2.6, HALF_W)) if sign < 0 else (max(y0 - 2.6, -HALF_W), y0)
    tris += wedge_panel(x0 + 8, x1 - 8, inner0, inner1, 0, min(18, h0), min(18, h1))
    return tris


def roof_boss_pillar(x: float, sign: int) -> list[Tri]:
    """Simple vertical boss/pillar, no side bars/tabs. Through-pilot for heat insert."""
    _,_,boss_y=side_y(sign)
    h=height_at_x(x)
    return annular_cylinder(x, boss_y, 0, h + 2.8, BOSS_OD, INSERT_PILOT_D)


def front_left_rail() -> list[Tri]:
    tris=side_rail(0, 100, -1)
    for x in (22.0, 78.0):
        tris += roof_boss_pillar(x, -1)
    return tris


def front_right_rail() -> list[Tri]:
    tris=side_rail(0, 100, 1)
    for x in (22.0, 78.0):
        tris += roof_boss_pillar(x, 1)
    return tris


def rear_u_cowl() -> list[Tri]:
    tris: list[Tri] = []
    tris += side_rail(100, 200, -1)
    tris += side_rail(100, 200, 1)
    for sign in (-1, 1):
        for x in (122.0, 178.0):
            tris += roof_boss_pillar(x, sign)
    # rear wall only, connected to side walls; lower central cable relief left open.
    x0, x1 = 197.0, 200.0
    h0=height_at_x(197.0); h1=height_at_x(200.0)
    tris += wedge_panel(x0, x1, -HALF_W, HALF_W, 36, h0, h1)
    tris += box(x0, x1, -HALF_W, -33.0, 0, 36)
    tris += box(x0, x1, 33.0, HALF_W, 0, 36)
    return tris


def seam_clip_pair() -> list[Tri]:
    """Two screw-on seam bridge plates for joining front rails to the rear U-cowl.

    Coordinates intentionally match the assembled shell coordinate system:
    - front rail rear insert centers: x=78, y=±41.5
    - rear cowl front insert centers: x=122, y=±41.5

    The plates bridge across the x=100 seam. Holes are true 3.6 mm M3
    clearance holes, not filled circles. They screw down into heat-set inserts
    installed in the rail/cowl boss pilots.
    """
    tris: list[Tri] = []
    hole_r_clear = 3.6 / 2.0
    boss_clearance = 5.0
    plate_x0, plate_x1 = 66.0, 134.0
    plate_t = 3.2
    for y in (-41.5, 41.5):
        y0, y1 = y - 7.0, y + 7.0
        # Horizontal strips above/below the screw holes.
        tris += box(plate_x0, plate_x1, y0, y - boss_clearance, 0, plate_t)
        tris += box(plate_x0, plate_x1, y + boss_clearance, y1, 0, plate_t)
        # Center band split around both holes so no face caps the screw path.
        tris += box(plate_x0, 78.0 - boss_clearance, y - boss_clearance, y + boss_clearance, 0, plate_t)
        tris += box(78.0 + boss_clearance, 122.0 - boss_clearance, y - boss_clearance, y + boss_clearance, 0, plate_t)
        tris += box(122.0 + boss_clearance, plate_x1, y - boss_clearance, y + boss_clearance, 0, plate_t)
        # Washer collars around true through holes.
        for cx in (78.0, 122.0):
            tris += annular_cylinder(cx, y, 0, plate_t, outer_d=12.0, inner_d=3.6)
    return tris


def insert_coupon() -> list[Tri]:
    tris: list[Tri] = []
    tris += box(-36,36,-10,-6.5,0,2.4)
    tris += box(-36,36,6.5,10,0,2.4)
    for cx,hole in [(-24,4.1),(0,4.2),(24,4.3)]:
        tris += annular_cylinder(cx,0,0,6.4,outer_d=12.0,inner_d=hole)
    return tris


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v12 printable U kit",
        "",
        "Research-driven redesign after PETG failures. This is intentionally simple: side rails plus rear U-cowl.",
        "",
        "## Design rules applied",
        "",
        "- Max width is 98 mm, below the 100 mm wheel-clearance limit.",
        "- No unsupported decorative cantilevers or side tabs.",
        "- Heat-set insert hardpoints are plain vertical boss/pillars with 4.2 mm pilot holes.",
        "- Bosses have material around the hole and depth greater than the 5.7 mm insert length.",
        "- Lower RGB vents use short <=6 mm openings and chunky posts.",
        "- No roof, no full-width center/bottom rails over electronics, no support forest.",
        "- Front is open; rear wall is the only cross-wall.",
        "",
        "## Assembly shape",
        "",
        "- Front left rail + front right rail cover the front sides only.",
        "- Rear U-cowl covers both rear sides and the back.",
        "- Use Velcro on the inside lower ledges/chassis. Do not drill the rover.",
        "- Future roof/seam screw centers: x=22/78/122/178, y=±41.5 mm.",
        "- The seam bridge pair screws across x=78 to x=122, joining each front rail to the rear U-cowl.",
        "",
        "## PETG/Bambu settings",
        "",
        "- Supports: OFF.",
        "- Brim: 5-8 mm, especially on side rails.",
        "- 0.20 mm layer height, 3 walls, 10-15% gyroid/cubic.",
        "- Use slow/default PETG profile, not sport/ludicrous.",
        "- Dry clear PETG if stringing/bubbling/cloudy weak layers appear.",
        "- Glue/release agent on PEI if PETG sticks too aggressively.",
        "",
        "## Print order",
        "",
        "1. `pip_shell_v12_front_left_rail.stl` and `pip_shell_v12_front_right_rail.stl` as the width/fit test.",
        "2. `pip_shell_v12_rear_u_cowl.stl` only after front rail clearance is confirmed.",
        "3. Optional seam clip/coupon only if needed.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name,size in results:
        fit = "OK" if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else "TOO LARGE"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    return "\n".join(lines)+"\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v12_front_left_rail.stl": front_left_rail(),
        "pip_shell_v12_front_right_rail.stl": front_right_rail(),
        "pip_shell_v12_rear_u_cowl.stl": rear_u_cowl(),
        "pip_shell_v12_seam_clip_pair.stl": seam_clip_pair(),
        "pip_shell_v12_insert_coupon_4p1_4p2_4p3.stl": insert_coupon(),
    }
    results=[]
    for filename,tris in parts.items():
        _,_,size=bounds(tris)
        results.append((filename,size))
        write_stl(OUT/filename, filename.removesuffix('.stl'), tris)
    readme=readme_text(results)
    (OUT/"README.md").write_text(readme, encoding="utf-8")
    with ZipFile(ZIP,"w",ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f"pip_shell_v12_printable_u/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v12_printable_u/generate_pip_shell_v12_printable_u_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
