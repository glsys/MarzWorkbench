# Marz Workbench Changelog

## 0.1.32 (Nov 6th 2026)

- Place the parametric heel cutting plane at the original Gordon generator's world-space origin, rather than copying its identity Shape.Placement.
- Automatically correct legacy unmodified heel planes created at (0,0,0); preserve manually repositioned or resized cutters on normal updates.

## 0.1.31 (Nov 6th 2026)

- Preserve original generated neck profile and guide edges until their poles or source profiles actually change, rather than rebuilding unchanged B-splines on recomputation.
- On an incomplete neck, automatically compare stock and editable curves, Gordon surface, heel plane, blank, headstock and original headstock fusion in the FreeCAD log without modifying edited geometry.

## 0.1.30 (Nov 6th 2026)

- Fix Update Parts crash when assigning a scripted view provider to native Part::Feature cutters. Preserve native FreeCAD view providers and user visibility settings.

## 0.1.29 (Nov 6th 2026)

- Initialize neck construction view providers, restore visibility toggling, and display shape-specific icons without resetting saved manual edits.
- Diagnose the headstock/neck volume intersection and attempt a trimmed-operand union if ordinary fusion fails.

## 0.1.28 (Nov 6th 2026)

- Retry headstock fusion with alternative OCC tolerances and repaired operand copies; reject empty, disconnected or incomplete results.
- Diagnose the combined neck and heel fillet independently; expose the neck assembly status.
- Add `make test` to open the neck test document and capture FreeCAD/terminal logs.

## 0.1.27 (Nov 6th 2026)

- Prevent silent empty-solid results in the editable neck Boolean/fillet pipeline.
- Report per-stage geometry and failures in the FreeCAD Report view; recompute existing necks on Update Parts.

## 0.1.26 (Nov 6th 2026)

- Expose editable neck splines, Gordon surface, cutter plane and solids as linked FreeCAD objects.
- Preserve manual edits during normal recompute; add separate spline and cutter regeneration controls.

## 0.1.16 (Jul 14th 2025)

- Add button to reimport last used svg file

## 0.1.15 (Nov 21th 2024)

- Fix tinted icon colors based on theme

## 0.1.14 (Nov 20th 2024)

- Fix PySide6 issues

## 0.1.13 (Nov 20th 2024)

- Add PySide6 ThreadPool support

## 0.1.12 (Nov 15th 2024)

- Fix #45: Invalid count of widgets

## 0.1.11 (Nov 7th 2024)

- Fix Issue 42: numpy.typing

## 0.1.10 (Nov 3rd 2024)

- Fix dependencies

## 0.1.9 (Nov 1st 2024)

- Removed CurvesWB dependency

## 0.1.8 (Aug 22th 2024)

- Improve neck-headstock transition geometry (Issue #40)

## 0.1.7 (Aug 21th 2024)

- Raise the parameters window on MacOS

## 0.1.6 (Jul 15th 2024)

- Minor ui style change (contrast)

## 0.1.5 (May 12th 2024)

- New Icons, thanks to Turan Furkan TOPAK (https://github.com/Reqrefusion)

## 0.1.4 (May 6th 2024)

- Support older FreeCAD's PySide naming schema

## 0.1.3 (May 6th 2024)

- Added Headless example
- Fixed some cutaway bugs

## 0.1.2 (May 5th 2024)

- Body ergonomic cutaways
- Updated inkscape extension

## 0.1.1 (Apr 30th 2024)

- Some bugfixes
- Added examples
- Added Inkscape extension

## 0.1.0 (Apr 2024)

- Neck
  - Smooth surfaces heel-neck and neck-headstock
  - removed old transition functions stuff
  - String distance at nut is now calculated from nut width
  - Added Heel fillet (rounded corners)
  - Heel offset under Fretboard
  - 2D preview


- Body
  - Neck pocket is now optional, so you can create a custom pocket by hand
  - 2D preview


- Fretboard
  - Added fillet (rounded corners)
  - 2D preview


- GUI
  - FreeCAD's Property editor is now in readonly mode
  - New custom Property editor
  - New import svg ui with preview and validation
  - Imported files are now embedded into the document to keep everything together and can be exported back
  - Grouping all parts in the three
  - Added 2D draft previews to see changes before the heavy 3D generation
  - New toolbar and menu


- Internal
  - Started migration to fcscript apis
  - Started code modernization


- Support
  - Minimum required FreeCAD version is now 0.21.1
  - Added dependency on Curves Workbench 0.6.31+

