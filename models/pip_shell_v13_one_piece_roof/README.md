# Pip shell v13 one-piece sloped roof

Simple one-piece roof for the v12 printable U shell.

## Fit geometry

- Starts at x=22 mm, leaving the front 22 mm open for turret/sensor clearance.
- Ends at x=190 mm, leaving a 10 mm rear cable/service gap on the v12 U-cowl.
- Width is 96 mm, within the 98 mm v12 shell width and under the 100 mm wheel limit.
- Underside follows the exact shell top slope: z=100+0.15*x.
- Screw holes use all 8 v12 insert centers: x=22/78/122/178, y=±41.5 mm.
- Screw holes are 3.8 mm M3 clearance through-holes.

## USB mic/speaker landing

- Rear raised landing/slot is sized for about 100 x 50 mm oval USB mic/speaker footprint.
- The mic/speaker can be Velcroed or VHB-taped into the raised rails.
- The device's 50-100 mm height/depth is expected to sit above the roof, not inside the roof.

## Printing

- This roof is modeled in final installed orientation, so it appears sloped.
- In Bambu Studio, use Lay on Face on the broad underside/top plane if needed so it prints flat.
- It is about 174 mm long including front screw collars, so it fits A1 Mini better than a full x=200 roof.
- Supports: OFF.
- Brim: optional but recommended for PETG corners.
- PETG clear: 0.20 mm, 3 walls, 10-15% infill, slow/default PETG profile.

## Verified generated bounding boxes

- `pip_shell_v13_one_piece_sloped_roof.stl`: 173.8 x 96.0 x 36.8 mm (OK)
- `pip_shell_v13_usb_mic_100x50_template.stl`: 100.0 x 50.0 x 1.2 mm (OK)
