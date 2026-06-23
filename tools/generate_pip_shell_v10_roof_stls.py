#!/usr/bin/env python3
"""Generate Pip shell v10 styled roof kit.

Goals from user feedback:
- Screw holes must go all the way through and visibly stay open in slicer.
- Front/rear roof halves must visually connect at the seam.
- Aesthetics should read as a futuristic vehicle roof, not a flat plate.
- Must align to v6 shell insert hardpoints.
- Include a 100 x 50 x 50 mm USB mic cradle/slot area.

The model is intentionally built from printable, bed-up features: flat base,
raised polygon armor panels, faceted dorsal mic pod, and screw collars. No roof
spans over empty air, so supports should be off.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable, Sequence

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v10_styled_roof"
ZIP = ROOT / "models" / "pip_shell_v10_styled_roof_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
M3_CLEARANCE = 3.8
Y_HALF = 54.0
BASE_T = 3.0
HOLE_GAP_R = 6.0


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return []
    p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [(p000,p110,p100),(p000,p010,p110),(p001,p101,p111),(p001,p111,p011),(p000,p001,p011),(p000,p011,p010),(p100,p110,p111),(p100,p111,p101),(p000,p100,p101),(p000,p101,p001),(p010,p011,p111),(p010,p111,p110)]


def polygon_prism(points: Sequence[tuple[float, float]], z0: float, z1: float) -> list[Tri]:
    """Extrude a convex-ish XY polygon between z0/z1."""
    if len(points) < 3 or z1 <= z0:
        return []
    tris: list[Tri] = []
    bottom=[(x,y,z0) for x,y in points]
    top=[(x,y,z1) for x,y in points]
    # fan triangulation; all polygons used here are convex/simple enough.
    for i in range(1, len(points)-1):
        tris.append((bottom[0], bottom[i+1], bottom[i]))
        tris.append((top[0], top[i], top[i+1]))
    for i in range(len(points)):
        j=(i+1)%len(points)
        tris += [(bottom[i], bottom[j], top[j]), (bottom[i], top[j], top[i])]
    return tris


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 80) -> list[Tri]:
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
    """Base rectangles leave keepout squares under every screw center."""
    tris: list[Tri] = []
    # center field avoids y=±47.5 screw rows completely
    tris += box(x0, x1, -38.0, 38.0, 0, BASE_T)
    # screw-row side strips are split around each hole keepout
    for y0, y1, cy in [(38.0, Y_HALF, 47.5), (-Y_HALF, -38.0, -47.5)]:
        cuts = sorted([x0, x1] + [cx - HOLE_GAP_R for cx,c_y in centers if abs(c_y-cy)<0.2] + [cx + HOLE_GAP_R for cx,c_y in centers if abs(c_y-cy)<0.2])
        for a,b in zip(cuts, cuts[1:]):
            mid=(a+b)/2
            if any(abs(mid-cx) < HOLE_GAP_R and abs(c_y-cy)<0.2 for cx,c_y in centers):
                continue
            tris += box(a,b,y0,y1,0,BASE_T)
    return tris


def screw_collars(centers: Sequence[tuple[float, float]]) -> list[Tri]:
    tris: list[Tri] = []
    for cx,cy in centers:
        tris += annular_cylinder(cx, cy, 0, 8.6, outer_d=15.2, inner_d=M3_CLEARANCE)
        # diamond/angular collar wings, all split around the through-hole.
        tris += polygon_prism([(cx-12,cy),(cx-7,cy-5),(cx-3.2,cy-3.0),(cx-3.2,cy+3.0),(cx-7,cy+5)], BASE_T, 6.4)
        tris += polygon_prism([(cx+12,cy),(cx+7,cy-5),(cx+3.2,cy-3.0),(cx+3.2,cy+3.0),(cx+7,cy+5)], BASE_T, 6.4)
        tris += polygon_prism([(cx,cy-12),(cx-5,cy-7),(cx-3.0,cy-3.2),(cx+3.0,cy-3.2),(cx+5,cy-7)], BASE_T, 6.4)
        tris += polygon_prism([(cx,cy+12),(cx-5,cy+7),(cx-3.0,cy+3.2),(cx+3.0,cy+3.2),(cx+5,cy+7)], BASE_T, 6.4)
    return tris


def edge_fins(x0: float, x1: float, centers: Sequence[tuple[float, float]]) -> list[Tri]:
    tris: list[Tri] = []
    hole_xs = sorted({cx for cx,_ in centers})
    intervals = [(x0+8, hole_xs[0]-12), (hole_xs[0]+12, hole_xs[1]-12), (hole_xs[1]+12, x1-8)]
    for a,b in intervals:
        if b-a < 8:
            continue
        # asymmetric swept fins, more vehicle-like than straight bars.
        tris += polygon_prism([(a,-55.8),(b,-55.8),(b-6,-48.0),(a+4,-44.0)], BASE_T, 10.5)
        tris += polygon_prism([(a,55.8),(b,55.8),(b-6,48.0),(a+4,44.0)], BASE_T, 10.5)
        tris += triangular_prism_x(a+2, b-2, -49.8, -45.8, 10.5, 15.5)
        tris += triangular_prism_x(a+2, b-2, 45.8, 49.8, 10.5, 15.5)
    return tris


def mic_pod_segment(x0: float, x1: float, center_x: float = 100.0) -> list[Tri]:
    tris: list[Tri] = []
    inner_len=104.0; inner_w=52.0; outer_w=78.0
    sx0=max(x0+2, center_x-inner_len/2)
    sx1=min(x1-2, center_x+inner_len/2)
    if sx1 <= sx0:
        return tris
    # Low mic bed/open slot: 104 x 52 nominal; raised ribs keep it visually integrated.
    tris += box(sx0, sx1, -inner_w/2, inner_w/2, BASE_T, 4.2)
    # Tall side nacelles with faceted caps for the 50mm-deep oval mic.
    for sign in (-1, 1):
        y_inner=sign*inner_w/2
        y_outer=sign*outer_w/2
        y0=min(y_inner,y_outer); y1=max(y_inner,y_outer)
        tris += box(sx0, sx1, y0, y1, BASE_T, 18.5)
        tris += triangular_prism_x(sx0+3, sx1-3, y0+1, y1-1, 18.5, 34.0)
        # Floating-looking side blade on top of nacelle. Keep it inside y=±40 so it never crosses the y=±47.5 screw rows.
        tris += polygon_prism([(sx0+8, sign*31.5),(sx1-8, sign*31.5),(sx1-20, sign*38.0),(sx0+20, sign*38.0)], 21.0, 29.0)
    # End stops become angular cockpit bulkheads.
    for ex, point_dir in ((center_x-inner_len/2, -1), (center_x+inner_len/2, 1)):
        if x0 <= ex <= x1:
            tris += box(ex-5, ex+5, -inner_w/2, inner_w/2, BASE_T, 18.0)
            tris += polygon_prism([(ex-7,-31),(ex+7,-25),(ex+7,25),(ex-7,31)] if point_dir < 0 else [(ex-7,-25),(ex+7,-31),(ex+7,31),(ex-7,25)], 18.0, 30.0)
    return tris


def armor_panels(kind: str, x0: float, x1: float) -> list[Tri]:
    tris: list[Tri] = []
    if kind == 'front':
        # Arrowhead nose and swept shoulders pointed toward Pip's face.
        tris += polygon_prism([(x0+4,-32),(x0+18,-20),(x0+42,-14),(x0+72,-18),(x1-6,-28),(x1-6,28),(x0+72,18),(x0+42,14),(x0+18,20),(x0+4,32)], BASE_T, 8.8)
        tris += triangular_prism_x(x0+12, x0+56, -9, 9, 8.8, 22.0)
        tris += polygon_prism([(x0+16,-34),(x0+52,-30),(x0+58,-23),(x0+24,-22)], BASE_T, 13.0)
        tris += polygon_prism([(x0+16,34),(x0+52,30),(x0+58,23),(x0+24,22)], BASE_T, 13.0)
        tris += polygon_prism([(x0+60,-30),(x1-10,-34),(x1-16,-24),(x0+66,-22)], BASE_T, 10.8)
        tris += polygon_prism([(x0+60,30),(x1-10,34),(x1-16,24),(x0+66,22)], BASE_T, 10.8)
    else:
        # Rear haunches and cable spine, swept backward.
        tris += polygon_prism([(x0+6,-28),(x0+34,-18),(x0+64,-14),(x1-18,-20),(x1-4,-32),(x1-4,32),(x1-18,20),(x0+64,14),(x0+34,18),(x0+6,28)], BASE_T, 8.8)
        tris += triangular_prism_x(x0+42, x1-12, -9, 9, 8.8, 20.0)
        tris += polygon_prism([(x0+12,-34),(x0+50,-30),(x0+44,-22),(x0+18,-23)], BASE_T, 11.5)
        tris += polygon_prism([(x0+12,34),(x0+50,30),(x0+44,22),(x0+18,23)], BASE_T, 11.5)
        tris += polygon_prism([(x0+58,-23),(x1-18,-32),(x1-8,-24),(x0+64,-17)], BASE_T, 13.0)
        tris += polygon_prism([(x0+58,23),(x1-18,32),(x1-8,24),(x0+64,17)], BASE_T, 13.0)
        # rear cable guide as dorsal fin/tunnel
        tris += box(x0+48, x1-5, -5.0, 5.0, BASE_T, 10.5)
        tris += triangular_prism_x(x0+50, x1-7, -8.5, 8.5, 10.5, 20.0)
    return tris


def seam_crown(kind: str) -> list[Tri]:
    """Visual bridge at x=100. Rear half overhangs slightly over front roof."""
    tris: list[Tri] = []
    if kind == 'front':
        # receiving low bevel at seam
        tris += box(94.0, 100.0, -38.0, 38.0, BASE_T, 6.0)
        tris += triangular_prism_x(90.0, 100.0, -15.0, 15.0, 6.0, 13.0)
    else:
        # overhanging top crown cap: makes halves read as one continuous roof when installed.
        tris += box(96.0, 106.0, -42.0, 42.0, 11.5, 15.0)
        tris += triangular_prism_x(96.0, 106.0, -18.0, 18.0, 15.0, 24.0)
    return tris


def roof_half(kind: str) -> list[Tri]:
    if kind == 'front':
        x0, x1 = 4.0, 100.0
        centers=[(22,-47.5),(22,47.5),(78,-47.5),(78,47.5)]
    else:
        x0, x1 = 100.0, 196.0
        centers=[(122,-47.5),(122,47.5),(178,-47.5),(178,47.5)]
    tris: list[Tri] = []
    tris += base_plate_with_through_hole_keepouts(x0, x1, centers)
    tris += armor_panels(kind, x0, x1)
    tris += edge_fins(x0, x1, centers)
    tris += mic_pod_segment(x0, x1)
    tris += seam_crown(kind)
    tris += screw_collars(centers)
    return tris


def mic_envelope() -> list[Tri]:
    tris: list[Tri] = []
    tris += box(-50,50,-25,25,0,2)
    tris += box(-50,50,-25,-23,0,50)
    tris += box(-50,50,23,25,0,50)
    tris += box(-50,-48,-25,25,0,50)
    tris += box(48,50,-25,25,0,50)
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
        '# Pip shell v10 styled roof kit','',
        'A more deliberate futuristic vehicle roof for the v6 open-top Pip shell. This replaces v9, which was mechanically aligned but still read too flat/bland from top-down.','',
        '## Visual design','',
        '- Chamfered armor-panel top-down silhouette instead of a rectangle.',
        '- Raised dorsal USB mic pod with tall side nacelles for a 100 x 50 x 50 mm mic.',
        '- Swept side fins, diagonal shoulder plates, screw collars, and a central seam crown.',
        '- Rear roof has a slight overhanging seam crown that visually locks over the front roof at x=100.',
        '- Front/rear parts still print separately and bolt to the v6 shell insert hardpoints.','',
        '## Alignment / holes','',
        '- Front roof screw centers: x=22 and 78 mm, y=±47.5 mm.',
        '- Rear roof screw centers: x=122 and 178 mm, y=±47.5 mm.',
        f'- Screw holes are real through-holes with {M3_CLEARANCE:.1f} mm M3 clearance.',
        '- Base plates are segmented around every screw center so no hidden face fills the holes.','',
        '## USB mic','',
        '- Mic cradle is designed around an oval/rounded USB mic about 100 x 50 x 50 mm.',
        '- Use thin Velcro/VHB or glue in the cradle after test fitting.',
        '- Rear half includes a raised cable-guide fin.','',
        '## Print settings','',
        '- Print flat on bed, decorative side up.',
        '- Supports: off first.',
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
        'pip_shell_v10_front_styled_roof.stl': roof_half('front'),
        'pip_shell_v10_rear_styled_roof.stl': roof_half('rear'),
        'pip_shell_v10_usb_mic_100x50x50_envelope.stl': mic_envelope(),
    }
    results=[]
    for name,tris in parts.items():
        _,_,size=bounds(tris)
        results.append((name,size))
        write_stl(OUT/name, name.removesuffix('.stl'), tris)
    doc=readme(results)
    (OUT/'README.md').write_text(doc, encoding='utf-8')
    with ZipFile(ZIP, 'w', ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f'pip_shell_v10_styled_roof/{path.name}')
        zf.write(Path(__file__), arcname='pip_shell_v10_styled_roof/generate_pip_shell_v10_roof_stls.py')
    print(doc)
    print(f'ZIP: {ZIP}')


if __name__ == '__main__':
    main()
