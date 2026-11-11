## 0.2.52 (Nov 11th 2026)

- Fix fretboard regeneration after the shared Inlay-import migration by importing `FRET_INLAY_SKETCH_PREFIX` in the regeneration scope that uses it. This removes the `NameError` raised after a successful Inlay import when Generate Parts rebuilds inlay cutters.

## 0.2.51 (Nov 11th 2026)

- Migrate Fretboard Inlay recognition to the shared semantic parser. Individually tagged SVG elements now group by parsed fret/X/Y placement semantics regardless of descriptive suffixes; authored `inkscape:label` fallback is active in production; malformed semantic modifiers are reported without inventing errors for unrelated SVG geometry; and tagged SVG `<g>` elements can own supported closed descendants while remaining distinct from another same-position tagged group. The supplied Inlay fixture now imports all 11 semantic inlays, including the label-only `f13_x0a2p0_y1s2p5_part2`.
- Create one editable Sketcher source per logical inlay through the verified shared SVG reader/native-Sketch adapter, preserving native circles/ellipses/lines/curves and source-topology Coincident joins. Keep the historical `Marz_FInlay_FretN` object as a centered per-fret compatibility aggregate, and allow multiple same-fret logical sketches/cutters without changing their current midpoint placement; X/Y placement remains the next migration stage. Persist semantic/source metadata in each sketch and emit logical-group diagnostics during import. 118 focused tests plus 14 subtests pass; the full suite still has the same 33 unrelated Body/component mock-package failures. Real FreeCAD import/sketch/cutter integration remains to be runtime-verified.

## 0.2.50 (Nov 11th 2026)

- Switch the Neck and Inlay SVG import-result tables to their planned semantic columns. Neck now shows `Reference / Validation / Fret`; Inlay shows `Reference / Validation / Fret / X / Y`. Remove Type/Start/Depth from only those two tables, keep Body and Headstock tables unchanged, and normalize older embedded `Fret<N> Found` statuses when reopening documents.
- Populate Neck table metadata through the shared semantic parser, including authored `inkscape:label` fallback and fractional positions such as `f10p25` -> `10.25`. Keep the current Inlay production-recognition path unchanged while using shared semantics for displayed Fret/X/Y values, including centered defaults `0.5` and compact signed offsets such as `0+2` / `1-2.5`. Actual Inlay recognition/placement migration remains the next task.

## 0.2.49 (Nov 11th 2026)

- Add one FreeCAD-independent Marz SVG semantic parser, kept separate from the generic SVG geometry reader. It implements ID-first / label-fallback resolution, fractional Neck fret positions, Inlay X/Y alignment plus signed-mm offsets, arbitrary suffix tokens, the compact legacy `D13X0.25+2Y1.0-2.5` form, legacy pocket start/depth names, and the new two-Z pocket start/end syntax with the shared case/decimal/sign aliases. Malformed semantic-looking modifiers are reported without misclassifying free-text tokens such as `xaviar`. Production importers remain unchanged.
- Extend the SVG comparison report with the new semantic interpretation beside the legacy lexical match. Offline comparison of the supplied Neck/Inlay/Headstock/Body fixtures reports zero semantic parse errors; the Neck fixture gains the label-only fractional `f10p25` section and the Headstock/Body fixtures gain the new Z-labelled pockets. 114 focused SVG/semantic tests pass.

## 0.2.48 (Nov 11th 2026)

- Fix part generation after the Neck SVG import-property addition by adding the missing `internal.neckImport` field to the Python `InternalProps` model. The FreeCAD property map already contained `internal.neckImport`; without the model field, `InstrumentProps.save_object_to_model(...)` failed during 2D/3D rebuild with `AttributeError: 'InternalProps' object has no attribute 'neckImport'`.

## 0.2.47 (Nov 11th 2026)

- Extend the shared SVG reader's native-circle recovery to closed four-cubic Bezier loops, using the established pocket-circle sampling rule: sample the authored curves, fit center/radius from their extents, and accept only when every sampled point is within 0.01 mm in final drawing space. Preserve noncircular four-cubic contours unchanged. Ellipses continue to be classified from their effective transformed axes, so coincident effective foci (equal final semi-axes) produce a native Sketcher circle even when the source tag is `<ellipse>`; nonuniform transforms can likewise turn a nominal circle into an ellipse. Production Marz importers remain unchanged.
- On the supplied `test_body.svg`, 24 named Body pocket/hole loops that were previously four cubic spans are now native circles; their maximum radial fit error is 0.001164 mm (0.001379 mm across all converted four-cubic circles in the fixture). The 0.2.46 FreeCAD report also confirms that the previously converted arc-based Inlay/Headstock circles are valid, closed and undistorted after Sketcher creation.

## 0.2.46 (Nov 11th 2026)

- The FreeCAD 1.1.4 comparison of 0.2.45 confirms that source-topology Coincident constraints still deform some SVG paths originally written as four circular arcs. Keep the topology-only join rule, but conservatively recognize complete same-center circular arc paths in the independent SVG reader and emit a single native Circle (or Ellipse under nonuniform SVG transforms) instead of four constrained arcs. Preserve separate subpaths, original SVG IDs/labels, and genuinely noncircular arc segments. Production Marz importers remain unchanged.
- Offline checks on the provided Inlay and Headstock SVGs identify seven complete circular paths; their radial difference from the original paths is at most 0.000004 mm. FreeCAD/OCC validation of the native Sketcher results remains pending.

## 0.2.45 (Nov 11th 2026)

