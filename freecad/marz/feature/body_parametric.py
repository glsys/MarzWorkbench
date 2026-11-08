# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Native editable body extrusions and recomputable, linked body finishes.

The two halves share one editable contour. Native Part::Extrusion objects own
height and direction; their finished results retain the original Marz cutting
sequence (pocket compounds, neck pocket, then ergonomic cutaways). Normal
FreeCAD recomputation never recreates upstream sketches or cutter shapes.
"""

import Part  # type: ignore

from freecad.marz.extension.fc import App, Vector, Placement
from freecad.marz.feature.document import (BodyContour, BodyPockets,
    BodyTopPockets, BodyBackPockets, BodyErgoCutsTop, BodyErgoCutsBack,
    BodyTopPart, BodyBackPart)
from freecad.marz.feature.logging import MarzLogger


BODY_GROUP = 'Marz_Group_Body'
TOP_GROUP = 'Marz_Group_Body_Top'
BACK_GROUP = 'Marz_Group_Body_Back'


def _group(doc, name, label, parent=None):
    group = doc.getObject(name)
    if group is None:
        group = doc.addObject('App::DocumentObjectGroup', name)
        group.Label = label
    if parent is not None and group not in parent.Group:
        parent.addObject(group)
    return group


def _move_to_group(doc, obj, group):
    """One tree owner: avoid the same sketch under Imports and Generated parts."""
    if obj is None:
        return
    for owner in doc.Objects:
        if (owner is not group and owner.TypeId == 'App::DocumentObjectGroup'
                and obj in owner.Group):
            owner.removeObject(obj)
    if obj not in group.Group:
        group.addObject(obj)


def body_groups(doc):
    parts = doc.getObject('Marz_Group_Parts')
    if parts is None:
        parts = _group(doc, 'Marz_Group_Parts', 'Generated parts')
    body = _group(doc, BODY_GROUP, 'Body', parts)
    top = _group(doc, TOP_GROUP, 'Body Top construction', body)
    back = _group(doc, BACK_GROUP, 'Body Back construction', body)
    return body, top, back


def organize_body_sources(doc):
    """Move editable sources, not archived/imported SVG reference shapes."""
    body, _, _ = body_groups(doc)
    for name in ('Marz_Sketch_BodyContour', 'Marz_Sketch_BridgeRef',
                 'Marz_Sketch_BodyPockets', 'Marz_Sketch_BodyDefaultContour'):
        _move_to_group(doc, doc.getObject(name), body)
    return body


def _usable(obj):
    return obj is not None and (not hasattr(obj, 'SVGConversionValid') or
                                obj.SVGConversionValid)


def _contour(doc, bodyd):
    """Prefer the shared Sketcher outline, with legacy SVG fallback."""
    sketch = doc.getObject('Marz_Sketch_BodyContour')
    if _usable(sketch):
        return sketch
    original = doc.getObject('Marz_Body_Contour')
    if original is not None and not original.Shape.isNull():
        return original
    # New guitar without a Body SVG: create a native, editable rectangle.
    name = 'Marz_Sketch_BodyDefaultContour'
    sketch = doc.getObject(name)
    if sketch is None:
        from Sketcher import Constraint
        sketch = doc.addObject('Sketcher::SketchObject', name)
        sketch.Label = 'Body default contour (edit in Sketcher)'
        half = bodyd.width / 2
        points = [Vector(0, half, 0), Vector(-bodyd.length, half, 0),
                  Vector(-bodyd.length, -half, 0), Vector(0, -half, 0)]
        sketch.addGeometry([Part.LineSegment(points[i], points[(i + 1) % 4])
                            for i in range(4)], False)
        sketch.addConstraint([Constraint('Coincident', i, 2, (i + 1) % 4, 1)
                              for i in range(4)])
        sketch.ViewObject.Visibility = False
    return sketch


def _link(obj, kind, name, value):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, 'Marz construction')
    setattr(obj, name, value)


def _valid_solid(shape):
    return (shape is not None and not shape.isNull() and
            len(shape.Solids) == 1 and shape.isValid())


def _cut(source, cutter, label, failures=None):
    try:
        candidate = source.cut(cutter)
        if not _valid_solid(candidate):
            raise ValueError('cut does not produce one valid solid')
        return candidate.removeSplitter()
    except Exception as exc:
        if failures is not None:
            failures.append('{}: {}'.format(label, exc))
        MarzLogger.warn('[Marz Body] {}: {}; retaining previous stage'.format(label, exc))
        return source


def finish_body_shape(blank, *, height, top_thickness, back, placement,
                      global_pockets=None, side_pockets=None, neck_pocket=None,
                      carve_neck=False, ergo_top=None, ergo_back=None,
                      top_placement=None, back_placement=None, failures=None):
    """Reapply the existing body cutter transforms using linked FreeCAD shapes."""
    if not _valid_solid(blank):
        raise ValueError('Body extrusion did not produce one valid solid')
    shape = blank.copy()
    for name, pockets, shift in (
            ('Global pockets', global_pockets, height + top_thickness if back else height),
            ('Side pockets', side_pockets, height)):
        if pockets is None or pockets.Shape.isNull():
            continue
        tool = pockets.Shape.copy()
        tool.translate(Vector(0, 0, shift))
        for solid in tool.Solids:
            shape = _cut(shape, solid, name, failures)
    # The native extrusion retains the source Sketcher's shape Location.
    # SVG imports often have a non-identity Placement; assigning the guitar
    # placement outright discards that import transform and shifts the body
    # toward the headstock. Compose the guitar placement on the *left* so it
    # also rotates the imported frame exactly as the legacy generator does.
    shape.Placement = placement.multiply(shape.Placement)
    if carve_neck:
        if neck_pocket is None or neck_pocket.Shape.isNull():
            if failures is not None:
                failures.append('Neck pocket: cutter unavailable')
        else:
            shape = _cut(shape, neck_pocket.Shape, 'Neck pocket', failures)
    # Both ergonomic cutters affect both halves, just like apply_ergo_cutaways.
    if ergo_top is not None and not ergo_top.Shape.isNull():
        tool = ergo_top.Shape.copy()
        tool.Placement = Placement(top_placement.Base + Vector(0, 0, top_thickness),
                                   top_placement.Rotation)
        shape = _cut(shape, tool, 'Top ergonomic cutaway', failures)
    if ergo_back is not None and not ergo_back.Shape.isNull():
        tool = ergo_back.Shape.copy()
        tool.Placement = back_placement
        shape = _cut(shape, tool, 'Back ergonomic cutaway', failures)
    if not _valid_solid(shape):
        raise ValueError('Body result invalid after cuts')
    return shape


class BodyResult:
    """FreeCAD recompute proxy for derived cuts; all geometry inputs are Links."""

    def __init__(self, obj):
        obj.Proxy = self
        for name in ('Blank', 'TopExtrusion', 'GlobalPockets', 'SidePockets', 'NeckPocket',
                     'ErgoTop', 'ErgoBack'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyLink', name, 'Marz construction')
        for name in ('BodyPlacement', 'TopPlacement', 'BackPlacement'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyPlacement', name, 'Marz construction')
        for name in ('ExtrusionHeight', 'TopThickness'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyLength', name, 'Marz construction')
        for name in ('IsBack', 'CarveNeckPocket'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyBool', name, 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        if obj.Blank is None:
            return
        try:
            failures = []
            for pocket in (obj.GlobalPockets, obj.SidePockets):
                if pocket is not None and hasattr(pocket, 'BuildStatus') and pocket.BuildStatus != 'OK':
                    failures.append('{}: {}'.format(pocket.Label, pocket.BuildStatus))
            result = finish_body_shape(
                obj.Blank.Shape,
                height=obj.Blank.LengthFwd.Value,
                top_thickness=(obj.TopExtrusion.LengthFwd.Value if obj.TopExtrusion
                               else obj.TopThickness.Value),
                back=obj.IsBack,
                placement=obj.BodyPlacement,
                global_pockets=obj.GlobalPockets,
                side_pockets=obj.SidePockets,
                neck_pocket=obj.NeckPocket,
                carve_neck=obj.CarveNeckPocket,
                ergo_top=obj.ErgoTop,
                ergo_back=obj.ErgoBack,
                top_placement=obj.TopPlacement,
                back_placement=obj.BackPlacement,
                failures=failures)
            obj.Shape = result
            obj.BuildStatus = ('INCOMPLETE: ' + '; '.join(failures)) if failures else 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] {}: {}'.format(obj.Label, exc))
            # Do not overwrite a previously valid solid with an empty result.

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _native_extrusion(doc, name, label, source, length, group):
    """Part::Extrusion uses a local Link to one shared Sketcher contour.

    The original Sketch remains in Body, while the native extrusion's own
    child is a lightweight Link. FreeCAD 1.1 supports App::Link as the base of
    Part::Extrusion. LengthFwd is the normal editable thickness property.
    """
    link_name = name + '_ContourLink'
    link = doc.getObject(link_name)
    if link is None:
        link = doc.addObject('App::Link', link_name)
        link.Label = 'Shared body contour'
    link.LinkedObject = source
    # Part::Extrusion owns/claims its Base Link in the tree; do not also put
    # the Link directly into a group (which would display it twice).
    if link.ViewObject is not None:
        link.ViewObject.Visibility = False
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('Part::Extrusion', name)
        obj.Label = label
        obj.ViewObject.Visibility = False
    obj.Base = link
    obj.DirMode = 'Custom'
    obj.Dir = Vector(0, 0, 1)
    obj.LengthFwd = length
    obj.LengthRev = 0
    obj.Solid = True
    _move_to_group(doc, obj, group)
    obj.recompute()
    if not _valid_solid(obj.Shape):
        raise ValueError('Native body extrusion {} produced no valid solid'.format(name))
    return obj


def _result(doc, name, label, group, style):
    obj = doc.getObject(name)
    # A first-time migration is an explicit regeneration: show its finished
    # result, even if the obsolete static object happened to be hidden.
    # Subsequent regenerations must preserve the user's visibility choice.
    if obj is not None and obj.TypeId != 'Part::FeaturePython':
        # Only executed on explicit Marz regeneration, never on Recompute.
        # Keep the established output name; this is an explicit migration.
        doc.removeObject(name)
        obj = None
    if obj is None:
        obj = doc.addObject('Part::FeaturePython', name)
        obj.Label = label
        BodyResult(obj)
        if style is not None:
            style.apply(obj.ViewObject)
        obj.ViewObject.Visibility = True
    elif not isinstance(getattr(obj, 'Proxy', None), BodyResult):
        BodyResult(obj)
    _move_to_group(doc, obj, group)
    return obj


class PocketCutters:
    """Derived body cutters linked to the *editable* shared pocket sketch."""

    def __init__(self, obj):
        obj.Proxy = self
        if 'Source' not in obj.PropertiesList:
            obj.addProperty('App::PropertyLink', 'Source', 'Marz construction')
        if 'Target' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'Target', 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        import json
        sketch = obj.Source
        if sketch is None:
            return
        try:
            if not getattr(sketch, 'SVGConversionValid', True):
                raise ValueError('SVG pocket sketch marked invalid')
            elements = json.loads(sketch.SVGElementMap)['elements']
            cutters = []
            for item in elements:
                if item['target'] != obj.Target:
                    continue
                if not item['indices'] or item['depth'] <= 0:
                    raise ValueError('Invalid SVG pocket: {}'.format(item['id']))
                edges = [sketch.Geometry[i].toShape() for i in item['indices']]
                wire = Part.Wire(edges)
                wire.Placement = sketch.Placement
                if not wire.isClosed():
                    raise ValueError('Open SVG pocket: {}'.format(item['id']))
                solid = Part.Face(wire).extrude(Vector(0, 0, -item['depth']))
                solid.translate(Vector(0, 0, -item['start']))
                if not _valid_solid(solid):
                    raise ValueError('Invalid SVG pocket solid: {}'.format(item['id']))
                cutters.append(solid)
            obj.Shape = Part.makeCompound(cutters) if cutters else Part.Shape()
            obj.BuildStatus = 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] {}: {}; retained previous cutters'.format(obj.Label, exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _pocket_cutters(doc, group, sketch):
    """Native linked downstream features for all/top/back cutter subsets."""
    targets = {}
    for target, label in (('', 'Both'), ('t', 'Top'), ('b', 'Back')):
        name = 'Marz_Body_SketchCutters_' + (label)
        obj = doc.getObject(name)
        if obj is None:
            obj = doc.addObject('Part::FeaturePython', name)
            obj.Label = label + ' pocket cutters (derived)'
            PocketCutters(obj)
            obj.ViewObject.Visibility = False
        elif not isinstance(getattr(obj, 'Proxy', None), PocketCutters):
            PocketCutters(obj)
        obj.Source = sketch
        obj.Target = target
        _move_to_group(doc, obj, group)
        obj.recompute()
        targets[target] = obj
    return targets


def regenerate_body(inst, bodyd, doc, *, component=None):
    """Explicitly reset selected half; its other half is never overwritten."""
    if component not in (None, 'top', 'back'):
        raise ValueError('Unknown body component: {}'.format(component))
    from freecad.marz.feature.svg_sketch import source_object
    from freecad.marz.feature.neck import make_neck_pocket

    body, top_group, back_group = body_groups(doc)
    contour = _contour(doc, bodyd)
    organize_body_sources(doc)
    bridge = source_object(doc, 'Marz_Body_Bridge')
    top_placement, back_placement = bodyd.placements(bridge)

    pocket_sketch = doc.getObject('Marz_Sketch_BodyPockets')
    linked_pockets = (_pocket_cutters(doc, body, pocket_sketch)
                      if _usable(pocket_sketch) else None)
    # Shared neck pocket cutter, not a duplicated hidden Boolean inside each half.
    tool = doc.getObject('Marz_Body_NeckPocketTool')
    if bodyd.neckPocketCarve:
        cutter = make_neck_pocket(inst, bodyd.neckd.fbd)
        if cutter is not None:
            if tool is None:
                tool = doc.addObject('Part::Feature', 'Marz_Body_NeckPocketTool')
                tool.Label = 'Neck pocket cutter'
                tool.ViewObject.Visibility = False
            tool.Shape = cutter
            _move_to_group(doc, tool, body)
    for side in ('top', 'back'):
        if component is not None and component != side:
            continue
        thickness = bodyd.topThickness if side == 'top' else bodyd.backThickness
        part_def = BodyTopPart if side == 'top' else BodyBackPart
        if thickness <= 0:
            # Explicit regeneration to zero thickness clears this side's
            # own native construction, but never changes the other half.
            part_def.remove(doc=doc)
            base_name = 'Marz_Body_' + side.title() + '_Extrusion'
            if doc.getObject(base_name):
                doc.removeObject(base_name)
            if doc.getObject(base_name + '_ContourLink'):
                doc.removeObject(base_name + '_ContourLink')
            continue
        group = top_group if side == 'top' else back_group
        # Repair the inverse display state left by earlier versions: an
        # unpositioned construction blank was shown while the positioned,
        # fully cut body output was hidden. Capture this *before* hiding the
        # extrusion, and only repair it on explicit regeneration.
        previous_blank = doc.getObject('Marz_Body_' + side.title() + '_Extrusion')
        previous_finish = doc.getObject(part_def.name)
        inverted_visibility = bool(
            previous_blank is not None and previous_blank.ViewObject.Visibility
            and previous_finish is not None
            and not previous_finish.ViewObject.Visibility)
        extrusion = _native_extrusion(doc, 'Marz_Body_' + side.title() + '_Extrusion',
                                      side.title() + ' blank (Part Extrusion)',
                                      contour, thickness, group)
        result = _result(doc, part_def.name, part_def.label, group, part_def.style)
        _link(result, 'App::PropertyLink', 'Blank', extrusion)
        _link(result, 'App::PropertyLink', 'TopExtrusion',
              extrusion if side == 'top' else doc.getObject('Marz_Body_Top_Extrusion'))
        _link(result, 'App::PropertyLink', 'GlobalPockets',
              linked_pockets[''] if linked_pockets else BodyPockets.get(doc=doc))
        _link(result, 'App::PropertyLink', 'SidePockets',
              linked_pockets['t' if side == 'top' else 'b'] if linked_pockets
              else (BodyTopPockets if side == 'top' else BodyBackPockets).get(doc=doc))
        _link(result, 'App::PropertyLink', 'NeckPocket', tool if bodyd.neckPocketCarve else None)
        _link(result, 'App::PropertyLink', 'ErgoTop', BodyErgoCutsTop.get(doc=doc))
        _link(result, 'App::PropertyLink', 'ErgoBack', BodyErgoCutsBack.get(doc=doc))
        result.BodyPlacement = top_placement if side == 'top' else back_placement
        result.TopPlacement = top_placement
        result.BackPlacement = back_placement
        result.ExtrusionHeight = thickness
        result.TopThickness = bodyd.topThickness
        result.IsBack = (side == 'back')
        result.CarveNeckPocket = bodyd.neckPocketCarve
        result.recompute()
        if inverted_visibility:
            if _valid_solid(result.Shape):
                result.ViewObject.Visibility = True
            else:
                MarzLogger.warn('[Marz Body] {} cannot replace visible blank: '
                                'finished result has no valid solid; {}'
                                .format(result.Label, result.BuildStatus))
        # The native blank is in the SVG source frame; the finished result
        # carries the guitar-position transform. Always hide the blank, so
        # an unpositioned, uncut extrusion cannot mask the finished body.
        if hasattr(extrusion.ViewObject, 'Visibility'):
            extrusion.ViewObject.Visibility = False
    return (doc.getObject(BodyTopPart.name), doc.getObject(BodyBackPart.name))
