#!/usr/bin/env python3
"""Generate Pip shell v13 one-piece sloped roof.

Matches v12 printable U shell geometry:
- Shell insert/screw centers: x=22/78/122/178, y=±41.5 mm
- Shell max width: 98 mm
- Side wall top slope: 100 mm at x=0 to 130 mm at x=200

Roof strategy:
- One piece, x=22..200 mm, y=±48 mm.
- Starts at the first insert columns instead of x=0, leaving the very front open
  for turret/sensor clearance.
- Sloped underside/top follows the same linear shell slope.
- True vertical through-holes for all 8 M3 screws.
- Rear 100 x 50 mm oval-ish/rounded Velcro landing for USB mic/speaker.
- Low profile, printability-first: no unsupported fins, no tall ornamentation.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v13_one_piece_roof"
ZIP = ROOT / "models" / "pip_shell_v13_one_piece_roof_bambu_a1_mini.zip"

X0 = 22.0
X1 = 190.0
HALF_W = 48.0
ROOF_T = 3.2
SCREW_HOLES = [(x, y) for x in (22.0, 78.0, 122.0, 178.0) for y in (-41.5, 41.5)]
HOLE_CLEAR = 6.5
SCREW_CLEAR_D = 3.8
COLLAR_OD = 11.5


def height_at_x(x: float) -> float:
    return 100.0 + (max(0.0, min(200.0, x)) / 200.0) * 30.0


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def sloped_box(x0: float, x1: float, y0: float, y1: float, extra0: float, extra1: float) -> list[Tri]:
    """Box whose lower and upper z follow the shell slope plus offsets."""
    z00 = height_at_x(x0) + extra0
    z10 = height_at_x(x1) + extra0
    z01 = height_at_x(x0) + extra1
    z11 = height_at_x(x1) + extra1
    p000=(x0,y0,z00); p100=(x1,y0,z10); p110=(x1,y1,z10); p010=(x0,y1,z00)
    p001=(x0,y0,z01); p101=(x1,y0,z11); p111=(x1,y1,z11); p011=(x0,y1,z01)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 72) -> list[Tri]:
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


def overlaps_hole_square(x0: float, x1: float, y0: float, y1: float) -> bool:
    for cx, cy in SCREW_HOLES:
        if x0 < cx + HOLE_CLEAR and x1 > cx - HOLE_CLEAR and y0 < cy + HOLE_CLEAR and y1 > cy - HOLE_CLEAR:
            return True
    return False


def roof_plate_segmented() -> list[Tri]:
    tris: list[Tri] = []
    xs = sorted(set([X0, X1] + [max(X0, cx-HOLE_CLEAR) for cx,_ in SCREW_HOLES] + [min(X1, cx+HOLE_CLEAR) for cx,_ in SCREW_HOLES]))
    ys = sorted(set([-HALF_W, HALF_W] + [max(-HALF_W, cy-HOLE_CLEAR) for _,cy in SCREW_HOLES] + [min(HALF_W, cy+HOLE_CLEAR) for _,cy in SCREW_HOLES]))
    for xa, xb in zip(xs, xs[1:]):
        if xb - xa < 0.1:
            continue
        for ya, yb in zip(ys, ys[1:]):
            if yb - ya < 0.1:
                continue
            if overlaps_hole_square(xa, xb, ya, yb):
                continue
            tris += sloped_box(xa, xb, ya, yb, 0.0, ROOF_T)
    # screw collars / washers, also true through-holes.
    for cx, cy in SCREW_HOLES:
        tris += annular_cylinder(cx, cy, height_at_x(cx) - 0.15, height_at_x(cx) + ROOF_T + 1.0, COLLAR_OD, SCREW_CLEAR_D)
    return tris


def mic_landing() -> list[Tri]:
    """Low rear Velcro landing for 100x50 oval/rounded USB mic/speaker.

    Keep it low and simple: two side rails plus two end stops, no roof overhangs.
    It sits on top of the sloped plate, x=84..188, y=±28.
    """
    tris: list[Tri] = []
    x0, x1 = 84.0, 188.0
    y0, y1 = -28.0, 28.0
    rail_t = 2.0
    rail_h0 = ROOF_T + 0.4
    rail_h1 = ROOF_T + 5.0
    # Long side rails for velcro alignment around 100x50 device.
    tris += sloped_box(x0, x1, y0, y0 + rail_t, rail_h0, rail_h1)
    tris += sloped_box(x0, x1, y1 - rail_t, y1, rail_h0, rail_h1)
    # Rear and front shallow end stops, leaving center open for adhesive/velcro.
    tris += sloped_box(x0, x0 + 3.0, y0, y1, rail_h0, rail_h1)
    tris += sloped_box(x1 - 3.0, x1, y0, y1, rail_h0, rail_h1)
    # Cable guide notch/ridge towards rear center.
    tris += sloped_box(173.0, 190.0, -5.0, 5.0, rail_h1, rail_h1 + 3.2)
    return tris


def roof() -> list[Tri]:
    tris = roof_plate_segmented()
    tris += mic_landing()
    # simple front brow line, low enough not to create a print risk
    tris += sloped_box(24.0, 88.0, -18.0, 18.0, ROOF_T + 0.3, ROOF_T + 2.6)
    return tris


def mic_template() -> list[Tri]:
    return box(-50,50,-25,25,0,1.2)


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v13 one-piece sloped roof",
        "",
        "Simple one-piece roof for the v12 printable U shell.",
        "",
        "## Fit geometry",
        "",
        "- Starts at x=22 mm, leaving the front 22 mm open for turret/sensor clearance.",
        "- Ends at x=190 mm, leaving a 10 mm rear cable/service gap on the v12 U-cowl.",
        "- Width is 96 mm, within the 98 mm v12 shell width and under the 100 mm wheel limit.",
        "- Underside follows the exact shell top slope: z=100+0.15*x.",
        "- Screw holes use all 8 v12 insert centers: x=22/78/122/178, y=±41.5 mm.",
        "- Screw holes are 3.8 mm M3 clearance through-holes.",
        "",
        "## USB mic/speaker landing",
        "",
        "- Rear raised landing/slot is sized for about 100 x 50 mm oval USB mic/speaker footprint.",
        "- The mic/speaker can be Velcroed or VHB-taped into the raised rails.",
        "- The device's 50-100 mm height/depth is expected to sit above the roof, not inside the roof.",
        "",
        "## Printing",
        "",
        "- This roof is modeled in final installed orientation, so it appears sloped.",
        "- In Bambu Studio, use Lay on Face on the broad underside/top plane if needed so it prints flat.",
        "- It is about 174 mm long including front screw collars, so it fits A1 Mini better than a full x=200 roof.",
        "- Supports: OFF.",
        "- Brim: optional but recommended for PETG corners.",
        "- PETG clear: 0.20 mm, 3 walls, 10-15% infill, slow/default PETG profile.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name,size in results:
        fit = "OK" if size[0] <= 180 and size[1] <= 180 and size[2] <= 180 else "CHECK"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    return "\n".join(lines)+"\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v13_one_piece_sloped_roof.stl": roof(),
        "pip_shell_v13_usb_mic_100x50_template.stl": mic_template(),
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
            zf.write(path, arcname=f"pip_shell_v13_one_piece_roof/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v13_one_piece_roof/generate_pip_shell_v13_one_piece_roof_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