- Follow up the FreeCAD 1.1.4 result that unconstrained SVG arcs match legacy geometry within 0.00014 mm, while automatic Coincident constraints shrink Headstock pockets by 4.30–5.88 mm and one Inlay by 1.33 mm. Replace coordinate-proximity clustering with source-topology joins: only join consecutive primitives that originated in the same SVG subpath and share one authored point, including the closing endpoint of closed paths. Never join independent subpaths or crossing profiles just because they touch; include native arc endpoints when their original SVG path was split. Account for FreeCAD's reversed arc parameter directions. Production importers are unchanged.
- Extend comparison diagnostics with authored join indices and source points, wire/closed-wire counts, and before/after-constraint geometric drift. Offline regression tests cover closed arcs, separate SVG subpaths, rectangles, polylines, crossings and native endpoint reversal. Real FreeCAD solver stability and pocket readiness still require validation; topology restrictions alone are not proven to prevent arc distortion.

## 0.2.44 (Nov 11th 2026)

- Follow up the first FreeCAD 1.1.4 side-by-side report: independently sampled SVG arc geometry matches the legacy Body/Headstock pocket bounding boxes within ~0.0002 mm, but the resulting connected Sketcher arcs differ by up to 6.29 mm. Extend comparison diagnostics with both unconstrained and Coincident-constrained Sketcher output, their mutual geometry drift and solver constraint counts, without changing production imports.
- Recognize all FreeCAD legacy subpath wire names (`f12__w`, `f12__1_w`, etc.) in comparison so multi-contour SVG elements are measured against their full original geometry. Isolate OCC distance errors per comparison stage and include detailed errors in the JSON report. Offline arc/multiwire regressions and reader tests pass; native Sketcher discrepancy still requires a FreeCAD rerun to isolate its cause.

## 0.2.43 (Nov 11th 2026)

- Extract standalone-compatible `freecad/marz/svg_to_sketch/` reader and native Sketcher adapter. The reader retains SVG source element kind, original ID/Inkscape label, group ancestry, affine transforms, units/viewBox and line/circle/ellipse/Bezier/arc primitives, independent of FreeCAD and guitar-specific semantics. The optional adapter builds editable Sketcher primitives and connects matching native endpoints without changing Marz production imports.
- Add `tools/compare_svg_imports.py` with offline per-element reports and an optional side-by-side FreeCAD legacy import vs native Sketcher geometry comparison. Reader test fixtures (Body/Headstock/Inlays/Neck) parse offline; 14 focused contract checks and the existing 70 SVG sketch tests pass. Real FreeCAD/OCC equivalence and GUI behavior remain unverified; production importer migration is intentionally deferred.

## 0.2.42 (Nov 11th 2026)

- Fix instrument property migration removing newly created properties when the legacy and current names are identical. This caused the existing-document Neck SVG import to lose `Internal_NeckImport` and abort before populating the import table. Keep actual differently named legacy-property migration unchanged; FreeCAD GUI confirmation remains pending.

## 0.2.35 (Nov 11th 2026)

- SVG import: recover original Inkscape labels from SVG XML by element ID because FreeCAD importSVG discards them; apply ID-first label fallback consistently to Body, Headstock, Inlay, Neck, and embedded pocket reconstruction. Existing naming grammars remain unchanged.
- Neck SVG: add the missing import timestamp property to previously open documents before storing Neck source data, preventing the `Internal_NeckImport` AttributeError.

## 0.2.34 (Nov 11th 2026)

- SVG import: accept matching `inkscape:label` values when an element's `id` does not match a recognized pattern, for Body, Headstock, Fretboard Inlays and Neck. Keep `id` precedence and the existing grammars. Apply the same rule to embedded pocket recovery and preserve circle/ellipse source tags under label fallback.

## 0.2.33 (Nov 10th 2026)

- Neck SVG: remove the erroneous fret-0-only filter. Accept and list every valid `f<N>_...` section (`f0_`, `f10_`, `f20_`, etc.), preserving the parsed fret number while continuing to ignore unrelated SVG IDs.
- Neck UI: rename the imported-source section from `Neck section at fret 0 (imported)` to `Neck sections (imported)` to reflect the multi-section source.

## 0.2.32 (Nov 10th 2026)
- Neck SVG: populate the fret-0 import table from the authored SVG id even when FreeCAD importSVG sanitizes the object Name; resolve the logical `f<N>_...` id from Name or Label, then keep only fret 0.

## 0.2.31 (Nov 10th 2026)
- Neck SVG: align fret-0 ID parsing with the existing Inlay importer: `f0_` is valid, arbitrary suffix text after the underscore is optional, unrelated named SVG geometry is silently ignored, and a missing fret-0 section produces only the information notification rather than synthetic `Ignored`/`Error` table rows.

## 0.2.30 (Nov 10th 2026)

- Neck UI: make the two main Neck-tab panes explicitly 50/50 instead of allowing the fixed-width profile preview to leave the parameter pane roughly 75/25.
- Neck SVG: add a separate embedded Neck source directly below **Section at fret 0**, using the same Import/Re-Import/Export, preview and parsed-elements table pattern as Fretboard/Body/Headstock SVG inputs.
- Neck SVG: accept fret-0 section element IDs `f0_...`, report recognized logical shapes in the table, report other named geometry as ignored, and reject files with no valid `f0_...` section. This patch stores/validates the source only; the existing C/D-generated neck profile remains the active surface source until the later neck-geometry migration.

## 0.2.29 (Nov 10th 2026)

- Headstock: fix the native plate Pad profile so SVG pocket loops do not appear as through-holes in the blank before the real Pocket operations run. Use the selected +X MakeInternals face only for its outer boundary, then include every current InternalFace region contained by that boundary to reconstruct the complete uncut plate.
- Headstock: enable multi-face Pad input for that reconstructed blank; grouped `Neck Pocket ...` / `Neck Pocket Profile ...` operations remain unchanged and continue to own pocket start/depth semantics.

## 0.2.28 (Nov 10th 2026)

- Headstock: record successful FreeCAD 1.1.4 runtime verification of the native Pad + grouped Pocket chain: one valid Headstock solid is produced, the legacy Boolean `PocketCutter` is `null`, and the finished neck reaches `Assembly status: OK`.
- Headstock: document that the first migration pass may emit a transient intermediate `headstock missing` recompute while the legacy object is being replaced/relinked; this is not the final native Headstock state.

