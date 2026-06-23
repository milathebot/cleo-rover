# Pip shell v11 simple U-cowl

Hard simplification after the real PETG shell print was too wide and fragile.
This version prioritizes fit and successful printing over styling complexity.

## Geometry

- Max outer width: 98 mm, below the 100 mm hard limit before the wheels.
- Total length: 200 mm, split into 100 mm front and rear halves.
- Height slopes from 100 mm at the front to 130 mm at the rear.
- True U shape: left wall, right wall, rear wall only. Front and center are open.
- No bottom crossbars across the Pi/servo/electronics area.
- Small lower side RGB/vent strip only, with robust vertical posts.
- Top hardpoints use true 4.2 mm heat-set insert pilot holes for a future roof.

## Print settings for clear PETG

- Supports: OFF first. This design should not need the support forest that broke v6.
- Brim: 5-8 mm.
- Layer height: 0.20 mm.
- Walls: 3.
- Infill: 10-15% gyroid/cubic.
- Slow/default PETG profile, not sport/ludicrous.
- Dry filament if you see bubbling, clouding, or heavy strings.

## Print order

1. `pip_shell_v11_front_simple_u_half.stl` as the fit test.
2. `pip_shell_v11_rear_simple_u_half.stl` if front width/clearance are good.
3. Optional: `pip_shell_v11_seam_clip_pair.stl`.
4. Optional: insert coupon if you still need pilot confirmation.

## Verified bounding boxes

- `pip_shell_v11_front_simple_u_half.stl`: 100.0 x 98.0 x 118.7 mm (OK)
- `pip_shell_v11_rear_simple_u_half.stl`: 100.0 x 98.0 x 133.7 mm (OK)
- `pip_shell_v11_seam_clip_pair.stl`: 25.0 x 92.0 x 3.2 mm (OK)
- `pip_shell_v11_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)

## Fit checklist

- Confirm outer width clears wheels before printing rear half.
- Confirm front sensor/turret/camera face is unobstructed.
- Confirm lower vent strip is above wheel rub line.
- Confirm no shell wall presses on Pi, GPIO, camera ribbon, or servo wires.
