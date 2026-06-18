#!/usr/bin/env python3
"""Generate simple printable STL prototypes for the Cleo Rover body shell.

Units are millimetres. The full target envelope is 200 L x 100 W x 140 H.
Because the Bambu Lab A1 Mini build volume is 180 x 180 x 180 mm, the shell is
split into front and rear 100 mm sections, plus a separate rooftop display turret.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

Vec = tuple[float, float, float]
Tri = tuple[Vec, Vec, Vec]

OUT = Path(__file__).resolve().parents[1] / "models" / "shell_v1"


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[Tri]:
    """Axis-aligned rectangular solid as triangles."""
    p000 = (x0, y0, z0); p100 = (x1, y0, z0); p110 = (x1, y1, z0); p010 = (x0, y1, z0)
    p001 = (x0, y0, z1); p101 = (x1, y0, z1); p111 = (x1, y1, z1); p011 = (x0, y1, z1)
    return [
        # bottom
        (p000, p110, p100), (p000, p010, p110),
        # top
        (p001, p101, p111), (p001, p111, p011),
        # front x0
        (p000, p001, p011), (p000, p011, p010),
        # back x1
        (p100, p110, p111), (p100, p111, p101),
        # left y0
        (p000, p100, p101), (p000, p101, p001),
        # right y1
        (p010, p011, p111), (p010, p111, p110),
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


def side_slats(x0: float, x1: float, y_outer: float, inward: int) -> list[Tri]:
    """Ventilated lower side: solid posts/top band plus horizontal light slats."""
    t = 2.4
    y0, y1 = (y_outer - t, y_outer) if inward < 0 else (y_outer, y_outer + t)
    tris: list[Tri] = []
    # end posts and one middle post for stiffness/alignment
    for xa, xb in [(x0, x0+5), ((x0+x1)/2-2.5, (x0+x1)/2+2.5), (x1-5, x1)]:
        tris += box(xa, xb, y0, y1, 4, 138)
    # top solid band and lower rub rail
    tris += box(x0, x1, y0, y1, 106, 138)
    tris += box(x0, x1, y0, y1, 4, 10)
    # lower LED/airflow grille slats
    for z in [18, 30, 42, 54, 66, 78, 90]:
        tris += box(x0, x1, y0, y1, z, z+3.2)
    return tris


def roof(x0: float, x1: float) -> list[Tri]:
    # Thin roof. The separate display turret mounts on top with velcro or drilled/heat-set inserts.
    # Keep the shell itself inside the requested 140 mm height envelope.
    return box(x0, x1, -50, 50, 137.6, 140)


def front_shell() -> list[Tri]:
    # Local part: 0..100 mm corresponds to global rover length 0..100.
    # The first 55 mm is deliberately open for the camera/ultrasonic turret sweep.
    tris: list[Tri] = []
    tris += side_slats(55, 100, -50, inward=1)
    tris += side_slats(55, 100, 47.6, inward=-1)
    tris += roof(70, 100)
    # Alignment tongue/lip at rear edge to mate with rear section.
    tris += box(96, 100, -42, -35, 122, 136)
    tris += box(96, 100, 35, 42, 122, 136)
    return tris


def rear_shell() -> list[Tri]:
    # Local part: 0..100 mm corresponds to global rover length 100..200.
    tris: list[Tri] = []
    tris += side_slats(0, 100, -50, inward=1)
    tris += side_slats(0, 100, 47.6, inward=-1)
    tris += roof(0, 100)
    # Rear wall as frame only, leaving center open for Pi USB/Ethernet/cable access.
    tris += box(97.6, 100, -50, 50, 0, 16)       # bottom rear rail
    tris += box(97.6, 100, -50, 50, 112, 140)    # top rear rail
    tris += box(97.6, 100, -50, -39, 16, 112)    # left rear upright
    tris += box(97.6, 100, 39, 50, 16, 112)      # right rear upright
    # Front alignment sockets/receivers as outer tabs. Drill/heat-set after fit check if desired.
    tris += box(0, 4, -42, -35, 122, 136)
    tris += box(0, 4, 35, 42, 122, 136)
    return tris


def display_turret() -> list[Tri]:
    # Separate upright 2-inch LCD holder for the roof.
    # User measurements: display/module face ~60 x 40 mm, total depth ~17.5 mm.
    # This cradle provides a 64 x 44 x 19.5 mm open-front pocket with a bottom
    # cable notch for jumper wires. Face direction is -X; rear/backbone is +X.
    tris: list[Tri] = []
    # Wide base plate for velcro or later drill/heat-set insert mounting onto shell roof.
    tris += box(0, 46, -42, 42, 0, 3.2)
    # rear backing plate, just behind the 17.5 mm display/backbone stack.
    tris += box(23, 26, -39, 39, 3.2, 64)
    # side rails: inner clear width is 64 mm, enough for a 60 mm module plus tolerance.
    tris += box(4, 26, -39, -32, 6, 61)
    tris += box(4, 26, 32, 39, 6, 61)
    # top retainer, inner clear height is ~44 mm for the 40 mm module plus tolerance.
    tris += box(4, 26, -39, 39, 54, 64)
    # bottom retainer split by a generous center cable notch.
    tris += box(4, 26, -39, -13, 3.2, 10)
    tris += box(4, 26, 13, 39, 3.2, 10)
    # rear cable relief window edges / strain-relief shoulders.
    tris += box(26, 36, -39, -23, 3.2, 22)
    tris += box(26, 36, 23, 39, 3.2, 22)
    # box buttresses from base to display back for stiffness.
    tris += box(4, 23, -38, -32, 3.2, 32)
    tris += box(4, 23, 32, 38, 3.2, 32)
    # low front stop so the module cannot slide out downward.
    tris += box(0, 6, -18, 18, 3.2, 7)
    return tris


def main() -> None:
    files = [
        ("cleo_rover_shell_front_open_half_v1.stl", "cleo_rover_shell_front_open_half_v1", front_shell()),
        ("cleo_rover_shell_rear_half_v1.stl", "cleo_rover_shell_rear_half_v1", rear_shell()),
        ("cleo_rover_display_roof_turret_v1.stl", "cleo_rover_display_roof_turret_v1", display_turret()),
    ]
    for filename, name, tris in files:
        path = OUT / filename
        write_stl(path, name, tris)
        print(path)


if __name__ == "__main__":
    main()