## 0.2.27 (Nov 10th 2026)

- Headstock: fix the native plate profile after FreeCAD runtime testing showed the authored transition endpoints can lie on contour-edge interiors rather than contour vertices. Stop reconstructing the Pad profile from exact endpoint/vertex matches.
- Headstock: resolve the current `InternalFaceN` regions from `Headstock Master Sketch` on every rebuild, select the transition-adjacent +X face using the same center-of-mass rule as the old plate slicer, and keep grouped SVG pocket profiles on semantic edge loops. Internal-face numbering is never persisted.

## 0.2.26 (Nov 10th 2026)

- Headstock: add one authoritative `Headstock Master Sketch` combining contour, transition and SVG pocket loops with semantic `(start,end)` metadata.
- Headstock: replace the legacy generated headstock solid with persistent `Marz_Neck_Headstock` `PartDesign::Body`, a master-driven Pad for the plate side of the transition, and grouped native `PartDesign::Pocket` operations.
- Headstock: name grouped pocket operations `Neck Pocket <start>..<end> mm` and their binders `Neck Pocket Profile <start>..<end> mm`; clear the old Boolean SVG pocket cutter during migration to prevent double cutting. Top-transition and volute cutters remain intentionally staged for later migration.

## 0.2.25 (Nov 10th 2026)

- Body: give each native Pocket profile the same side/target/range identity as its Pocket, with `Profile` inserted in the label, for example `Body Top Pocket Profile Both 0.0..0.05 mm` and `Body Back Pocket Profile Back 0.0..20.0 mm`. Internal names and geometry are unchanged.

## 0.2.24 (Nov 10th 2026)

- Body: make native PartDesign Pocket labels self-contained and side-specific: `Body Top Pocket Both/Top ...` and `Body Back Pocket Both/Back ...`. This avoids FreeCAD adding `001` solely because Top and Back operations previously shared identical display labels. Internal object names and native feature history are unchanged.

## 0.2.23 (Nov 10th 2026)

- Document the verified Body migration findings from the full FreeCAD tree dump: purge the exact legacy object graph before creating native replacements, keep native containers persistent, and rebuild only their owned history.
- Define Headstock migration to follow the same staged process: inventory and purge legacy objects, build/verify a Headstock Master-driven PartDesign Pad first, then add grouped native SVG pockets, then migrate top/volute cuts one stage at a time without a legacy fallback hiding failures.

## 0.2.22 (Nov 10th 2026)

- Fix native Body migration after inspecting the real FreeCAD document tree.
- Do not protect legacy `Marz_Body_Top` / `Marz_Body_Back` `Part::FeaturePython` outputs during purge; they are the canonical-name blockers that force new PartDesign Bodies to `001`.
- Retire the obsolete `BodyTopPart` / `BodyBackPart` `PartFeature` descriptors from the native Body path so legacy public Body objects cannot be recreated.

## 0.2.21 (Nov 10th 2026)

- Body: flatten the native `Body Top` and `Body Back` `PartDesign::Body` objects directly under **Generated parts → Body**. The old **Body Top construction** / **Body Back construction** groups are migration-only scaffolding and are removed on **Update Parts** after their surviving children are rehomed.
- Body: keep the single Body Master/source sketches and the two native PartDesign Bodies together in the Body group; no geometry or native Pad/Pocket semantics change in this patch.

## 0.2.20 (Nov 10th 2026)

- Body: normalize the public `Body Top` / `Body Back` labels only after the surrounding FreeCAD Update Parts/regeneration transaction commits. FreeCAD 1.1.4 keeps deleted labels reserved until commit, which left the already-canonical `Marz_Body_Top` / `Marz_Body_Back` objects displayed as `Body Top001` / `Body Back001` during migration.
- Body: keep the working PartDesign Pad/Pocket history unchanged; add an explicit diagnostic if a post-commit label still cannot be reclaimed.

## 0.2.19 (Nov 10th 2026)

- Body: remove the complete pre-PartDesign Top/Back construction during migration: legacy public `Part::FeaturePython`/`Part::Feature` Body outputs, old `Part::Extrusion` blanks and their `Shared body contour*` links. These objects were visible in old documents before Update Parts, reserved the unsuffixed `Body Top` / `Body Back` labels, and produced repeated `No object linked` recompute diagnostics.
- Body: validate label ownership after legacy/native cleanup and report the exact remaining object name/type if `Body Top` or `Body Back` is still reserved, rather than silently accepting another `001` display label. The working PartDesign Pad/Pocket history itself is unchanged.

## 0.2.18 (Nov 10th 2026)

- Body: release stale FreeCAD display labels before deleting obsolete native Top/Back objects, then force the canonical `Body Top` / `Body Back` labels after native history construction so the persistent `Marz_Body_Top` / `Marz_Body_Back` Bodies no longer display as `001`.
- Body: remove obsolete staged `Shared body contour*` `App::Link` objects by their legacy internal-name pattern as well as their display label, eliminating the repeated broken-link reports left by the old `Part::Extrusion` architecture.

## 0.2.17 (Nov 10th 2026)

- Body: clean stale auto-suffixed native Top/Back Bodies and detached native features on every **Update Parts**, not only during the initial migration, then reclaim the canonical `Body Top` / `Body Back` labels for the persistent `Marz_Body_Top` / `Marz_Body_Back` PartDesign Bodies.
- Body: follow normal Part Design visibility after successful grouped pocket construction: hide the Pad and intermediate Pocket features/profile binders and show only the final Pocket (or the Pad when no Pocket exists).

## 0.2.16 (Nov 10th 2026)

- Body: keep canonical `Marz_Body_Top` / `Marz_Body_Back` `PartDesign::Body` containers persistent across **Update Parts** and rebuild only their owned Pad/Pocket features. This prevents repeated auto-suffixed `Body Top001` / `Body Back001` histories.
- Body: migrate the temporary 0.2.13--0.2.15 native histories by deleting owned features before deleting auto-suffixed Bodies, then remove already-detached native Pad/Pocket/profile artifacts before creating the canonical unsuffixed Body once.
- Body: stop deleting the PartDesign Body before its children, which caused FreeCAD to detach those children as orphaned root-level Pocket/profile objects.

