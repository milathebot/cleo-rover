# Cleo Rover shell v1

Prototype printable body shell for the Freenove/Cleo Rover.

## Target envelope

- Full rover shell envelope: **200 mm L x 100 mm W x 140 mm H**
- Front is intentionally open for the camera + ultrasonic turret sweep.
- Bambu Lab A1 Mini build volume is 180 x 180 x 180 mm, so the 200 mm shell is split into parts.

## Files

- `cleo_rover_shell_front_open_half_v1.stl`
  - Front cheek/roof transition section.
  - Leaves the first ~55 mm open for turret motion.
- `cleo_rover_shell_rear_half_v1.stl`
  - Rear 100 mm shell section with side LED/air vents and rear Pi port opening.
- `cleo_rover_display_roof_turret_v1.stl`
  - Separate rooftop holder for the 2-inch LCD module.
  - Designed around the measured LCD body envelope: ~60 mm x 40 mm face, ~17.5 mm total depth.
  - Provides a loose-fit open-front pocket of about 64 mm x 44 mm x 19.5 mm.
  - Has a bottom-center cable notch and rear cable relief shoulders.
  - Mount it to the roof with velcro first; drill/heat-set only after fit is confirmed.

## Print suggestions, PLA on Bambu A1 Mini

- Material: PLA
- Nozzle: 0.4 mm
- Layer height: 0.20 mm first prototype
- Walls: 3
- Infill: 12-15% gyroid/grid
- Supports: off for shell halves; display turret may need tree supports depending orientation
- Brim: optional, especially for tall shell side walls

## Fit-check order

1. Print the rear half first.
2. Check Pi/heatsink/cable clearance and rear USB/Ethernet access.
3. Print the front open half.
4. Check turret pan clearance at full left/right.
5. Mount the display turret with velcro first before drilling or heat-setting inserts.

## Notes

This is a fit prototype, not the final aesthetic shell. The side lower grille is made from actual slats/gaps so the Freenove RGB LEDs can glow through while also ventilating the Pi area.

The display holder is separate on purpose: it lets you tune the exact roof position after seeing where the cable naturally wants to route.
