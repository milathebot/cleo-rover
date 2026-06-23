# Pip shell v5 roof-down PETG canopy

This is the printability audit revision after the clear PETG grate failure.
It keeps the closed futuristic canopy idea, but removes unsupported vent holes and avoids printing a roof over empty air.

## Dimensions

- Assembled length: 200 mm front-to-back.
- Width: about 110 mm.
- Installed height, shell bottom to roof: 80 mm.
- Front face remains open for turret/camera/ultrasonic view.

## Critical print orientation

Print both body halves ROOF-DOWN, exactly as generated. The large flat roof face goes on the build plate.
After printing, flip the part over and install it on Pip. This makes the roof the first layer instead of an unsupported bridge.

## What changed from v4

- No through-hole side grates: the previous slot/grate bridges sagged in PETG.
- Fine grille details are raised ribs on solid walls, so they have material underneath.
- Height reduced from ~95 mm to 80 mm.
- Length reduced/locked to 200 mm total.
- Rear is mostly closed, with a cable notch/arch instead of a long extension.
- Body is split into two 100 mm halves for A1 Mini reliability.

## Suggested Bambu/PETG clear settings

- Supports: off for the roof-down halves; use support blockers if Bambu tries to fill the interior.
- Brim: 5-8 mm.
- Layer height: 0.20 mm.
- Walls: 3.
- Infill: 10-15% gyroid/cubic.
- Speed: slow PETG profile, not sport/ludicrous. PETG clear likes stable flow.
- Bed: 75-80 C if adhesion allows; glue stick/release agent on PEI if PETG bonds too hard.
- Dry filament if you see bubbling, excessive strings, or cloudy weak layers.

## Print order

1. `pip_shell_v5_front_roofdown_body.stl` as the fit/printability test.
2. `pip_shell_v5_rear_roofdown_body.stl`.
3. `pip_shell_v5_seam_clip_pair.stl` only if useful.
4. `pip_shell_v5_insert_coupon_4p1_4p2_4p3.stl` if insert pilot is still unconfirmed.

## Verified generated bounding boxes

- `pip_shell_v5_front_roofdown_body.stl`: 100.0 x 113.4 x 80.0 mm (OK)
- `pip_shell_v5_rear_roofdown_body.stl`: 100.0 x 113.4 x 80.0 mm (OK)
- `pip_shell_v5_seam_clip_pair.stl`: 25.2 x 71.2 x 3.2 mm (OK)
- `pip_shell_v5_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)