## 0.2.15 (Nov 10th 2026)

- Body: resume native ordinary pocket migration only after runtime confirmation that both Part Design Pads follow Body Master contour edits correctly. Group pockets by `(target,start,end)` and create one real `PartDesign::Pocket` per group.
- Body: source each grouped Pocket from a `PartDesign::SubShapeBinder` selecting the authored semantic edge loops directly from the single Body Master Sketch. This replaces the rejected `InternalFaceN` partition resolver and does not introduce depth-group sketches.
- Body: clip each operation to the Top/Back half it actually intersects, including splitting Both-target depth spans at the Top/Back interface, so Pocket profiles start on or inside their own solid. Failed native profiles/Pockets remain visible; no legacy Boolean fallback is restored.
- Body: remove stale auto-suffixed native Top/Back Bodies before regeneration and flush removals so the canonical `Marz_Body_Top` / `Marz_Body_Back` names can be reclaimed.

## 0.2.14 (Nov 10th 2026)

- Body: make `Marz_Body_Top` and `Marz_Body_Back` the actual `PartDesign::Body` objects instead of wrapping temporary `*_History` Bodies in legacy `Part::FeaturePython` result objects. This removes the cross-scope links FreeCAD rejected even though both native Pads were already valid solids.
- Body: keep the successful Pad-first development state directly visible in the public Body Top/Back tree; failed Pad/profile objects remain visible and no legacy geometry fallback is restored.
- Body: remove orphaned staged `Shared body contour` links left by earlier `Part::Extrusion` revisions during explicit Update Parts.

## 0.2.13 (Nov 10th 2026)

- Body: make the native migration explicitly Pad-first. Body Top/Back now build only `PartDesign::Body` + `PartDesign::Pad` blanks from the single Body Master semantic contour; grouped native Pocket creation is suspended until both blanks are verified in FreeCAD.
- Body: remove the automatic legacy `Part::Extrusion`/Boolean fallback from the native development path. A failed Pad leaves its Body, contour `SubShapeBinder`, and Pad visible and marked `[FAILED]`/`BuildStatus=ERROR` for direct inspection instead of silently restoring the old result.
- Body: stop creating the legacy master-derived pocket cutter compounds during this milestone and clear pocket/neck/ergonomic finishing from the final linked Body result, so the visible geometry is exactly the native Pad foundation being tested.

## 0.2.12 (Nov 10th 2026)

- Body: resolve native pocket coverage from the Body Master's own `InternalFaceN` partitions instead of unreliable coplanar pocket/contour `Face.common()` results.
- Body: keep strict validation by rejecting any semantic pocket that crosses an `InternalFaceN` without a partition boundary.

## 0.2.11 (Nov 10th 2026)

- Fix native Body Master pocket resolution for authored pocket profiles that intentionally cross or protrude beyond the outer body contour. `InternalFaceN` coverage is now validated against the pocket's intersection with the body contour, matching the established Boolean semantics where geometry outside the body removes no material.
- Restrict selected pocket partitions to `InternalFaceN` regions that are themselves inside the body contour, so outside profile fragments cannot enter the native Part Design Pocket support.

## 0.2.10 (Nov 10th 2026)

- Fix native Body Master region resolution when overlapping closed profiles partition one semantic pocket into multiple Sketcher `InternalFaceN` regions. Grouped Part Design pocket profiles now select every internal face fully contained by the semantic SVG pocket and verify that their combined area covers the complete authored pocket before creating the native operation.
- Flatten multi-region semantic pockets when building/relinking `PartDesign::SubShapeBinder` supports, preserving one native `PartDesign::Pocket` per `(target, start, end)` group without adding derived grouping sketches.
- Correct the Body SVG reimport warning to direct the user to **Update Parts**, the actual command that rebuilds native Body histories in the current UI.

## 0.2.9 (Nov 10th 2026)

- Replace ordinary Body SVG pocket Booleans with native grouped Part Design histories when the Body Master exposes Sketcher internal faces. Body Top and Back each get their own `PartDesign::Body`, one multi-face Pad sourced from the single Body Master, and one real `PartDesign::Pocket` per semantic `(target, start, end)` operation group. No derived depth-group sketches are created.
- Resolve semantic pocket regions to the current `InternalFaceN` subelements by geometric overlap/containment on explicit regeneration instead of persisting face numbers. Profile `PartDesign::SubShapeBinder` objects reference those internal faces across Body scope; explicit Body SVG reimport reconnects surviving binders by semantic SVG IDs.
- Keep Both/Top/Back ownership and depth semantics: Both groups are added only to body halves their depth interval intersects, Top/Back groups stay on their designated half, and operation profiles are offset from the master plane while `PartDesign::Pocket.Length` remains `End-Start`. The semantic neck pocket and ergonomic cuts remain on the transitional linked finish stage pending their own native migration.

## 0.2.8 (Nov 10th 2026)

- Include the semantic Body Master `neckpocket` in the Body Pocket Properties list. Its geometry remains editable in the master sketch while its displayed depth follows the existing `Body_NeckPocketDepth` parameter; ordinary pocket Start/End/Target editing is not applied to this special region.
- Preserve mixed line/B-spline pocket profiles as separate native Sketcher geometries instead of collapsing them into one multispan spline when exact segment conversion is available. Add explicit endpoint `Coincident` constraints for every multi-edge pocket loop, including line-to-B-spline joins.

## 0.2.7 (Nov 10th 2026)

