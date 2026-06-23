# Pip rover shell final, Bambu A1 Mini

Futuristic velcro-first shell for Pip/Cleo Rover. No display mount in this revision.
The design keeps the front sensor/turret area open, leaves cable/port access at the rear, and uses open side exoskeleton panels for RGB glow and airflow.

## Insert spec used

- NICECRAFT M3 x 4.6 x 5.7 mm knurled brass heat-set insert
- Final bosses use 4.2 mm nominal pilots with 6.4 mm modeled depth.
- Print the coupon first. Use the smallest pilot that melts in cleanly without splitting or bulging the boss.
- If 4.2 mm feels too tight/loose for your filament and iron tip, adjust the source and regenerate before printing the shell.

## Mounting plan

- Shell attaches to rover with adhesive Velcro on the inner side landings. Do not drill into the rover yet.
- Heat-set inserts are for the removable top seam bridges and optional future hardpoints, not for chassis mounting.
- Use M3 x 6 or M3 x 8 screws for seam bridges after confirming insert depth; do not bottom out screws into electronics.

## Print order

1. `pip_m3x4p6x5p7_insert_coupon_final.stl`
2. `pip_shell_front_open_half_final.stl`
3. `pip_shell_rear_half_final.stl`
4. `pip_shell_seam_bridge_pair_final.stl`

## Suggested Bambu A1 Mini settings

- Material: PLA or PETG; PLA easiest for first fit.
- Nozzle: 0.4 mm, layer height 0.20 mm.
- Walls: 3, top/bottom: 4, infill: 12-18% gyroid/cubic.
- Brim: recommended on shell halves.
- Supports: off or organic supports only if slicer flags the raised roof spine. Parts are intended to print upright.

## Verified generated bounding boxes

- `pip_shell_front_open_half_final.stl`: 45.0 x 103.6 x 142.0 mm (OK)
- `pip_shell_rear_half_final.stl`: 100.0 x 103.6 x 142.0 mm (OK)
- `pip_shell_seam_bridge_pair_final.stl`: 26.0 x 72.0 x 7.0 mm (OK)
- `pip_m3x4p6x5p7_insert_coupon_final.stl`: 72.0 x 20.0 x 6.4 mm (OK)

## Fit notes

- Front x=0..55 mm remains open for camera/ultrasonic pan/tilt sweep.
- Rear wall is a frame only, leaving cables and Pi ports reachable.
- Because the shell is velcro-first, final chassis hole positions are intentionally not guessed.
- After first print, check sensor clearance, wheel clearance, cable exit, and heat after 15 minutes powered on.
