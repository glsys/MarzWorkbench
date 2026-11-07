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


### Regenerating individual guitar parts

The Guitar Parameters editor has a **Regenerate:** row with **Body Top**,
**Body Back**, **Neck**, **Headstock**, and **Fretboard** buttons. Each button
uses the current Marz parameter values and overwrites only that component's
generated geometry. **Body Top** and **Body Back** are separate outputs; the
unselected half's FreeCAD shape is not replaced. The body generator currently
calculates both halves internally because they share cutting operations.

**Neck** resets its profiles, guides, Gordon surface, heel plane, truss rod,
and heel-fillet parameter, but leaves the headstock solid and headstock cutters
alone. **Headstock** regenerates its plate, top cutter, volute cutter, and
pocket cutter, while keeping the neck curves, heel plane, and truss rod.
Its updated geometry is then used by the finished neck assembly. **Fretboard**
replaces only the generated fretboard shape.

These buttons do not reimport SVG files or replace edited SVG Sketcher source
objects. Normal FreeCAD **Recompute** updates linked geometry without
regenerating these sources. The existing **Update Parts** button is unchanged;
it updates the whole guitar but continues to preserve existing edited neck
construction unless an explicit regeneration button is used. The individual
body and fretboard outputs are still legacy finished shapes: converting those
parts to native, editable construction histories remains on the `todo.md` list.

### Editable SVG pocket sketches (pilot)

Reimporting the **Body SVG** or **Headstock SVG** now creates an additional
Sketcher object under **Imported objects → Editable SVG sketches**:
**Body pockets (edit in Sketcher)** or **Headstock pockets (edit in Sketcher)**.
Each collects all pocket/hole outlines recognized in that SVG, with each
original SVG pocket ID, start depth, cutting depth and top/back target saved
in the sketch's `SVGElementMap` JSON property. Circles are retained as native
Sketcher circles where the imported outline is circular to within 0.01 mm;
other supported closed contours are editable B-splines.

**Update Parts**, **Regenerate Body Top/Back** and **Regenerate Headstock/Neck**
rebuild the legacy cutter solids from edited pocket sketch geometry. If a
profile is open or invalid, the previous cutters remain unchanged and the
Report view identifies the failing SVG ID. These are still legacy output
shapes, not native PartDesign Pocket features. Explicit SVG reimport replaces
edited sketches; simply updating parts does not reimport them. For existing projects, **Guitar → Create editable SVG sketches** also
creates any missing pocket sketches from the SVG files embedded in the
FreeCAD document. This does not reimport the guitar, replace its imported
wires, or overwrite any existing edited sketches. An explicit SVG reimport
still replaces that SVG's sketches.

**Pocket start/end and target editor (0.1.48):** With a pocket sketch present,
choose **Guitar → Edit pocket properties**. The dock remains available while
editing the sketch in Sketcher. Choose Body or Headstock, then select an SVG ID
in the list; selecting a row attempts to highlight its corresponding sketch
geometry. Change **Start depth**, **End depth**, and (for body pockets) **Cut
target** (Both, Top, Back), then click **Apply pocket properties**. End depth is
shown as `start + cutting depth`; the stored `SVGElementMap` still uses `start`
and `depth` so existing cutter generation reads the edited values. The SVG ID
and geometry indices are never rewritten. The editor rebuilds the existing
legacy pocket cutters immediately and rolls back the metadata if any profile
is invalid or the rebuild fails. **Update Parts** is still required to rebuild
the final body/neck solids: those shapes do not yet have native FreeCAD
parametric links. Changes survive document save/reopen; SVG reimport replaces
the pocket sketch and its edited metadata.

This is an intermediate step: body/headstock each still have separate
contour/reference sketches in addition to their pocket sketch. The eventual
**one complete sketch per SVG** and direct native SVG primitive import remain
open tasks.

FreeCAD 1.1.4's **B-spline curvature comb** is disabled once when Marz first
creates editable SVG sketches. The user can turn it back on from Sketcher's
visual tools; subsequent imports do not reset that preference.

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

