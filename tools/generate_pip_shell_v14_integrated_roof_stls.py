#!/usr/bin/env python3
"""Generate Pip shell v14 integrated one-piece roof.

Fixes v13 mistake: screw holes/collars must be visibly and structurally integrated
into the roof, not isolated rings floating near segmented plate cutouts.

Design rules:
- One piece, A1 Mini safe.
- Starts near x=22 insert line, leaving front turret clearance.
- Uses all 8 v12 insert/screw centers: x=22/78/122/178, y=±41.5.
- Roof follows the exact v12 side-wall slope: z = 100 + 0.15*x.
- Screw holes are true through-holes, 3.8 mm clearance.
- Screw pads are integrated into the plate by overlapping sloped pad material.
- Small rear 100x50 USB mic/speaker Velcro landing, low and simple.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v14_integrated_roof"
ZIP = ROOT / "models" / "pip_shell_v14_integrated_roof_bambu_a1_mini.zip"

X0 = 20.0
X1 = 190.0
HALF_W = 48.0
ROOF_T = 3.6
HOLE_D = 3.8
HOLE_CLEAR = 2.25  # only enough to keep the screw center open; pads/plate still attach around it
PAD_HALF = 8.2
PAD_EXTRA = 2.2
SCREW_HOLES = [(x, y) for x in (22.0, 78.0, 122.0, 178.0) for y in (-41.5, 41.5)]


def height_at_x(x: float) -> float:
    return 100.0 + (max(0.0, min(200.0, x)) / 200.0) * 30.0


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def sloped_box(x0: float, x1: float, y0: float, y1: float, extra0: float, extra1: float) -> list[Tri]:
    z00=height_at_x(x0)+extra0; z10=height_at_x(x1)+extra0
    z01=height_at_x(x0)+extra1; z11=height_at_x(x1)+extra1
    p000=(x0,y0,z00); p100=(x1,y0,z10); p110=(x1,y1,z10); p010=(x0,y1,z00)
    p001=(x0,y0,z01); p101=(x1,y0,z11); p111=(x1,y1,z11); p011=(x0,y1,z01)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 80) -> list[Tri]:
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


def overlaps_center_keepout(x0: float, x1: float, y0: float, y1: float) -> bool:
    for cx, cy in SCREW_HOLES:
        if x0 < cx + HOLE_CLEAR and x1 > cx - HOLE_CLEAR and y0 < cy + HOLE_CLEAR and y1 > cy - HOLE_CLEAR:
            return True
    return False


def segmented_sloped_rect(x0: float, x1: float, y0: float, y1: float, extra0: float, extra1: float) -> list[Tri]:
    """Sloped rectangle with only tiny square keepouts at screw centers.

    This keeps through-holes open while preserving material right up to each pad.
    """
    xs = sorted(set([x0, x1] + [max(x0, cx-HOLE_CLEAR) for cx,_ in SCREW_HOLES] + [min(x1, cx+HOLE_CLEAR) for cx,_ in SCREW_HOLES]))
    ys = sorted(set([y0, y1] + [max(y0, cy-HOLE_CLEAR) for _,cy in SCREW_HOLES] + [min(y1, cy+HOLE_CLEAR) for _,cy in SCREW_HOLES]))
    tris: list[Tri] = []
    for xa, xb in zip(xs, xs[1:]):
        if xb - xa < 0.05:
            continue
        for ya, yb in zip(ys, ys[1:]):
            if yb - ya < 0.05:
                continue
            if overlaps_center_keepout(xa, xb, ya, yb):
                continue
            tris += sloped_box(xa, xb, ya, yb, extra0, extra1)
    return tris


def integrated_screw_pad(cx: float, cy: float) -> list[Tri]:
    """Large pad integrated with roof plus through-hole collar.

    Pad is segmented only around the screw center; it overlaps the base roof plate,
    so Bambu/slicer treats it as one fused solid, not a floating donut.
    """
    tris: list[Tri] = []
    x0, x1 = max(X0, cx-PAD_HALF), min(X1, cx+PAD_HALF)
    y0, y1 = max(-HALF_W, cy-PAD_HALF), min(HALF_W, cy+PAD_HALF)
    tris += segmented_sloped_rect(x0, x1, y0, y1, ROOF_T - 0.4, ROOF_T + PAD_EXTRA)
    # round washer collar inside/overlapping the pad
    tris += annular_cylinder(cx, cy, height_at_x(cx)-0.15, height_at_x(cx)+ROOF_T+PAD_EXTRA+0.6, outer_d=12.5, inner_d=HOLE_D)
    return tris


def mic_landing() -> list[Tri]:
    tris: list[Tri] = []
    x0, x1 = 84.0, 188.0
    y0, y1 = -28.0, 28.0
    # two side rails + two end stops, not a pocket. The tall mic/speaker sits above.
    tris += sloped_box(x0, x1, y0, y0+2.0, ROOF_T+0.2, ROOF_T+5.0)
    tris += sloped_box(x0, x1, y1-2.0, y1, ROOF_T+0.2, ROOF_T+5.0)
    tris += sloped_box(x0, x0+3.2, y0, y1, ROOF_T+0.2, ROOF_T+5.0)
    tris += sloped_box(x1-3.2, x1, y0, y1, ROOF_T+0.2, ROOF_T+5.0)
    # simple rear cable guide ridge
    tris += sloped_box(172.0, 190.0, -5.0, 5.0, ROOF_T+5.0, ROOF_T+8.0)
    return tris


def roof() -> list[Tri]:
    tris: list[Tri] = []
    # main roof body, with tiny keepouts only at screw centers
    tris += segmented_sloped_rect(X0, X1, -HALF_W, HALF_W, 0.0, ROOF_T)
    # integrate every screw hole into broad pads
    for cx, cy in SCREW_HOLES:
        tris += integrated_screw_pad(cx, cy)
    # low center stiffening ridge, not near holes
    tris += sloped_box(34.0, 72.0, -12.0, 12.0, ROOF_T+0.2, ROOF_T+2.6)
    tris += mic_landing()
    return tris


def mic_template() -> list[Tri]:
    return box(-50,50,-25,25,0,1.2)


def readme_text(results: list[tuple[str, Vec]]) -> str:
    lines = [
        "# Pip shell v14 integrated one-piece roof",
        "",
        "Fixes v13: the screw collars are no longer isolated/floating-looking. Each screw hole is embedded in a broad integrated sloped pad that overlaps the roof plate.",
        "",
        "## Fit geometry",
        "",
        "- Fits v12 printable U shell.",
        "- Starts at x=20 mm, leaving the front mostly open for turret/sensor clearance.",
        "- Ends at x=190 mm, leaving rear service/cable space.",
        "- Width is 96 mm, inside the 98 mm shell and under the 100 mm wheel limit.",
        "- Underside follows v12 side-wall slope: z=100+0.15*x.",
        "- Uses all 8 v12 insert centers: x=22/78/122/178, y=±41.5 mm.",
        "- Screw holes are 3.8 mm M3 clearance through-holes.",
        "",
        "## Printability notes",
        "",
        "- One piece, but only about 175 mm long including collars; fits A1 Mini.",
        "- Supports OFF.",
        "- Lay on face in Bambu Studio if needed so it prints flat.",
        "- PETG clear: 0.20 mm, 3 walls, 10-15% infill, slow/default PETG profile.",
        "- Brim recommended if corners lift.",
        "",
        "## USB mic/speaker landing",
        "",
        "- Rear landing rails fit about a 100 x 50 mm oval USB mic/speaker footprint.",
        "- The 50-100 mm tall/thick device sits above the roof and attaches with Velcro/VHB.",
        "",
        "## Verified generated bounding boxes",
        "",
    ]
    for name, size in results:
        fit = "OK" if all(v <= 180 for v in size) else "CHECK"
        lines.append(f"- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})")
    return "\n".join(lines)+"\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        "pip_shell_v14_integrated_one_piece_roof.stl": roof(),
        "pip_shell_v14_usb_mic_100x50_template.stl": mic_template(),
    }
    results=[]
    for filename, tris in parts.items():
        _,_,size=bounds(tris)
        results.append((filename,size))
        write_stl(OUT/filename, filename.removesuffix('.stl'), tris)
    readme=readme_text(results)
    (OUT/"README.md").write_text(readme, encoding="utf-8")
    with ZipFile(ZIP,"w",ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f"pip_shell_v14_integrated_roof/{path.name}")
        zf.write(Path(__file__), arcname="pip_shell_v14_integrated_roof/generate_pip_shell_v14_integrated_roof_stls.py")
    print(readme)
    print(f"ZIP: {ZIP}")


if __name__ == "__main__":
    main()
