# Pip shell v6 open-top PETG cowl

Finalized after print feedback: no roof, smoother sides, and only a small lower RGB/vent strip.
This is intended to print upright with supports off or minimal, in clear PETG on a Bambu A1 Mini.

## Dimensions

- Assembled length: 200 mm front-to-back.
- Width: about 110-114 mm including small exterior details.
- Height: 80 mm from bottom to top rim.
- Open top and open front face for turret/camera/ultrasonic clearance.
- Top side walls include M3 heat-set insert hardpoints for a future bolt-on roof.

## Design changes from failed v4/v5 attempts

- Removed roof entirely to reduce time/supports.
- Removed full-wall grilles.
- Added only one small lower side vent/RGB glow strip per side.
- Lower slots are narrow, vertical, and limited to a short band so PETG bridges are tiny.
- Upper shell is mostly smooth closed wall with a top rim and subtle armor crease.
- Rear is mostly closed with a lower cable-relief opening.

## Suggested PETG clear settings

- Supports: off first. If Bambu insists, use organic/tree only and block supports inside side vents.
- Brim: 5-8 mm on both body halves.
- Layer height: 0.20 mm.
- Walls: 3.
- Infill: 10-15% gyroid/cubic.
- Slow/default PETG profile, not sport/ludicrous.
- Bed: 75-80 C, with release agent if PETG sticks too hard to PEI.
- Dry filament if clear PETG strings/bubbles badly.

## Print order

1. `pip_shell_v6_front_open_top_body.stl` as the fit/clearance test.
2. `pip_shell_v6_rear_open_top_body.stl`.
3. Optional: `pip_shell_v6_seam_clip_pair.stl`.
4. Optional: `pip_shell_v6_insert_coupon_4p1_4p2_4p3.stl`.

## Verified generated bounding boxes

- `pip_shell_v6_front_open_top_body.stl`: 100.0 x 113.2 x 80.0 mm (OK)
- `pip_shell_v6_rear_open_top_body.stl`: 100.0 x 113.2 x 80.0 mm (OK)
- `pip_shell_v6_seam_clip_pair.stl`: 25.2 x 71.2 x 3.2 mm (OK)
- `pip_shell_v6_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)

## Fit checks

- Test front half on Pip before printing rear half.
- Manually swing turret/camera/ultrasonic through full travel with power off.
- Confirm wheels do not rub and Velcro pads sit on flat chassis areas.
- Confirm RGB shines through the lower vent strip without the strip touching wheels.
