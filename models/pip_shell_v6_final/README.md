# Pip shell v6 final, support-safe U-shell

This is the finalized correction after v4/v5 printability issues.
The main shell body has NO integrated roof, so it prints faster and avoids roof-cavity supports.
Optional roof skins are separate flat plates that can be printed later and attached with Velcro/VHB after fit is proven.

## Dimensions

- Assembled main body length: 200 mm.
- Body height: 80 mm from lower lip to top ledge.
- Width: about 114 mm including small outer grille/belt details.
- Front face: open center for turret/camera/ultrasonic view.

## Printability choices

- Real grille openings are vertical slots between ribs, not horizontal through-slots.
- Vertical ribs avoid long PETG bridge spans and should join cleanly.
- Top is open on the main body; roof prints as optional separate flat skins.
- Body halves are only 100 mm long each for A1 Mini reliability.

## PETG clear settings

- Supports: off for main body halves. If Bambu adds supports, use support blockers.
- Brim: 5-8 mm on body halves.
- Layer height: 0.20 mm.
- Walls: 3.
- Infill: 10-15% gyroid/cubic.
- Speed: normal/slow PETG, not sport/ludicrous.
- Dry filament if grilles string or bubble.

## Print order

1. `pip_shell_v6_front_u_body_real_grilles.stl` as fit/print test.
2. `pip_shell_v6_rear_u_body_real_grilles.stl`.
3. Optional: `pip_shell_v6_front_roof_skin_flat.stl` and `pip_shell_v6_rear_roof_skin_flat.stl`.
4. Optional: seam clips and insert coupon.

## Verified generated bounding boxes

- `pip_shell_v6_front_u_body_real_grilles.stl`: 100.0 x 112.8 x 80.0 mm (OK)
- `pip_shell_v6_rear_u_body_real_grilles.stl`: 100.0 x 112.8 x 80.0 mm (OK)
- `pip_shell_v6_front_roof_skin_flat.stl`: 100.0 x 94.0 x 5.2 mm (OK)
- `pip_shell_v6_rear_roof_skin_flat.stl`: 100.0 x 94.0 x 5.2 mm (OK)
- `pip_shell_v6_seam_clip_pair.stl`: 25.2 x 71.2 x 3.2 mm (OK)
- `pip_shell_v6_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)
