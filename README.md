# Marz Guitar Design Workbench

## What is Marz Guitar Design Workbench

This is a custom FreeCAD Workbench for Electric Guitar/Bass Parametric Design. It allows you to create Fretboards,
Necks, Nuts, ... based on a common set of parameters.

|![Body](https://github.com/mnesarco/MarzWorkbench/raw/master/docs/wiki/custom-svg-body-doc.svg)|![Headstock](https://github.com/mnesarco/MarzWorkbench/raw/master/docs/wiki/custom-svg-headstock-doc.svg)|
|---|---|

![Workbench](https://github.com/mnesarco/MarzWorkbench/raw/master/docs/images/screenshot.png)

## Features

This is a work in progress project, this is the list of the currently implemented features. They are working but need more testing.

* Fretboard
  * Compound Radius
  * Multi Scale
  * Zero Fret
  * Perpendicular Fret setting
  * Fret nipping
  * Margins
  * Thickness
  * String distance
  * Customizable Fret Wire (for accurate slots)
  * Custom Inlays
  * Corner fillet

* Neck
  * Neck Profiles
  * Thickness (start-end)
  * Smooth transitions to Headstock and Heel
  * Set-In, Bolt-On, Through Join
  * Tenon
  * Neck break angle
  * Top offset
  * Truss-Rod Channel
  * Heel fillet
  * Automatic positioning based on imported bridge reference

* Headstock
  * Dimensions
  * Transition
  * Volute
  * Flat/Angled
  * Custom shape
  * Pockets/Holes

* Bridge
  * String distance
  * Compensation

* Nut
  * Dimensions
  * Position

* Body
  * Top/Back Dimensions
  * Neck pocket
  * Custom Shape
  * Pockets/Holes


### Editing a generated neck

The first **Update Parts** creates a persistent FreeCAD construction tree under
**Generated parts → Neck construction**. The Profiles and Guides contain
individual B-spline objects whose **Poles** can be edited in FreeCAD's property
editor (XYZ coordinates); the Gordon surface also exposes its U-major **Poles**
control net for direct editing. Its `UPoles`/`VPoles` properties give the grid
dimensions. Setting a surface pole switches **Manual** on, so normal recompute
does not replace that edit. Change `Manual` to `False` to resume deriving the
surface from its curves.

Moving an input profile updates its automatically following guides, the Gordon
surface, the trimmed blank and the finished neck through standard FreeCAD
**Recompute**. Editing a guide's poles disables its **FollowProfiles** option,
keeping it independent. Independently edited guides and profiles must still
form a geometrically compatible Gordon curve network.

The **Cutting tools** group contains the editable **Heel cutting plane**
(native `Part::Plane`), headstock plate, volute and top cutters, optional
headstock pocket cutter, and truss-rod channel. The finished neck is linked
to these tools. Editing a tool and recomputing updates the result without
rebuilding construction splines.

The Neck tab offers two explicit commands: **Regenerate Neck Splines** replaces
edited profile/guide curves with curves generated from current Marz parameters
(and resumes automatic Gordon surface generation), but leaves cutters alone;
**Regenerate Neck Cutters** regenerates the tools from current parameters but
leaves all spline and surface edits alone. **Update Parts** does neither, so
editing the rest of the guitar does not overwrite custom neck construction.
The editable spline poles are initially exposed as property values rather than
interactive scene drag handles.
Profiles, guides, the Gordon surface and the blank use dedicated FreeCAD
view providers and type-specific icons. Their visibility is user-controlled;
construction shapes start hidden, but can be shown normally with the eye icon.
Previously saved neck objects acquire the view providers on **Update Parts**
without resetting their visibility or edited geometry.


The **Neck** object's **Diagnostics → BuildStatus** reports `OK` or `INCOMPLETE`
when an operation could not be completed. The headstock fusion retries with
smaller fuzzy tolerances and copies repaired by OCC; only a single valid solid
containing both original parts is accepted. Heel filleting is attempted only
after successful fusion, and never silently changes the requested radius.

The neck debug log also reports the blank/headstock common volume: a
zero-distance result alone does not establish that two solids actually
intersect. After ordinary fuse attempts, the assembler can try to remove
shared volume from one operand before fusing, while still rejecting an
incomplete result. An unsuccessful union remains `INCOMPLETE`.

Run `make test` to launch `/home/glsys/Nextcloud/guitar/marztest.FCStd`
with logs in `/tmp/freecad.log` and `/tmp/freecad-terminal.log`.

The **Neck** object's **Diagnostics → Debug** property controls geometry-stage
messages in FreeCAD's **Report view** (enabled by default). Each stage reports
its faces, solid count, volume and bounding box. If an OCC cut, fillet or
refinement returns no solid, a warning identifies the failed operation and
the previous valid shape is retained so the neck does not disappear. Such a
result may be incomplete (for example, missing a failed cut); inspect the
warning before using it for fabrication. **Update Parts** forces the neck to
recompute without replacing manually edited splines or cutting tools.

### Planned Features

* Nut
  * 3D Object

* Neck
  * Custom profile editor

* Body
  * Armrest
  * Belly cut
  * Carved top

* Binding
  * Fretboard binding
  * Body binding

## Documentation

The Wiki contains some useful documents: [Wiki](https://github.com/mnesarco/MarzWorkbench/wiki)


![ui](https://github.com/mnesarco/MarzWorkbench/raw/master/docs/images/ui-elements.png)


## Requirements

* FreeCAD v0.21+ ([releases](https://github.com/FreeCAD/FreeCAD/releases/))

## Install

The recommended way to install this workbench is through the FreeCAD [Addon Manager](https://wiki.freecad.org/Std_AddonMgr).


## Bugs

If you find problems, please report the issue here in Github.

## Background

I initially made a web based Marz Designer, it is still active at: https://marzguitars.com/marz-designer/
and it is very practical for quick calculations and references, but it is 2D and lacks some features like ZeroFret support.

I decided to go to the next level and make it 3D, so I started this project and work on this in my
free time. This is a work in progress thing.

## Contributors

### Icons

Icons redesign by Turan Furkan TOPAK (https://github.com/Reqrefusion)
### Editable SVG reference sketches (first pilot)

In the Guitar menu, **Create editable SVG sketches** converts already imported body and
headstock contours, the headstock transition, and the body bridge reference
into native Sketcher objects. Explicit **Import/Re-Import** of body/headstock
SVGs also generates them automatically. Find them in **Imported objects →
Editable SVG sketches**. Show a sketch using the eye icon, then double-click
it to edit its curves with Sketcher. The original imported wire is kept hidden
as a reference/fallback.

Conversion uses FreeCAD Draft's `make_sketch` and checks every segment's
geometry, closure, total length and world placement against the imported wire.
Bezier-to-B-spline conversion and harmless edge reversal/reordering are accepted
when geometry is equivalent. If the converted shape differs, Marz reports the
specific discrepancy under `[Marz SVG]` and uses the original
wire rather than silently substituting a different outline. Running the menu
command again does **not** overwrite manually edited sketches. Re-importing an
SVG intentionally removes and replaces its sketches. Editing a sketch does not
change the embedded source SVG.

For this pilot, run Marz **Update Parts** to rebuild the body or neck/headstock
after editing a sketch. FreeCAD's normal Recompute updates the sketch, but the
finished assemblies are **not yet** entirely native linked features. Pockets,
inlays and ergonomic cutaways are not converted in this pilot.
