# Pip shell v3 canopy, Bambu A1 Mini

Closed futuristic canopy shell for Pip/Cleo Rover with an open front face and ~100 mm turret clearance under the roof.
This revision replaces the earlier open exoframe look with a smoother, more finished body: mostly closed side walls, fine vent grilles, roof spine, and rear cable shroud.

## Shape notes

- Overall assembled shell envelope: about 250 L x 108 W x 108 H mm.
- Rover body coverage target: ~200 mm length plus ~50 mm rear cable shroud.
- Front face is open in the middle for camera/ultrasonic/turret line-of-sight.
- Roof is closed over the turret area with about 100 mm internal clearance.
- Side walls use fine horizontal vent grilles, not random large holes.
- Bottom remains open and Velcro-first. Do not screw into the rover chassis yet.

## Insert spec used

- NICECRAFT M3 x 4.6 x 5.7 mm brass heat-set insert.
- Modeled boss pilot: 4.2 mm, depth 6.4 mm.
- PETG clear note: test the coupon first. If 4.0 from the old v2 coupon fits best, regenerate with a smaller pilot before printing shell halves.

## Print order

1. `pip_shell_v3_insert_coupon_4p1_4p2_4p3.stl` if insert fit is still unconfirmed.
2. `pip_shell_v3_front_open_canopy_half.stl`.
3. `pip_shell_v3_rear_cable_canopy_half.stl`.
4. `pip_shell_v3_seam_bridge_pair.stl`.

## Suggested PETG clear settings

- 0.20 mm layer height, 3 walls, 12-18% gyroid/cubic infill.
- Brim recommended on both tall canopy halves.
- Slower PETG profile preferred over high-speed mode for transparency and layer adhesion.
- Supports should be off or organic-only if slicer insists; model is designed around vertical walls and short bridges.

## Verified generated bounding boxes

- `pip_shell_v3_front_open_canopy_half.stl`: 125.0 x 110.4 x 101.4 mm (OK)
- `pip_shell_v3_rear_cable_canopy_half.stl`: 125.0 x 110.4 x 101.4 mm (OK)
- `pip_shell_v3_seam_bridge_pair.stl`: 28.5 x 74.5 x 7.2 mm (OK)
- `pip_shell_v3_insert_coupon_4p1_4p2_4p3.stl`: 72.0 x 20.0 x 6.4 mm (OK)

## Fit checks before long print commitment

- In Bambu Studio, verify the front central face is open and no panel blocks ultrasonic/camera view.
- Check the first 20-30 minutes for PETG brim adhesion and wobble.
- After print, place shell on rover without Velcro first and swing turret left/right manually before powering motors.
- Confirm rear shroud covers cables without pressing on USB/Ethernet/power plugs.
