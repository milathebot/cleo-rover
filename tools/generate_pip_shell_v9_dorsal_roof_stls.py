#!/usr/bin/env python3
"""Generate Pip shell v9 dorsal cyber roof kit.

Fixes from v8:
- Screw holes are truly through-holes. The base plate is segmented around every
  screw center so no hidden flat face fills the hole.
- More extravagant futuristic vehicle styling: faceted dorsal mic pod, side
  flying buttresses, bolt collars, rear cable fin, and layered armor plates.
- Aligns with v6 open-top shell insert hardpoints.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable, Sequence

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v9_dorsal_roof"
ZIP = ROOT / "models" / "pip_shell_v9_dorsal_roof_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
M3_CLEARANCE = 3.7
Y_HALF = 54.0
BASE_T = 3.0
HOLE_GAP_R = 5.4  # square keepout around screw center in base plates


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return []
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 72) -> list[Tri]:
    tris: list[Tri] = []
    ro=outer_d/2; ri=inner_d/2
    for i in range(segments):
        a0=2*math.pi*i/segments; a1=2*math.pi*(i+1)/segments
        o0b=(cx+ro*math.cos(a0),cy+ro*math.sin(a0),z0); o1b=(cx+ro*math.cos(a1),cy+ro*math.sin(a1),z0)
        o0t=(cx+ro*math.cos(a0),cy+ro*math.sin(a0),z1); o1t=(cx+ro*math.cos(a1),cy+ro*math.sin(a1),z1)
        i0b=(cx+ri*math.cos(a0),cy+ri*math.sin(a0),z0); i1b=(cx+ri*math.cos(a1),cy+ri*math.sin(a1),z0)
        i0t=(cx+ri*math.cos(a0),cy+ri*math.sin(a0),z1); i1t=(cx+ri*math.cos(a1),cy+ri*math.sin(a1),z1)
        tris += [(o0b,o1b,o1t),(o0b,o1t,o0t),(i0b,i1t,i1b),(i0b,i0t,i1t),(o0t,o1t,i1t),(o0t,i1t,i0t),(o0b,i1b,o1b),(o0b,i0b,i1b)]
    return tris


def triangular_prism_x(x0: float, x1: float, y0: float, y1: float, z_base: float, z_peak: float) -> list[Tri]:
    ym=(y0+y1)/2
    a0=(x0,y0,z_base); b0=(x0,y1,z_base); c0=(x0,ym,z_peak)
    a1=(x1,y0,z_base); b1=(x1,y1,z_base); c1=(x1,ym,z_peak)
    return [(a0,c0,b0),(a1,b1,c1),(a0,a1,c1),(a0,c1,c0),(b0,c0,c1),(b0,c1,b1),(a0,b0,b1),(a0,b1,a1)]


def wedge_panel_x(x0: float, x1: float, y0: float, y1: float, z0: float, z_left: float, z_right: float) -> list[Tri]:
    p00=(x0,y0,z0); p10=(x1,y0,z0); p11=(x1,y1,z0); p01=(x0,y1,z0)
    q00=(x0,y0,z_left); q01=(x0,y1,z_left); q10=(x1,y0,z_right); q11=(x1,y1,z_right)
    return [(p00,p11,p10),(p00,p01,p11),(q00,q10,q11),(q00,q11,q01),(p00,q00,q01),(p00,q01,p01),(p10,p11,q11),(p10,q11,q10),(p00,p10,q10),(p00,q10,q00),(p01,q01,q11),(p01,q11,p11)]


def normal(a: Vec,b: Vec,c: Vec) -> Vec:
    ux,uy,uz=b[0]-a[0],b[1]-a[1],b[2]-a[2]
    vx,vy,vz=c[0]-a[0],c[1]-a[1],c[2]-a[2]
    nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
    l=(nx*nx+ny*ny+nz*nz)**0.5 or 1.0
    return (nx/l,ny/l,nz/l)


def write_stl(path: Path, name: str, tris: Iterable[Tri]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        f.write(f'solid {name}\n')
        for a,b,c in tris:
            n=normal(a,b,c)
            f.write(f'  facet normal {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}\n')
            f.write('    outer loop\n')
            for p in (a,b,c):
                f.write(f'      vertex {p[0]:.6g} {p[1]:.6g} {p[2]:.6g}\n')
            f.write('    endloop\n  endfacet\n')
        f.write(f'endsolid {name}\n')


def base_plate_with_through_hole_keepouts(x0: float, x1: float, centers: Sequence[tuple[float, float]]) -> list[Tri]:
    """Build base out of rectangles, leaving square holes under screw collars."""
    tris: list[Tri] = []
    # broad center plate, away from edge screw centers
    tris += box(x0, x1, -39.0, 39.0, 0, BASE_T)
    # side edge strips segmented around screw keepouts
    for y0, y1, cy in [(39.0, Y_HALF, 47.5), (-Y_HALF, -39.0, -47.5)]:
        xs = sorted([x0, x1] + [cx - HOLE_GAP_R for cx, c_y in centers if abs(c_y - cy) < 0.2] + [cx + HOLE_GAP_R for cx, c_y in centers if abs(c_y - cy) < 0.2])
        # create intervals and skip intervals overlapping keepout windows
        for a, b in zip(xs, xs[1:]):
            if b <= a:
                continue
            mid=(a+b)/2
            if any(abs(mid-cx) < HOLE_GAP_R and abs(c_y-cy) < 0.2 for cx,c_y in centers):
                continue
            tris += box(a, b, y0, y1, 0, BASE_T)
    # narrow front/rear lip segments also avoid hole squares
    return tris


def screw_collars(centers: Sequence[tuple[float, float]]) -> list[Tri]:
    tris: list[Tri] = []
    for cx, cy in centers:
        tris += annular_cylinder(cx, cy, 0, 7.8, outer_d=14.0, inner_d=M3_CLEARANCE)
        # angular collar wings that do not cross the central hole
        tris += box(cx - 9.0, cx - 3.2, cy - 3.0, cy + 3.0, BASE_T, 5.6)
        tris += box(cx + 3.2, cx + 9.0, cy - 3.0, cy + 3.0, BASE_T, 5.6)
        tris += box(cx - 3.0, cx + 3.0, cy - 9.0, cy - 3.2, BASE_T, 5.6)
        tris += box(cx - 3.0, cx + 3.0, cy + 3.2, cy + 9.0, BASE_T, 5.6)
    return tris


def mic_cradle_segment(x0: float, x1: float, center_x: float = 100.0) -> list[Tri]:
    tris: list[Tri] = []
    inner_len=104.0; inner_w=52.0; outer_w=72.0
    sx0=max(x0+3, center_x-inner_len/2)
    sx1=min(x1-3, center_x+inner_len/2)
    if sx1 > sx0:
        # Tall side nacelles for 50mm-deep oval mic. Center remains open for Velcro.
        tris += box(sx0, sx1, inner_w/2, outer_w/2, BASE_T, 17.0)
        tris += box(sx0, sx1, -outer_w/2, -inner_w/2, BASE_T, 17.0)
        tris += triangular_prism_x(sx0+2, sx1-2, inner_w/2+1.0, outer_w/2-1.0, 17.0, 28.0)
        tris += triangular_prism_x(sx0+2, sx1-2, -outer_w/2+1.0, -inner_w/2-1.0, 17.0, 28.0)
        # low bed under mic, still not a screw issue because centerline only
        tris += box(sx0, sx1, -inner_w/2, inner_w/2, BASE_T, 4.0)
    for ex in (center_x-inner_len/2, center_x+inner_len/2):
        if x0 <= ex <= x1:
            tris += box(ex-4.5, ex+4.5, -inner_w/2, inner_w/2, BASE_T, 15.0)
            tris += triangular_prism_x(ex-4.5, ex+4.5, -inner_w/2, inner_w/2, 15.0, 25.0)
    return tris


def roof_half(kind: str) -> list[Tri]:
    if kind == 'front':
        x0, x1 = 4.0, 100.0
        centers=[(22,-47.5),(22,47.5),(78,-47.5),(78,47.5)]
        z_l, z_r = 4.5, 12.0
    else:
        x0, x1 = 100.0, 196.0
        centers=[(122,-47.5),(122,47.5),(178,-47.5),(178,47.5)]
        z_l, z_r = 12.0, 6.0
    tris: list[Tri] = []
    tris += base_plate_with_through_hole_keepouts(x0, x1, centers)
    # Layered faceted body panels, kept away from screw edge zones.
    tris += wedge_panel_x(x0+5, x1-5, -28, 28, BASE_T, z_l, z_r)
    tris += wedge_panel_x(x0+9, x1-9, -39, -31, BASE_T, max(6, z_l-1), max(7, z_r-1))
    tris += wedge_panel_x(x0+9, x1-9, 31, 39, BASE_T, max(6, z_l-1), max(7, z_r-1))
    # Side "future vehicle" outriggers / cheek fins, segmented so screw holes stay clear.
    hole_xs = sorted(cx for cx, _ in centers)
    fin_breaks = [x0 + 12, x1 - 12]
    for hx in hole_xs:
        fin_breaks += [hx - 8.5, hx + 8.5]
    fin_breaks = sorted(v for v in fin_breaks if x0 + 12 <= v <= x1 - 12)
    for a, b in zip(fin_breaks, fin_breaks[1:]):
        if b - a < 5:
            continue
        mid = (a + b) / 2
        if any(abs(mid - hx) < 8.5 for hx in hole_xs):
            continue
        tris += triangular_prism_x(a, b, -53, -45, BASE_T, 12.0)
        tris += triangular_prism_x(a, b, 45, 53, BASE_T, 12.0)
    tris += box(x0+16, x1-16, -44, -41, BASE_T, 9.0)
    tris += box(x0+16, x1-16, 41, 44, BASE_T, 9.0)
    # Aggressive split dorsal ridges that point toward the mic pod.
    if kind == 'front':
        tris += triangular_prism_x(x0+10, 45, -10, 10, BASE_T, 17.0)
        tris += triangular_prism_x(x0+20, 58, -23, -15, BASE_T, 12.0)
        tris += triangular_prism_x(x0+20, 58, 15, 23, BASE_T, 12.0)
    else:
        tris += triangular_prism_x(154, x1-10, -10, 10, BASE_T, 16.0)
        tris += triangular_prism_x(142, x1-20, -23, -15, BASE_T, 12.0)
        tris += triangular_prism_x(142, x1-20, 15, 23, BASE_T, 12.0)
        # rear cable fin/tunnel for USB mic cable
        tris += box(150, 192, -4.5, 4.5, BASE_T, 9.0)
        tris += triangular_prism_x(150, 192, -8, 8, 9.0, 17.0)
    tris += mic_cradle_segment(x0, x1)
    tris += screw_collars(centers)
    return tris


def mic_envelope() -> list[Tri]:
    tris: list[Tri] = []
    tris += box(-50,50,-25,25,0,2)
    tris += box(-50,50,-25,-23,0,50)
    tris += box(-50,50,23,25,0,50)
    tris += box(-50,-48,-25,25,0,50)
    tris += box(48,50,-25,25,0,50)
    # top ridges to make the envelope visible in slicer
    for x in [-40,-25,-10,5,20,35]:
        tris += box(x,x+2,-22,22,50,52)
    return tris


def bounds(tris: Iterable[Tri]) -> tuple[Vec, Vec, Vec]:
    xs=[]; ys=[]; zs=[]
    for tri in tris:
        for x,y,z in tri:
            xs.append(x); ys.append(y); zs.append(z)
    mn=(min(xs),min(ys),min(zs)); mx=(max(xs),max(ys),max(zs))
    return mn,mx,(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])


def readme(results: list[tuple[str, Vec]]) -> str:
    lines=[
        '# Pip shell v9 dorsal cyber roof kit','',
        'Extravagant future-rover roof for the v6 open-top Pip shell. This replaces v8 with true through screw holes and a more sculpted mic pod / vehicle roof silhouette.','',
        '## Alignment','',
        '- Front roof screw centers: x=22 and 78 mm, y=±47.5 mm.',
        '- Rear roof screw centers: x=122 and 178 mm, y=±47.5 mm.',
        f'- Screw holes are true through-holes with {M3_CLEARANCE:.1f} mm M3 clearance.',
        '- The base plate is segmented around every screw center so no hidden face fills the holes.','',
        '## USB mic cradle','',
        '- Designed around an oval USB mic about 100 x 50 x 50 mm.',
        '- Raised dorsal side nacelles and end stops hold the mic visually as Pip’s roof pod.',
        '- Use thin Velcro/VHB or glue in the center cradle. Rear half includes a raised cable guide.','',
        '## Print settings','',
        '- Print flat on bed, decorative side up.',
        '- Supports: off first. Geometry is raised from the plate, not a roof over empty air.',
        '- PETG clear: 0.20 mm, 3 walls, 10-15% infill, normal/slow profile.',
        '- Brim optional if corners lift.','',
        '## Verified bounding boxes','',
    ]
    for name,size in results:
        fit='OK' if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else 'TOO LARGE'
        lines.append(f'- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})')
    return '\n'.join(lines)+'\n'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts={
        'pip_shell_v9_front_dorsal_cyber_roof.stl': roof_half('front'),
        'pip_shell_v9_rear_dorsal_cyber_roof.stl': roof_half('rear'),
        'pip_shell_v9_usb_mic_100x50x50_envelope.stl': mic_envelope(),
    }
    results=[]
    for filename,tris in parts.items():
        _,_,size=bounds(tris)
        results.append((filename,size))
        write_stl(OUT/filename, filename.removesuffix('.stl'), tris)
    text=readme(results)
    (OUT/'README.md').write_text(text, encoding='utf-8')
    with ZipFile(ZIP,'w',ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f'pip_shell_v9_dorsal_roof/{path.name}')
        zf.write(Path(__file__), arcname='pip_shell_v9_dorsal_roof/generate_pip_shell_v9_dorsal_roof_stls.py')
    print(text)
    print(f'ZIP: {ZIP}')


if __name__ == '__main__':
    main()
