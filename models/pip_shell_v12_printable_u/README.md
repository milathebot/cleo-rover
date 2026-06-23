# Pip shell v12 printable U kit

Research-driven redesign after PETG failures. This is intentionally simple: side rails plus rear U-cowl.

## Design rules applied

- Max width is 98 mm, below the 100 mm wheel-clearance limit.
- No unsupported decorative cantilevers or side tabs.
- Heat-set insert hardpoints are plain vertical boss/pillars with 4.2 mm pilot holes.
- Bosses have material around the hole and depth greater than the 5.7 mm insert length.
- Lower RGB vents use short <=6 mm openings and chunky posts.
- No roof, no full-width center/bottom rails over electronics, no support forest.
- Front is open; rear wall is the only cross-wall.

## Assembly shape

- Front left rail + front right rail cover the front sides only.
- Rear U-cowl covers both rear sides and the back.
- Use Velcro on the inside lower ledges/chassis. Do not drill the rover.
- Future roof/seam screw centers: x=22/78/122/178, y=±41.5 mm.
- The seam bridge pair screws across x=78 to x=122, joining each front rail to the rear U-cowl.

## PETG/Bambu settings

- Supports: OFF.
- Brim: 5-8 mm, especially on side rails.
- 0.20 mm layer height, 3 walls, 10-15% gyroid/cubic.
- Use slow/default PETG profile, not sport/ludicrous.
- Dry clear PETG if stringing/bubbling/cloudy weak layers appear.
- Glue/release agent on PEI if PETG sticks too aggressively.

## Print order

1. `pip_shell_v12_front_left_rail.stl` and `pip_shell_v12_front_right_rail.stl` as the width/fit test.
2. `pip_shell_v12_rear_u_cowl.stl` only after front rail clearance is confirmed.
3. Optional seam clip/coupon only if needed.

## Verified generated bounding boxes

- `pip_shell_v12_front_left_rail.stl`: 100.0 x 12.5 x 115.0 mm (OK)
- `pip_shell_v12_front_right_rail.stl`: 100.0 x 12.5 x 115.0 mm (OK)
- `pip_shell_v12_rear_u_cowl.stl`: 100.0 x 98.0 x 130.0 mm (OK)
- `pip_shell_v12_seam_clip_pair.stl`: 68.0 x 97.0 x 3.2 mm (OK)
- `pip_shell_v12_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)