- Keep native Body Top/Back extrusions in their already-correct final body placement while applying Body Master and legacy SVG pocket cutters. Local cutter geometry is now transformed into the half's body frame before each Boolean instead of moving the body into SVG-local space and repositioning the Boolean result afterward.
- Route semantic `neckpocket` through that same world-frame cutter path. This fixes the runtime regression where a successful neck-pocket Boolean normalized/baked `Shape.Placement` and left the finished body shifted away from its master sketch.
- Preserve the generated neck-pocket fallback and ergonomic cutaways on their existing world-space paths; this change also matches the intended next migration to native Part/Part Design subtractive features.

## 0.2.6 (Nov 10th 2026)

- Put the semantic Body Master `neckpocket` cutter on the same SVG-local Boolean path as the already-working ordinary Body Master pockets. The cutter is shifted to the body top surface inside each half's local frame before the final guitar placement, fixing cuts when the imported/master sketch carries a non-identity placement.
- Keep the generated neck-frame fallback on its established world-space Boolean path; this correction changes only the semantic `neckpocket` consumer and preserves the staged migration toward native Part/Part Design operations.

## 0.2.5 (Nov 9th 2026)

- Import the special Body SVG semantic ID `neckpocket` directly into `Marz_Sketch_BodyMaster`, including recovery from the embedded Body SVG without replacing existing edited master geometry. The profile is kept as one complete closed semantic loop even when it protrudes beyond or crosses the body contour.
- Add a recomputable master-driven neck-pocket cutter. Its profile comes from `neckpocket`; its start is the body top surface and its depth remains `Body_NeckPocketDepth`, extruded along the Body Master Sketch local -Z so rotated body planes keep a 90-degree cutter.
- Retain the existing generated neck-frame cutter only as fallback when the master has no `neckpocket` region. Once the semantic region exists it is authoritative: invalid edits are reported as an incomplete body result rather than silently substituting the generated outline. Ordinary Body SVG pockets and the proven Boolean body finish remain otherwise unchanged.

## 0.2.4 (Nov 9th 2026)

- Make `Marz_Sketch_BodyMaster` the sole active source for all ordinary Body SVG pocket geometry and its start/depth/target metadata. Build separate master-derived Both, Top and Back cutter compounds while deliberately retaining the proven 0.1.66 Boolean finishing sequence.
- Remove the staged one-group pilot and legacy derived pocket-cutter helpers when the master is usable, and migrate already-parametric Body results to the master cutters so selective Top/Back regeneration cannot leave the untouched half linked to a deleted legacy cutter.
- Move the Body pocket-properties workflow to the Body Master semantic map and keep its operation grouping synchronized. Explicit Body SVG reimport reconnects surviving master contour/pocket consumers to the newly recreated master.

## 0.2.3 (Nov 9th 2026)

- Start pocket migration with one deterministic Body Master Sketch operation group while retaining the established 0.1.66 Boolean finish. The selected semantic pocket IDs are excluded from the legacy pocket-sketch cutter and rebuilt from the master so they are cut exactly once.
- Prefer a shallow Both-target zero-start group for the pilot when available, keeping the first FreeCAD runtime comparison small. Editing that master pocket geometry recomputes the pilot cutter and both affected body halves without regenerating the SVG source.
- Keep all other pocket groups, the neck pocket and ergonomic cutaways on the legacy path. This step intentionally proves master pocket grouping, depth and coordinate semantics before any PartDesign Pocket migration.

## 0.2.2 (Nov 9th 2026)

- Complete the staged blank-profile migration by switching Body Back to the same semantic `contour` adapter from `Marz_Sketch_BodyMaster` already used by Body Top.
- Keep Top and Back placement independent while sharing one master contour source. Pocket, neck-pocket and ergonomic finishing remain unchanged on the established 0.1.66 path.
- Update the Body regression so both native extrusions must link the master contour profile and derive their areas from the master geometry.

## 0.2.1 (Nov 9th 2026)

- Start the consumer migration with Body Top only: its native `Part::Extrusion` now receives the semantic outer `contour` from `Marz_Sketch_BodyMaster` through a recomputable hidden linked profile adapter. The master itself remains the editable authority; pocket loops and construction references are excluded from this blank profile.
- Keep Body Back on the proven 0.1.66 `Marz_Sketch_BodyContour` path and leave all pocket, neck-pocket and ergonomic finishing stages unchanged, providing a direct A/B geometry and placement reference in the same document.
- Clarify Body debug output so Top reports the master contour profile while Back reports the legacy contour source.

## 0.2.0 (Nov 8th 2026)

- Start the master-sketch architecture with a persistent `Marz_Sketch_BodyMaster` under Generated parts → Body. It combines the current editable body contour, bridge reference (construction geometry) and successfully converted pocket profiles while preserving semantic SVG IDs and geometry indices.
- Enable FreeCAD Sketcher `MakeInternals` on the master and expose B-spline controls. Record planned pocket operation groups by `(target, start, end)` in the master map so subsequent native Part Design operations can consume multiple internal faces without creating duplicate depth-group sketches.
- Keep the existing 0.1.66 Body Top/Back path untouched as the comparison oracle for this first 0.2 step. The master mirrors the established Body contour placement one-way and never participates in body-frame calculation. Body SVG reimport resets the master; normal editable-sketch conversion is idempotent.

## 0.1.65 (Nov 8th 2026)

- Expose the fretboard cutting pipeline as persistent FreeCAD construction objects: generated fretboard blank, nut-slot cutter, individual fret-slot cutters, linked inlay cutters, and a recomputable final `Marz_Fretboard` result.
- Create one editable Sketcher source per imported fret inlay, preserving native lines and conic arcs where possible and keeping connected profile endpoints coincident. Existing embedded/imported inlay parts can be converted without reimporting the SVG; explicit inlay reimport resets only those inlay source sketches.
- Route Regenerate Fretboard / Update Parts through the linked construction tree while preserving manually edited inlay sketches. The compound-radius blank algorithm itself is intentionally retained for geometry parity and remains a future native-loft refactor.

## 0.1.64 (Nov 8th 2026)

