# Pip shell v4 support-light modular canopy

This replaces v3's one-piece roofed canopy, which needed heavy supports in Bambu Studio.
The shell is now a modular kit: two tall side/body halves plus two flat roof panels that print separately without large support structures.
After assembly, Pip still gets a closed-looking roof over the turret with ~100 mm clearance and an open front face.

## Why this is faster

- The front/rear bodies have no large horizontal roof span, so they should print with supports disabled or minimal tree support only for slicer edge cases.
- Roof panels print flat on the bed as shallow plates.
- PETG clear should have much lower risk than the 14-hour supported v3 front half.

## Assembly

- Attach body halves to Pip with adhesive Velcro on the inner side landings.
- Attach roof panels to the top ledges with thin Velcro, VHB tape, or small dots of CA after fit is confirmed.
- Use seam bridge pair with M3 screws/heat-set inserts only after insert coupon fit is confirmed.

## Print order

1. `pip_shell_v4_front_body_supportless.stl` as the fit test.
2. `pip_shell_v4_front_roof_flat.stl` to check roof clearance/fit.
3. `pip_shell_v4_rear_body_supportless.stl`.
4. `pip_shell_v4_rear_roof_flat.stl`.
5. `pip_shell_v4_seam_bridge_pair.stl` if using inserts.

## Suggested PETG clear settings

- Supports: off first. If Bambu insists, use organic/tree only and paint/block supports away from vent grilles.
- Brim: 5-8 mm on tall body halves.
- 0.20 mm layer height, 3 walls, 12-18% gyroid/cubic infill.
- Slower PETG profile preferred over speed mode.

## Verified bounding boxes

- `pip_shell_v4_front_body_supportless.stl`: 125.0 x 110.0 x 95.4 mm (OK)
- `pip_shell_v4_rear_body_supportless.stl`: 125.0 x 110.0 x 95.4 mm (OK)
- `pip_shell_v4_front_roof_flat.stl`: 125.0 x 100.0 x 8.0 mm (OK)
- `pip_shell_v4_rear_roof_flat.stl`: 125.0 x 100.0 x 13.0 mm (OK)
- `pip_shell_v4_seam_bridge_pair.stl`: 28.5 x 74.5 x 7.2 mm (OK)
- `pip_shell_v4_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)

## Fit checks

- Confirm front face stays open for camera/ultrasonic view.
- Manually swing turret before powering motors.
- Confirm roof panels do not press on sensor stack, camera ribbon, Pi headers, or USB/Ethernet cables.