For **body and headstock contours**, the imported SVG's connected cubic
Bezier segments and straight segments are reconstructed **as one closed,
multi-span cubic B-spline per contour**, directly from the original poles.
Every original segment boundary is an internal knot: the curve stays connected
when edited, without introducing separate splines, per-segment coincidence
constraints, or the 0.22–0.24 mm drift seen with Draft conversion. Original straight
segments remain mathematically straight. Internal knots have multiplicity 3
(C0), preserving original sharp corners and the exact SVG path geometry;
independent tangent/curvature smoothing across knots is not added automatically.
The first and last poles form a non-periodic seam, now joined by a native
Sketcher `Coincident` constraint during creation (0.1.45), so the contour
remains closed after dragging. The importer also calls
`exposeInternalGeometry()` on that spline, creating the native pole/knot
helpers needed to edit **interior poles** graphically. In Sketcher edit mode,
select the B-spline and enable **Show/hide B-spline control polygon** in the
Sketcher visual helpers if the polygon is hidden. Sketcher's
**Show/hide internal geometry** (`Z`, `I`) can recreate helpers for older
sketches, but it does not add the missing seam constraint: explicitly reimport
the SVG to get both automatically. Helper objects are not mapped as SVG
source elements in `SVGElementMap`.
If the contour cannot be
represented exactly by this construction, Marz retains the imported SVG source
and reports the error rather than approximating it.

The **bridge reference and headstock transition** still use Draft conversion;
for these, any shared endpoints are constrained at initial sketch creation.
All conversions are validated in world space for closure, length, position,
and curve deviation, with the user-approved 0.5 mm maximum. Joined contours
are compared geometrically rather than rejecting their intentional reduction
from many edges to one. An existing manually edited sketch is never
reconstructed by the menu command; explicitly re-importing its SVG rebuilds
it and discards the old sketch edits.
If the converted shape differs, Marz reports the specific discrepancy under `[Marz SVG]` and uses the original
wire rather than silently substituting a different outline. A rejected
conversion is **kept** under **Editable SVG sketches**, with a visible sketch
labelled `(conversion mismatch)`. Select it to inspect its **Marz SVG →
SVGConversionError** property, or double-click it to inspect/edit its curves.
Its persistent **SVGConversionValid = false** flag prevents the sketch from
being used to build the guitar; the imported SVG wire remains the source.
Running the menu command again does **not** overwrite manually edited or
rejected sketches. Re-importing an SVG intentionally removes and replaces its
sketches. Editing a sketch does not change the embedded source SVG.

For this pilot, run Marz **Update Parts** to rebuild the body or neck/headstock
after editing a sketch. FreeCAD's normal Recompute updates the sketch, but the
finished assemblies are **not yet** entirely native linked features. Pockets,
inlays and ergonomic cutaways are not converted in this pilot.


#### Comparing a rejected SVG sketch (0.1.39)

Select **Guitar → Create editable SVG sketches** again. For rejected conversions,
Marz shows **both** the original imported reference (red) and its Sketcher
conversion (green), at their actual world coordinates. The Report view logs
`[Marz SVG] Overlay` with the center offset, so an apparent translation can be
distinguished from a changed curve. The comparison is between imported SVG
geometry and Sketcher geometry, **not** the final extruded guitar. Repeating the
command never overwrites a preexisting sketch. If the mismatch is *only* a
rigid translation, new conversions correct the placement and accept the sketch
**only if** every curve, closure and dimension then matches; otherwise the
rejected geometry is left unchanged for inspection.

The current four pilot sketches carry **Marz SVG → SVGSourceName**,
**SVGSourceDocument** and **SVGElementMap**. The latter is JSON mapping the
original element ID (`contour`, `bridge` or `transition`) to Sketcher geometry
indices. This is **not yet** the target single-sketch-per-SVG importer: pockets,
holes, circles, inlays and their depth/target semantics still require direct
SVG parsing and full per-element mapping. Editing or deleting Sketcher geometry
may invalidate saved indices; those indices are not yet maintained through edits.


#### SVG conversion tolerance (0.1.40)

The Sketcher pilot accepts up to **0.5 mm** geometric difference from its
imported SVG reference, as requested for visual inspection and refinement.
The validator still checks edge count, closed/open topology, total length,
world-space bounds, and one-to-one sampled curve deviations. An actual
rigid offset is corrected only if the *strict* 0.0001 mm check proves full
shape equivalence; accepting small non-rigid differences does not recenter
the sketch. The original SVG remains stored as a reference.

For sketches previously labelled `(conversion mismatch)`, run
**Guitar → Create editable SVG sketches** again: the existing sketch is
revalidated in place (no overwrite), accepted if it meets the 0.5 mm limit,
and used as the model source after **Update Parts**. Larger mismatches remain
visible with their conversion error and the original SVG stays the model
source. The threshold is a user-approved allowance, not proof of exact SVG
geometry; a future direct SVG-to-Sketch importer should preserve primitives
and element IDs independently of this tolerance.