- Keep all mixed-contour endpoint `Coincident` constraints even when FreeCAD's solver moves under-constrained B-spline poles. Connectivity is now a validity requirement; geometric SVG deviation is logged for contours but no longer causes fallback to the disconnected/original source.
- Promote previously rejected but connected Body/Headstock contour sketches in place, so users do not need another destructive SVG reimport after this policy correction.

## 0.1.63 (Nov 8th 2026)

- Keep mixed SVG contour geometry exact when FreeCAD's under-constrained Sketcher solver moves B-spline spans while adding endpoint `Coincident` constraints. Snapshot the unconstrained contour, add joins transactionally, and remove only the new joins if they alter the outline.
- Preserve native straight lines, exact cubic B-spline spans and exposed spline controls even when endpoint joins are omitted. Add an offline regression for the reported 2.97405 mm solver distortion.

# Marz Workbench Changelog

## 0.1.62 (Nov 8th 2026)

- Stop requiring body/headstock contours to collapse into one cubic B-spline. Preserve straight SVG spans as native `Part.LineSegment` Sketcher geometry and curved cubic spans as exact single-span B-splines, joined by Coincident constraints including closure.
- Keep B-spline internal pole helpers only on curved segments and map all source contour geometries (not helpers) in `SVGElementMap`. The supplied new `marztest(2).FCStd` stores Body as 16 cubic + 2 line edges and Headstock as 8 cubic + 2 line edges, which this mixed representation accepts naturally.
- Retain the old exact multi-span B-spline builder only as a pocket-conversion fallback.

## 0.1.61 (Nov 8th 2026)

- Give the three derived body pocket-cutter `Part::FeaturePython` objects the same `BodyViewProvider` used by Body Top/Back, including repair on document restore, so hidden cutters can be shown and rendered normally.

## 0.1.60 (Nov 8th 2026)

- Restore display of scripted Body Top/Back results with the same Python view-provider pattern already proven by the neck (`BodyViewProvider` on `Part::FeaturePython`). Repair it on document restore as well as regeneration; the body solids were valid and `Visibility=True`, but their scripted view provider was missing.
- Position the Top and Back `App::Link` objects explicitly in their respective body frames while still linking the one editable contour. The Back native extrusion now starts on the Back plane instead of incorrectly starting on the Top plane and being shifted only in the finished result.
- Keep SVG reimport anchored to the shared Top source plane even when only the Back result exists, now that `SourceDisplay` is half-specific. Extend the body regression checks to require the Back link/blank at the Back Z placement and the finished scripted parts to carry the body view provider.

## 0.1.59 (Nov 8th 2026)

- Keep the proven `App::Link.LinkTransform` body-placement fix, but remove the speculative construction-group visibility forcing.
- Make the offline body model reproduce FreeCAD App::Link placement semantics so a missing `LinkTransform` now fails tests instead of being silently masked.
- Lock the supplied `marztest.FCStd` contour, top, and back placement chain into regression checks, including the neck-pocket Boolean path.

## 0.1.58 (Nov 8th 2026)

- Preserve the Sketcher source transform through the App::Link used by both native body extrusions, so the blanks and resulting cuts occupy the same guitar coordinate frame.
- Make the requested body construction group visible on explicit regeneration; a hidden parent prevented the valid finished body from appearing even with its own Visibility enabled.
- Keep the optional diagnostics compatible with test geometry without BoundBox.

## 0.1.56 (Nov 8th 2026)

- Ensure native Part body extrusions follow the positioned sketch's rotated
  local +Z direction, not fixed world +Z. This preserves thickness direction
  on guitars with a nonzero neck/body angle. Keep custom-axis control so a
  clockwise SVG contour cannot reverse extrusion by changing face normal.
- Add rotated-body direction regression check; FreeCAD GUI verification is open.


## 0.1.55 (Nov 8th 2026)

- Place the shared editable Body contour, bridge reference and pocket sketches
  in the actual guitar/Body Top coordinate frame rather than leaving them at
  the SVG origin. Native extrusion blanks now inherit the positioned contour.
- Keep final Top/Back placements and SVG pocket start/depth semantics unchanged:
  the derived Body feature and both native/legacy cutter paths compensate for
  the sketches' display transform before performing the original local cuts.
- Store the applied Marz transform on each sketch to prevent accumulated
  translation on repeated regeneration, preserve user placement edits and
  normalize the bridge-reference positioning calculation. Align newly
  reimported sketches with existing body features without resetting other parts.
- Add focused placement, repeated-regeneration, bridge, pocket-cutter and
  per-component tests. Actual FreeCAD 1.1.4 GUI/recompute validation is open.


## 0.1.54 (Nov 8th 2026)

- Restore the expected first-regeneration display: show the positioned finished
  Body Top/Back features and hide their native construction blanks. The blanks
  are in SVG source coordinates; showing them instead makes the body appear to
  overlap the neck and hides pocket cuts even after the world-placement fix.
- On explicit regeneration repair the specific legacy inverse-visibility state
  (blank visible, finish hidden). Subsequent FreeCAD recomputation and normal
  regeneration preserve intentional visibility choices when no inverse state
  exists. Warn if the finish is invalid and cannot be displayed.
- Add regression tests for migrated output, inverse display state, and preserved
  user visibility. Full FreeCAD 1.1.4 GUI verification remains outstanding.

## 0.1.53 (Nov 8th 2026)

- Fix missing body-position offset in the linked Body Top/Back construction:
  compose guitar placement with the extrusion's existing SVG import Location
  instead of replacing that Location. Preserves manually editable source
  contours and keeps the body at the correct neck/bridge position.
- Add location-aware body regression tests: imported source offsets survive,
  unplaced sources still work, and repeated FreeCAD recomputation does not
  accumulate the translation. The supplied guitar BREP confirms the original
  placement result via OpenCascade; FreeCAD 1.1.4 GUI verification remains open.

## 0.1.52 (Nov 8th 2026)

- Introduce the first linked, editable body construction: one shared body contour
  Sketcher source, two native `Part::Extrusion` blanks (Top/Back), and per-half
  scripted derived finishes that recompute from cutter links without
  overwriting sketch edits. Keep legacy body part names and cutting transforms.
