# Cleo Rover Shell v1

Parametric first shell for the current Cleo Rover body.

## Dimensions

- External length: **200 mm**
- External width: **100 mm**
- External height: **140 mm**
- Front: **fully open** for the pan/tilt turret, camera, and ultrasonic sensor sweep
- Bottom: open, shell drops over existing chassis/body
- Walls: 2.4 mm nominal
- Rear wall: 2.8 mm nominal

## Features

- Lower side vents on both sides for LED glow and Pi cooling
- Lower rear vents for heat exhaust
- Open front with no crossbar so the turret can pan freely
- Four internal M3 heat-set insert bosses
- Internal roof velcro guide pads
- Internal side stiffening ribs above vent rows

## Files

- `cleo_shell_v1.scad` - source CAD

## Suggested print settings

- Material: PETG preferred, PLA okay for first fit check
- Nozzle: 0.4 mm
- Layer height: 0.20 mm
- Walls/perimeters: 4
- Top/bottom layers: 5
- Infill: 15-20% gyroid or grid
- Supports: likely only for the top service slot and some vent bridges depending on slicer; try organic/tree supports from build plate only
- Orientation: print upright, open bottom on the bed, open front facing forward

## Fit-check order

1. Print a low-quality draft first if possible.
2. Test that the shell drops over the rover without touching turret/camera/ultrasonic.
3. Verify the turret can sweep left/right without hitting the front edges.
4. Check that LEDs glow through the lower vents.
5. Check Pi thermals after 10-15 minutes powered on.
6. Only then install heat-set inserts.

## Heat-set notes

- Boss hole diameter is currently **4.2 mm** for common M3 heat-set inserts.
- If your inserts are smaller/larger, edit `insert_hole_d` in `cleo_shell_v1.scad`.
- Bosses are internal at approximate coordinates:
  - X 36 / 164 mm
  - Y +/-36 mm

## Known assumptions

- The exact wheel/chassis mounting hole positions were not measured yet, so bosses are starting points.
- The front is fully open because the turret/camera/ultrasonic needs clearance.
- The shell is a protective/expression cover, not a structural roll cage.
