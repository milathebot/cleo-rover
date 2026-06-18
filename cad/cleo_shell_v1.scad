// Cleo Rover shell v1
// External envelope: 200mm L x 100mm W x 140mm H
// Orientation: X = length, front opening at X=0, back at X=200.
// Y = width, Z = height. Bottom is open.
// Designed for Freenove/Cleo Rover with open front for pan/tilt turret camera + ultrasonic.

$fn = 48;

// --- main dimensions ---
length = 200;
width = 100;
height = 140;
wall = 2.4;
back_wall = 2.8;
top_wall = 2.4;

// Print tuning
clearance = 0.35;
edge_radius = 5;

// Vents
vent_z = 16;
vent_h = 10;
vent_w = 24;
vent_gap = 8;
vent_depth = wall + 1.2;
vent_x0 = 24;
vent_count_side = 5;

// Fasteners
insert_hole_d = 4.2;      // for common M3 heat-set inserts, tune after test print
boss_outer_d = 10;
boss_height = 11;
boss_z = 1.2;

module rounded_box(size=[10,10,10], r=2) {
    // lightweight rounded rectangular prism
    minkowski() {
        cube([size[0]-2*r, size[1]-2*r, size[2]-2*r], center=true);
        sphere(r=r);
    }
}

module outer_shell() {
    translate([length/2, 0, height/2])
        rounded_box([length, width, height], edge_radius);
}

module inner_cavity() {
    // front is open, bottom is open. This hollows everything except side/back/top walls.
    translate([length/2 - wall, 0, height/2 - top_wall])
        cube([length + 4, width - 2*wall, height - top_wall + 4], center=true);
}

module front_opening_cleanup() {
    // full front open area for the turret sweep
    translate([-8, 0, height/2])
        cube([24, width + 20, height + 20], center=true);
}

module bottom_cleanup() {
    // removes rounded bottom lip so shell drops over chassis and does not trap heat
    translate([length/2, 0, -8])
        cube([length + 20, width + 20, 20], center=true);
}

module side_vents(side=1) {
    y = side * (width/2 - wall/2);
    for (i=[0:vent_count_side-1]) {
        x = vent_x0 + i*(vent_w + vent_gap);
        translate([x + vent_w/2, y, vent_z])
            cube([vent_w, vent_depth, vent_h], center=true);
    }
    // second low row, slightly offset for more LED glow without weakening too much
    for (i=[0:vent_count_side-2]) {
        x = vent_x0 + 10 + i*(vent_w + vent_gap);
        translate([x + vent_w/2, y, vent_z + 17])
            cube([vent_w, vent_depth, vent_h], center=true);
    }
}

module back_vents() {
    // rear lower vents, useful for Pi heat exhaust. Keep front fully open.
    for (i=[0:3]) {
        y = -33 + i*22;
        translate([length - back_wall/2, y, vent_z])
            cube([back_wall + 1.2, 14, vent_h], center=true);
        translate([length - back_wall/2, y, vent_z + 17])
            cube([back_wall + 1.2, 14, vent_h], center=true);
    }
}

module top_service_slot() {
    // Small rear top service/cooling slot, away from front turret opening.
    translate([150, 0, height - top_wall/2])
        cube([54, 32, top_wall + 1.0], center=true);
}

module mounting_boss(x, y) {
    difference() {
        translate([x, y, boss_z + boss_height/2])
            cylinder(d=boss_outer_d, h=boss_height, center=true);
        translate([x, y, boss_z + boss_height/2])
            cylinder(d=insert_hole_d, h=boss_height + 2, center=true);
    }
}

module mounting_bosses() {
    // Four internal bosses for M3 heat-set inserts. Screws can come up from chassis plate.
    // Adjust x/y if chassis holes demand it; these are inset from sides and away from turret.
    mounting_boss(36, -36);
    mounting_boss(36,  36);
    mounting_boss(164, -36);
    mounting_boss(164,  36);
}

module side_stiffening_ribs() {
    // Thin internal ribs above vent rows to reduce side panel flex.
    for (side=[-1,1]) {
        y = side * (width/2 - wall - 1.0);
        translate([100, y, 48]) cube([150, 2.0, 4], center=true);
        translate([100, y, 92]) cube([150, 2.0, 4], center=true);
    }
}

module velcro_pad_guides() {
    // Very shallow internal raised outlines showing suggested velcro locations.
    // These are inside the roof, not on the external envelope.
    translate([75, 0, height - top_wall - 0.7]) cube([52, 24, 1.2], center=true);
    translate([145, 0, height - top_wall - 0.7]) cube([52, 24, 1.2], center=true);
}

module cleo_shell() {
    union() {
        difference() {
            outer_shell();
            inner_cavity();
            front_opening_cleanup();
            bottom_cleanup();
            side_vents(1);
            side_vents(-1);
            back_vents();
            top_service_slot();
        }
        mounting_bosses();
        side_stiffening_ribs();
        velcro_pad_guides();
    }
}

cleo_shell();