- Derive Both/Top/Back pocket cutter compounds from the pocket Sketcher object
  using its SVG ID/depth/target metadata during normal FreeCAD recomputation.
  Failed cutter operations retain the previous valid shape and set `BuildStatus`.
- Move editable body/headstock sketches from Imported objects to their semantic
  groups under Generated parts, preserve original imported SVG wires, and avoid
  duplicate tree entries in `MarzInstrumentVP.claimChildren()`.
- Migrate existing static body halves only on explicit Body Top/Back regeneration;
  rebind native extrusion contour links after an explicit SVG reimport.
- Add linked-source, migration, selective-regeneration and pocket-update tests.
  Offline checks pass; actual FreeCAD 1.1.4 native extrusion, Boolean,
  migration and GUI geometry remain unverified.

## 0.1.51 (Nov 7th 2026)

- Convert geometrically circular SVG `<ellipse>` pockets to native Sketcher circles before considering an ellipse; preserve genuinely unequal effective radii as ellipses (including nonuniformly transformed circles). Use a 0.01 mm radial fit, not the permissive 0.5 mm conversion tolerance.
- Convert line-only SVG reference paths (notably the body bridge reference) to native `Part.LineSegment` Sketcher geometries instead of Draft-derived B-splines. Preserve original world positions and apply initial coincidence constraints only where distinct line segments share an SVG endpoint; genuinely curved references retain the Draft fallback.
- Add regression tests for equal/unequal-radius ellipses, native-ellipse conversion, saved-bridge reference coordinates, multi-line endpoint connectivity, curved-path fallback and SVG-ID mapping. FreeCAD GUI verification remains outstanding.

## 0.1.50 (Nov 7th 2026)

- Keep source SVG circle/ellipse primitive types associated with pocket IDs on both regular and embedded-SVG imports; distinguish them from circular paths.
- Measure curve samples rather than the potentially oversized OCC B-spline bounding box to recover native Sketcher circles, and use native ellipses for supported axis-aligned ovals.
- Convert straight imported Bézier/B-spline edges to native Sketcher lines, merge redundant collinear sections (e.g. twelve subdivisions into four rectangle sides), and constrain the corners when initially creating the sketch.
- Add regression tests for the primitive metadata, spline bounding-box overshoot, ellipse conversion, and subdivided rectangular paths. FreeCAD GUI verification is still outstanding.

## 0.1.49 (Nov 7th 2026)

- Avoid selection-feedback reentrancy in the pocket-properties dock: selecting a table row no longer modifies FreeCAD/Sketcher selection or registers a selection observer. An explicit **Highlight pocket** button selects associated edges outside Sketcher edit mode.
- Log distinct `[Marz Pocket]` dock-opening/ready markers and a `[Marz SVG]` conversion-command marker to distinguish dock startup from slow embedded-SVG imports. No SVG import is initiated by the properties dock. FreeCAD GUI reproduction of the reported freeze remains to be verified.
- Update the checklist and user instructions.

## 0.1.48 (Nov 7th 2026)

- Add **Guitar → Edit pocket properties**, a dockable per-pocket SVG metadata editor for body and headstock Sketcher pocket collections. IDs remain fixed while start/end depths and body target (Both/Top/Back) can be edited; the panel can remain open during Sketcher edit mode and attempts to select the associated sketch geometry.
- Commit edits to `SVGElementMap` as start/depth/target and immediately rebuild the legacy cutter groups; validate values, restore metadata on failed conversion, and remove empty former target groups when a pocket changes side. Finished guitar solids still require **Update Parts** until native FreeCAD-linked construction is implemented.
- Update README and handover checklist. Offline tests passed; real FreeCAD GUI and save/reopen validation remains outstanding.

## 0.1.47 (Nov 7th 2026)

- Make **Guitar → Create editable SVG sketches** create missing Body/Headstock pocket sketches from the existing document-embedded SVGs, not only after destructive SVG reimport. Recover original pocket IDs/depths and import anchor in an isolated temporary document; retain existing sketches and imported part geometry unchanged. Report missing SVGs, unrecognized pocket IDs and conversion failures in the FreeCAD Report view.
- Update the checklist and document the non-destructive conversion path. FreeCAD GUI execution remains unverified.

## 0.1.46 (Nov 7th 2026)

- Disable Sketcher B-spline curvature comb by default on first editable-SVG use; preserve the user's later display preference. Uses FreeCAD 1.1.4 `BSplineCombVisible` preference.
- Create one editable pocket sketch per imported Body/Headstock SVG, retaining per-element SVG IDs, geometry indices, start/depth values and target side. Imported circular outlines are recognized as Sketcher circles when geometrically circular; supported multi-edge contours become editable B-splines.
- Rebuild legacy body/headstock pocket cutter compounds from edited pocket sketches on Update Parts or selective component regeneration. Preserve original cutters if a sketch is absent, incomplete or contains invalid profiles. Explicit SVG reimport replaces only that SVG's sketches. The one-whole-SVG/one-sketch refactor remains open.
- Extend offline tests and handover; actual FreeCAD 1.1.4 GUI edits, generated cutter equivalence and save/reopen still require verification.

## 0.1.45 (Nov 7th 2026)

- Expose internal B-spline poles and knot helper geometry when constructing editable body/headstock contour sketches, allowing Sketcher control-point manipulation rather than only endpoints.
- Join the single clamped contour spline’s first and last endpoints with a native initial Coincident constraint; moving the seam no longer opens the closed contour. Preserve original C0 junctions and geometry.
- Keep internal Sketcher helper indices out of the source SVG element map. Add offline regression tests, update the handover and document the explicit SVG reimport required for preexisting sketches. FreeCAD 1.1.4 GUI interaction remains unverified.

## 0.1.44 (Nov 7th 2026)

