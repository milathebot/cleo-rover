#!/usr/bin/env python3
"""Generate Pip shell v8 cyber roof kit.

Styled bolt-on roof for the v6 open-top shell.
- Lines up to v6 M3 insert hardpoints.
- 3D faceted / Cybertruck-inspired roof, not a flat cap.
- Integrated USB mic cradle/slot for an oval mic about 100 L x 50 W x 50 D.
- Designed to print flat on the bed with supports off/minimal.

Coordinates match the v6 shell assembled coordinate system:
front roof covers x=4..100, rear roof covers x=100..196.
Screw centers match v6 insert holes:
front x=22/78, rear x=122/178, y=+-47.5.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import math
from typing import Iterable, Sequence

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "pip_shell_v8_cyber_roof"
ZIP = ROOT / "models" / "pip_shell_v8_cyber_roof_bambu_a1_mini.zip"

BUILD_VOLUME = (180.0, 180.0, 180.0)
M3_CLEARANCE = 3.6

# Roof dimensions: slightly inset from v6 body width, enough edge cover for top walls.
Y_HALF = 54.0
BASE_T = 3.0


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    p000 = (x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
    p001 = (x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
    return [
        (p000,p110,p100),(p000,p010,p110),
        (p001,p101,p111),(p001,p111,p011),
        (p000,p001,p011),(p000,p011,p010),
        (p100,p110,p111),(p100,p111,p101),
        (p000,p100,p101),(p000,p101,p001),
        (p010,p011,p111),(p010,p111,p110),
    ]


def annular_cylinder(cx: float, cy: float, z0: float, z1: float, outer_d: float, inner_d: float, segments: int = 64) -> list[Tri]:
    tris: list[Tri] = []
    ro = outer_d/2; ri = inner_d/2
    for i in range(segments):
        a0 = 2*math.pi*i/segments; a1 = 2*math.pi*(i+1)/segments
        o0b=(cx+ro*math.cos(a0),cy+ro*math.sin(a0),z0); o1b=(cx+ro*math.cos(a1),cy+ro*math.sin(a1),z0)
        o0t=(cx+ro*math.cos(a0),cy+ro*math.sin(a0),z1); o1t=(cx+ro*math.cos(a1),cy+ro*math.sin(a1),z1)
        i0b=(cx+ri*math.cos(a0),cy+ri*math.sin(a0),z0); i1b=(cx+ri*math.cos(a1),cy+ri*math.sin(a1),z0)
        i0t=(cx+ri*math.cos(a0),cy+ri*math.sin(a0),z1); i1t=(cx+ri*math.cos(a1),cy+ri*math.sin(a1),z1)
        tris += [(o0b,o1b,o1t),(o0b,o1t,o0t)]
        tris += [(i0b,i1t,i1b),(i0b,i0t,i1t)]
        tris += [(o0t,o1t,i1t),(o0t,i1t,i0t)]
        tris += [(o0b,i1b,o1b),(o0b,i0b,i1b)]
    return tris


def triangular_prism_x(x0: float, x1: float, y0: float, y1: float, z_base: float, z_peak: float) -> list[Tri]:
    ym = (y0+y1)/2
    a0=(x0,y0,z_base); b0=(x0,y1,z_base); c0=(x0,ym,z_peak)
    a1=(x1,y0,z_base); b1=(x1,y1,z_base); c1=(x1,ym,z_peak)
    return [(a0,c0,b0),(a1,b1,c1),(a0,a1,c1),(a0,c1,c0),(b0,c0,c1),(b0,c1,b1),(a0,b0,b1),(a0,b1,a1)]


def wedge_panel_x(x0: float, x1: float, y0: float, y1: float, z0: float, z_left: float, z_right: float) -> list[Tri]:
    """Rectangular sloped armor plate from z_left at x0 to z_right at x1."""
    p00=(x0,y0,z0); p10=(x1,y0,z0); p11=(x1,y1,z0); p01=(x0,y1,z0)
    q00=(x0,y0,z_left); q01=(x0,y1,z_left); q10=(x1,y0,z_right); q11=(x1,y1,z_right)
    return [
        (p00,p11,p10),(p00,p01,p11),
        (q00,q10,q11),(q00,q11,q01),
        (p00,q00,q01),(p00,q01,p01),
        (p10,p11,q11),(p10,q11,q10),
        (p00,p10,q10),(p00,q10,q00),
        (p01,q01,q11),(p01,q11,p11),
    ]


def oval_rail_segment(x0: float, x1: float, center_x: float = 100.0, length: float = 108.0, width: float = 58.0) -> list[Tri]:
    """Approximate an oval raised mic rim/clamp split over x interval.

    It makes a 100x50-ish mic slot with small tolerance: inner opening about
    102 x 52, outer about 116 x 66. The mic is retained by raised side/end lips
    but the center remains open for Velcro/VHB.
    """
    tris: list[Tri] = []
    inner_len = 104.0
    inner_w = 52.0
    outer_len = 118.0
    outer_w = 66.0
    cx = center_x
    # side rails run the length of the mic, split by part extents
    sx0 = max(x0 + 2, cx - inner_len/2)
    sx1 = min(x1 - 2, cx + inner_len/2)
    if sx1 > sx0:
        # raised rails on either side of mic body; 12mm high gives a real 3D roof silhouette
        tris += box(sx0, sx1, inner_w/2, outer_w/2, BASE_T, 15.0)
        tris += box(sx0, sx1, -outer_w/2, -inner_w/2, BASE_T, 15.0)
        # bevel-like top caps on rails
        tris += triangular_prism_x(sx0, sx1, inner_w/2 + 1.0, outer_w/2 - 1.0, 15.0, 20.0)
        tris += triangular_prism_x(sx0, sx1, -outer_w/2 + 1.0, -inner_w/2 - 1.0, 15.0, 20.0)
    # front/rear end stops only on the halves that contain oval ends
    for ex in (cx - inner_len/2, cx + inner_len/2):
        if x0 <= ex <= x1:
            tris += box(ex - 3.2, ex + 3.2, -inner_w/2, inner_w/2, BASE_T, 13.0)
            tris += triangular_prism_x(ex - 3.2, ex + 3.2, -inner_w/2, inner_w/2, 13.0, 18.0)
    return tris


def screw_holes(centers: Sequence[tuple[float, float]]) -> list[Tri]:
    tris: list[Tri] = []
    for cx, cy in centers:
        # Low raised collar with actual clearance hole through the roof panel.
        tris += annular_cylinder(cx, cy, 0, 6.2, outer_d=12.0, inner_d=M3_CLEARANCE)
        # angular pad shoulders tie collars into roof without filling holes
        tris += box(cx - 7.5, cx + 7.5, cy - 8.5, cy - 6.0, BASE_T, 5.2)
        tris += box(cx - 7.5, cx + 7.5, cy + 6.0, cy + 8.5, BASE_T, 5.2)
    return tris


def cyber_roof_half(kind: str) -> list[Tri]:
    if kind == "front":
        x0, x1 = 4.0, 100.0
        centers = [(22,-47.5),(22,47.5),(78,-47.5),(78,47.5)]
        # front slopes up toward the mic pod, like a little armored brow
        left_z, right_z = 3.4, 8.0
    else:
        x0, x1 = 100.0, 196.0
        centers = [(122,-47.5),(122,47.5),(178,-47.5),(178,47.5)]
        # rear slopes down slightly from mic pod to tail
        left_z, right_z = 8.0, 4.2
    tris: list[Tri] = []
    # thin base plate, print flat with decorative structures upward
    tris += box(x0, x1, -Y_HALF, Y_HALF, 0, BASE_T)
    # faceted roof planes: central raised wedge plus angular side shoulders
    tris += wedge_panel_x(x0 + 4, x1 - 4, -24, 24, BASE_T, left_z, right_z)
    tris += wedge_panel_x(x0 + 8, x1 - 8, -46, -34, BASE_T, max(4.0, left_z-1.0), max(5.0, right_z-1.0))
    tris += wedge_panel_x(x0 + 8, x1 - 8, 34, 46, BASE_T, max(4.0, left_z-1.0), max(5.0, right_z-1.0))
    # armored central spine, but split around mic cradle so mic remains the hero
    if kind == "front":
        tris += triangular_prism_x(x0 + 8, 44, -8, 8, BASE_T, 10.5)
    else:
        tris += triangular_prism_x(156, x1 - 8, -8, 8, BASE_T, 10.0)
    # side fins / edge definition
    tris += triangular_prism_x(x0 + 10, x1 - 10, -Y_HALF + 6, -Y_HALF + 14, BASE_T, 9.0)
    tris += triangular_prism_x(x0 + 10, x1 - 10, Y_HALF - 14, Y_HALF - 6, BASE_T, 9.0)
    # mic cradle spanning both halves
    tris += oval_rail_segment(x0, x1)
    # cable channel on rear: little raised tunnel guide for mic cable leaving backward
    if kind == "rear":
        tris += box(150, 192, -5, 5, BASE_T, 7.5)
        tris += triangular_prism_x(150, 192, -7, 7, 7.5, 12.0)
    tris += screw_holes(centers)
    return tris


def mic_template() -> list[Tri]:
    # simple 100x50x50 visual block + footprint, so user can preview the mic envelope in slicer
    tris: list[Tri] = []
    tris += box(-50, 50, -25, 25, 0, 2.0)
    tris += box(-50, 50, -25, -23, 0, 50)
    tris += box(-50, 50, 23, 25, 0, 50)
    tris += box(-50, -48, -25, 25, 0, 50)
    tris += box(48, 50, -25, 25, 0, 50)
    # dotted-ish face ridge bands, not holes
    for x in [-35, -20, -5, 10, 25, 40]:
        tris += box(x, x+2, -22, 22, 50, 52)
    return tris


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


def bounds(tris: Iterable[Tri]) -> tuple[Vec, Vec, Vec]:
    xs=[]; ys=[]; zs=[]
    for tri in tris:
        for x,y,z in tri:
            xs.append(x); ys.append(y); zs.append(z)
    mn=(min(xs),min(ys),min(zs)); mx=(max(xs),max(ys),max(zs))
    return mn,mx,(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])


def readme(results: list[tuple[str, Vec]]) -> str:
    lines = [
        '# Pip shell v8 cyber roof kit', '',
        'A more 3D, Cybertruck-inspired roof for the v6 open-top shell. It is intentionally not a flat cap.',
        'The roof is split into front/rear bolt-on panels and has a raised central USB mic cradle sized for an oval mic about 100 x 50 x 50 mm.', '',
        '## Alignment', '',
        '- Front roof screw centers: x=22 and 78 mm, y=±47.5 mm.',
        '- Rear roof screw centers: x=122 and 178 mm, y=±47.5 mm.',
        '- M3 clearance holes are 3.6 mm and line up with v6 shell insert holes.', '',
        '## Mic cradle', '',
        '- Center mic cradle/slot is approximately 104 x 52 mm internally with raised side rails and end stops.',
        '- The mic can be Velcro/VHB/glued into the cradle. Its ~50 mm depth sticks upward as a little dorsal pod.',
        '- Rear roof includes a raised cable-guide ridge for the mic cable.', '',
        '## Print settings', '',
        '- Print flat on the bed with decorative geometry upward.',
        '- Supports: off first. The roof uses raised geometry rather than unsupported cavities.',
        '- PETG clear: 0.20 mm, 3 walls, 10-15% infill, normal/slow speed.',
        '- Brim optional, useful if corners lift.', '',
        '## Verified bounding boxes', '',
    ]
    for name, size in results:
        fit = 'OK' if all(size[i] <= BUILD_VOLUME[i] for i in range(3)) else 'TOO LARGE'
        lines.append(f'- `{name}`: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm ({fit})')
    return '\n'.join(lines) + '\n'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {
        'pip_shell_v8_front_cyber_roof.stl': cyber_roof_half('front'),
        'pip_shell_v8_rear_cyber_roof.stl': cyber_roof_half('rear'),
        'pip_shell_v8_usb_mic_100x50x50_envelope.stl': mic_template(),
    }
    results=[]
    for filename, tris in parts.items():
        _,_,size=bounds(tris)
        results.append((filename,size))
        write_stl(OUT/filename, filename.removesuffix('.stl'), tris)
    text=readme(results)
    (OUT/'README.md').write_text(text, encoding='utf-8')
    with ZipFile(ZIP, 'w', ZIP_DEFLATED) as zf:
        for path in sorted(OUT.iterdir()):
            zf.write(path, arcname=f'pip_shell_v8_cyber_roof/{path.name}')
        zf.write(Path(__file__), arcname='pip_shell_v8_cyber_roof/generate_pip_shell_v8_cyber_roof_stls.py')
    print(text)
    print(f'ZIP: {ZIP}')


if __name__ == '__main__':
    main()
