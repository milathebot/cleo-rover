# Pip shell v14 integrated one-piece roof

Fixes v13: the screw collars are no longer isolated/floating-looking. Each screw hole is embedded in a broad integrated sloped pad that overlaps the roof plate.

## Fit geometry

- Fits v12 printable U shell.
- Starts at x=20 mm, leaving the front mostly open for turret/sensor clearance.
- Ends at x=190 mm, leaving rear service/cable space.
- Width is 96 mm, inside the 98 mm shell and under the 100 mm wheel limit.
- Underside follows v12 side-wall slope: z=100+0.15*x.
- Uses all 8 v12 insert centers: x=22/78/122/178, y=±41.5 mm.
- Screw holes are 3.8 mm M3 clearance through-holes.

## Printability notes

- One piece, but only about 175 mm long including collars; fits A1 Mini.
- Supports OFF.
- Lay on face in Bambu Studio if needed so it prints flat.
- PETG clear: 0.20 mm, 3 walls, 10-15% infill, slow/default PETG profile.
- Brim recommended if corners lift.

## USB mic/speaker landing

- Rear landing rails fit about a 100 x 50 mm oval USB mic/speaker footprint.
- The 50-100 mm tall/thick device sits above the roof and attaches with Velcro/VHB.

## Verified generated bounding boxes

- `pip_shell_v14_integrated_one_piece_roof.stl`: 174.2 x 96.0 x 37.1 mm (OK)
- `pip_shell_v14_usb_mic_100x50_template.stl`: 100.0 x 50.0 x 1.2 mm (OK)