- Replace the per-segment Sketcher representation of body/headstock contours with a single multi-span cubic B-spline per connected SVG contour, preserving original Bezier spans and straight segments exactly; no post-processing coincidence constraints.
- Validate joined-curve geometry bidirectionally and retain the original source on unsupported topology. Confirmed using the supplied new guitar BREP with OpenCascade: body 23 segments, headstock 21 segments, maximum sampled deviation under 2e-13 mm; checks for closure, placement and size unchanged.
- Preserve manually edited existing sketches until explicit SVG reimport; add offline regression tests and update the implementation checklist. Full FreeCAD 1.1.4 GUI edit/recompute and save/reopen verification remains open.

## 0.1.43 (Nov 7th 2026)

- Create native SVG-derived Sketcher objects with their `Coincident` endpoint constraints already attached; infer joins from the original SVG wire rather than from Draft-altered sketch endpoints.
- Match source edges to converted Sketcher geometry even if reversed or reordered; keep the 0.5 mm import tolerance distinct from the 0.001 mm original connectivity tolerance.
- Remove the failed post-processing/rollback path from 0.1.42 and never modify existing manually edited sketches implicitly. Explicit SVG reimport regenerates sketches with the corrected joins.
- Add focused tests for original-edge connectivity, edge reordering, initial constraint timing, and the exact reported contour deviations; update the handover checklist.

## 0.1.42 (Nov 7th 2026)

- Add native Sketcher endpoint Coincident constraints to new and existing SVG-derived reference sketches without adding horizontal/vertical constraints or overwriting manual edits.
- Keep the tight 0.001 mm endpoint-joining tolerance separate from the 0.5 mm conversion tolerance; warn and remove newly created constraints if the solver conflicts or alters the outline.
- Add focused regression tests and update the editable-model checklist; FreeCAD GUI confirmation remains open.

## 0.1.41 (Nov 7th 2026)

- Add five independent regeneration buttons to the Guitar Parameters editor: Body Top, Body Back, Neck, Headstock, and Fretboard. Retain the existing Update Parts operation.
- Keep body outputs independent: only write the requested half. Separate headstock plate/top/volute/pocket resets from neck spline/Gordon/heel/truss-rod resets without reimporting SVG sketches.
- Document the reset boundaries, maintain the editable-model roadmap, and add offline tests for controller routing, source retention, body writes, and Qt callback binding. FreeCAD GUI verification remains open.

## 0.1.40 (Nov 7th 2026)

- Accept SVG-to-Sketch pilot conversion differences up to 0.5 mm, retaining curve, topology, length, placement and edge-count checks. Preserve strict verification for automatic rigid-translation corrections.
- Revalidate saved rejected conversions in place from the existing Guitar menu command, without replacing or moving their edited sketch geometry; retain rejection for differences above 0.5 mm.
- Add tolerance-boundary and revalidation tests; update the handover checklist.

## 0.1.39 (Nov 7th 2026)

- Overlay rejected Sketcher contours over the original imported SVG references (red reference, green sketch) for visual inspection; log their world-space center displacement. Existing rejected sketches can be compared without rebuilding them.
- Correct purely rigid Draft placement offsets only after validating full curve equality at the corrected placement. Do not recenter non-rigid mismatches or alter manual edits.
- Persist the pilot's original SVG element ID and Sketcher geometry index map, with source name/category for migration toward one Sketcher object per SVG. Pocket/hole metadata and native primitive preservation remain future work.
- Extend offline regression tests and update the editable-model checklist. Actual FreeCAD GUI overlay remains to be verified.

## 0.1.38 (Nov 7th 2026)

- Keep SVG-to-Sketch conversions that fail the geometry fidelity check as visible Sketcher objects, labelled `(conversion mismatch)`, so the user can inspect their actual contours.
- Record a persistent `SVGConversionValid = false` guard and `SVGConversionError` diagnostic; continue using the original SVG wire for generated guitar parts. Existing accepted sketches remain valid and repeated conversions preserve edits.
- Add contract tests reproducing the reported contour XMin/XMax deviations, document the inspection workflow, and update the project checklist. Real FreeCAD GUI validation remains open.

## 0.1.37 (Nov 7th 2026)

- Correct Sketcher conversion fidelity validation for SVG multi-edge closed contours: accept exact curve matches despite Bézier-to-B-spline conversion, reversed edge direction or different edge enumeration.
- Retain explicit checks for closed topology, edge count, curve deviations, full length and world placement; log a specific rejection reason instead of a generic mismatch.
- Add focused regression tests, inspect the current guitar's imported contour BREPs and update `todo.md`; FreeCAD GUI conversion and save/reopen remain unverified.

## 0.1.36 (Nov 7th 2026)

- Add a first SVG-to-native-Sketcher conversion pilot for imported body/headstock contours, transition and bridge references; also offer Guitar → Create editable SVG sketches for existing documents.
- Validate the converted curve geometry before use, preserve the original imported wire as fallback, and retain manual Sketcher edits until explicit SVG reimport.
- Feed the edited Sketcher geometry to existing body/headstock builders on Update Parts; retain headstock edge ordering and original coordinate placement.
- Add six offline contract tests and update the editable-model checklist and limitations.

## 0.1.35 (Nov 7th 2026)

- Add `todo.md` handover and task checklist for editable native FreeCAD construction across all guitar components, Draft-editable SVG sources, and independent regeneration.
- Record dependency and geometry-equivalence gates, regression fixtures, migration requirements, and previous neck-construction failures.

## 0.1.34 (Nov 6th 2026)

- Correct negative neck-shell orientation before slicing with the editable heel plane.
- Report unsplit heel geometry instead of silently accepting the untrimmed solid.
- Recompute the neck blank on Update Parts when its geometry generator changes.

## 0.1.33 (Nov 6th 2026)

- Fix the FreeCAD length-quantity mismatch when migrating the legacy heel cutting plane; preserve user-edited cutters.
- Add isolated regression tests for migration, placement, manual edits and cutter regeneration.

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

