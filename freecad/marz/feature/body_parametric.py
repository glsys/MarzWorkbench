# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Native editable body extrusions and recomputable, linked body finishes.

The two halves share one editable contour. Native Part::Extrusion objects own
height and direction; their finished results retain the original Marz cutting
sequence (pocket compounds, neck pocket, then ergonomic cutaways). Normal
FreeCAD recomputation never recreates upstream sketches or cutter shapes.
"""

import json

import Part  # type: ignore

from freecad.marz.extension.fc import App, Vector, Placement
from freecad.marz.extension.paths import iconPath
from freecad.marz.feature.document import (BodyContour, BodyPockets,
    BodyTopPockets, BodyBackPockets, BodyErgoCutsTop, BodyErgoCutsBack,
    BodyTopPart, BodyBackPart)
from freecad.marz.feature.logging import MarzLogger


BODY_GROUP = 'Marz_Group_Body'
TOP_GROUP = 'Marz_Group_Body_Top'
BACK_GROUP = 'Marz_Group_Body_Back'


MASTER_CONTOUR_PROFILE = 'Marz_Body_Top_MasterContour'


def _usable_master(master):
    return bool(master is not None
                and master.TypeId == 'Sketcher::SketchObject'
                and getattr(master, 'SVGConversionValid', False)
                and getattr(master, 'SVGElementMap', None))


def _master_contour_item(master):
    try:
        data = json.loads(master.SVGElementMap)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Body Master Sketch has no valid semantic map') from exc
    for item in data.get('elements', []):
        if item.get('role') == 'body-contour' or item.get('id') == 'contour':
            if item.get('indices'):
                return item
    raise ValueError('Body Master Sketch has no contour semantic region')


class MasterContourProfile:
    """Hidden linked contour adapter for the staged Body migration.

    The Body Master Sketch contains the outer contour plus pocket loops and
    references, so feeding the whole sketch to Part::Extrusion would change the
    proven 0.1.66 blank semantics.  This feature exposes only the semantic
    ``contour`` loop while keeping the master itself authoritative/editable.
    """

    def __init__(self, obj):
        obj.Proxy = self
        if 'Source' not in obj.PropertiesList:
            obj.addProperty('App::PropertyLink', 'Source', 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        master = obj.Source
        if not _usable_master(master):
            obj.BuildStatus = 'ERROR: Body Master Sketch unavailable'
            return
        try:
            item = _master_contour_item(master)
            geometry = list(getattr(master, 'Geometry', []))
            edges = [geometry[index].toShape() for index in item['indices']]
            wire = Part.Wire(edges)
            if not wire.isClosed():
                raise ValueError('master contour is open')
            obj.Shape = wire
            # Keep source geometry local and mirror only the already-proven
            # master display placement.  This must not participate in the body
            # placement calculation itself.
            obj.Placement = master.Placement
            obj.BuildStatus = 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] Master contour profile: {}'.format(exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _master_contour_profile(doc, master, group):
    obj = doc.getObject(MASTER_CONTOUR_PROFILE)
    if obj is None:
        obj = doc.addObject('Part::FeaturePython', MASTER_CONTOUR_PROFILE)
        obj.Label = 'Body Master contour profile'
        MasterContourProfile(obj)
        obj.ViewObject.Visibility = False
    elif not isinstance(getattr(obj, 'Proxy', None), MasterContourProfile):
        MasterContourProfile(obj)
    _view(obj)
    obj.Source = master
    _move_to_group(doc, obj, group)
    obj.recompute()
    if getattr(obj, 'BuildStatus', '') != 'OK' or obj.Shape.isNull():
        raise ValueError('Body Master contour profile is invalid: {}'.format(
            getattr(obj, 'BuildStatus', 'unknown error')))
    return obj


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
                 'Marz_Sketch_BodyPockets', 'Marz_Sketch_BodyMaster',
                 'Marz_Sketch_BodyDefaultContour'):
        _move_to_group(doc, doc.getObject(name), body)
    return body


def _source_display(obj):
    """Guitar placement already applied to a Sketcher source (identity otherwise)."""
    if obj is not None and 'MarzBodySketchTransform' in getattr(obj, 'PropertiesList', []):
        return obj.MarzBodySketchTransform
    return Placement()


def _unpositioned_bridge(bridge):
    """Calculate Marz's body anchor in the SVG frame, even after moving its sketch.

    The input's *geometry* is not restored: manual edits to the bridge line
    still affect the body positioning. Only our own display transform is undone.
    """
    if bridge is None or 'MarzBodySketchTransform' not in getattr(bridge, 'PropertiesList', []):
        return bridge
    from types import SimpleNamespace
    shape = bridge.Shape.copy()
    shape.Placement = _source_display(bridge).inverse().multiply(shape.Placement)
    return SimpleNamespace(Shape=shape)


def _position_sketch(sketch, target):
    """Place existing editable SVG geometry in the body frame, once.

    Changing Marz parameters replaces the *previous Marz transform*, not the
    user's sketch placement or poles. Repeated regeneration cannot accumulate
    the neck-length offset. Never move the original archived SVG reference.
    """
    if sketch is None or sketch.TypeId != 'Sketcher::SketchObject':
        return
    previous = _source_display(sketch)
    new_placement = target.multiply(previous.inverse()).multiply(sketch.Placement)
    if 'MarzBodySketchTransform' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyPlacement', 'MarzBodySketchTransform',
                           'Marz SVG', 'Guitar positioning applied to this SVG sketch')
    sketch.Placement = new_placement
    sketch.MarzBodySketchTransform = target


def _position_body_sources(doc, target):
    # Only the established 0.1.x sources participate in Marz's body-frame
    # positioning.  The 0.2 master mirrors the resulting contour placement
    # one-way; it must never become another input to this transform cycle.
    for name in ('Marz_Sketch_BodyContour', 'Marz_Sketch_BodyDefaultContour',
                 'Marz_Sketch_BridgeRef', 'Marz_Sketch_BodyPockets'):
        _position_sketch(doc.getObject(name), target)

    master = doc.getObject('Marz_Sketch_BodyMaster')
    contour = doc.getObject('Marz_Sketch_BodyContour')
    if master is not None and contour is not None:
        master.Placement = contour.Placement
        if 'MarzBodySketchTransform' in getattr(contour, 'PropertiesList', []):
            if 'MarzBodySketchTransform' not in master.PropertiesList:
                master.addProperty('App::PropertyPlacement', 'MarzBodySketchTransform',
                                   'Marz SVG',
                                   'Guitar positioning mirrored from Body contour')
            master.MarzBodySketchTransform = contour.MarzBodySketchTransform


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
                      top_placement=None, back_placement=None, failures=None,
                      source_display=None):
    """Reapply the existing body cutter transforms using linked FreeCAD shapes."""
    if not _valid_solid(blank):
        raise ValueError('Body extrusion did not produce one valid solid')
    shape = blank.copy()
    # Editable sketches and their native extrusions are displayed in guitar
    # coordinates. The existing Marz pocket/cutaway pipeline expects the SVG
    # local frame until the final placement, so undo only our display move.
    if source_display is not None:
        shape.Placement = source_display.inverse().multiply(shape.Placement)
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


class BodyViewProvider:
    """Use the same scripted-Part view-provider pattern as the neck."""

    def __init__(self, icon='body.svg'):
        self.icon = icon

    def attach(self, view):
        pass

    def getIcon(self):
        return iconPath(self.icon)

    def __getstate__(self):
        return self.icon

    def __setstate__(self, state):
        self.icon = state


def _view(obj, icon='body.svg'):
    """Initialize/repair the scripted Part view provider without touching visibility."""
    if obj is None or obj.TypeId != 'Part::FeaturePython':
        return
    view = obj.ViewObject
    if view is None:
        return
    provider = getattr(view, 'Proxy', None)
    if not isinstance(provider, BodyViewProvider) or provider.icon != icon:
        view.Proxy = BodyViewProvider(icon)


class BodyResult:
    """FreeCAD recompute proxy for derived cuts; all geometry inputs are Links."""

    def __init__(self, obj):
        obj.Proxy = self
        for name in ('Blank', 'TopExtrusion', 'GlobalPockets', 'SidePockets', 'NeckPocket',
                     'ErgoTop', 'ErgoBack'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyLink', name, 'Marz construction')
        for name in ('BodyPlacement', 'TopPlacement', 'BackPlacement', 'SourceDisplay'):
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
                failures=failures,
                source_display=obj.SourceDisplay)
            obj.Shape = result
            obj.BuildStatus = ('INCOMPLETE: ' + '; '.join(failures)) if failures else 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] {}: {}'.format(obj.Label, exc))
            # Do not overwrite a previously valid solid with an empty result.

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _body_debug(label, obj):
    """Report native body dependency state after explicit regeneration."""
    if obj is None:
        MarzLogger.warn('[Marz Body debug] {}: missing object'.format(label))
        return
    shape = getattr(obj, 'Shape', None)
    if shape is None or shape.isNull():
        shape_info = 'null'
    else:
        bounds = getattr(shape, 'BoundBox', None)
        shape_info = 'solids={} valid={}'.format(len(shape.Solids), shape.isValid())
        if bounds is not None:
            shape_info += ' bounds=({:.2f}..{:.2f}, {:.2f}..{:.2f}, {:.2f}..{:.2f})'.format(
                bounds.XMin, bounds.XMax, bounds.YMin, bounds.YMax,
                bounds.ZMin, bounds.ZMax)
    placement = getattr(obj, 'Placement', None)
    visibility = (obj.ViewObject.Visibility if obj.ViewObject is not None
                  else 'no view')
    status = getattr(obj, 'BuildStatus', 'n/a')
    MarzLogger.warn('[Marz Body debug] {} ({}, {}): placement={} visible={} '
                    'status={} shape={}'.format(label, obj.Name, obj.TypeId,
                                                 placement, visibility, status,
                                                 shape_info))


def _native_extrusion(doc, name, label, source, length, group,
                      source_display, target_display):
    """Part::Extrusion uses a positioned Link to one shared contour.

    The editable contour lives on the Body Top plane.  Each lightweight Link
    gets its own explicit placement: the Top follows that plane, while the Back
    is shifted to the Back plane before extrusion.  Keeping LinkTransform off
    makes this placement unambiguous and still preserves any manual placement
    delta made to the shared Sketcher source.
    """
    link_name = name + '_ContourLink'
    link = doc.getObject(link_name)
    if link is None:
        link = doc.addObject('App::Link', link_name)
        link.Label = 'Shared body contour'
    link.LinkedObject = source
    # With LinkTransform=False FreeCAD uses the Link's own Placement instead
    # of silently inheriting the linked Sketch placement.  Move the current
    # source from its generated Top display frame into this half's body frame;
    # any user-added Sketch placement remains in the composed result.
    link.LinkTransform = False
    link.Placement = target_display.multiply(source_display.inverse()).multiply(
        source.Placement)
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
    # Extrude along the half's own local +Z.  In particular the Back link now
    # starts at the Back plane instead of incorrectly growing upward from Top.
    obj.Dir = link.Placement.Rotation.multVec(Vector(0, 0, 1))
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
    _view(obj)
    _move_to_group(doc, obj, group)
    return obj


class PocketCutters:
    """Derived body cutters linked to the *editable* shared pocket sketch."""

    def __init__(self, obj):
        obj.Proxy = self
        if 'Source' not in obj.PropertiesList:
            obj.addProperty('App::PropertyLink', 'Source', 'Marz construction')
        if 'SourceDisplay' not in obj.PropertiesList:
            obj.addProperty('App::PropertyPlacement', 'SourceDisplay', 'Marz construction')
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
                # Translate the displayed sketch back to SVG-local space so
                # the original pocket start/depth parameters remain unchanged.
                wire.Placement = obj.SourceDisplay.inverse().multiply(sketch.Placement)
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
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _pocket_cutters(doc, group, sketch, source_display):
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
        _view(obj)
        obj.Source = sketch
        obj.SourceDisplay = source_display
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
    top_placement, back_placement = bodyd.placements(_unpositioned_bridge(bridge))
    # The body Top defines the editable master sketch plane. Both halves now
    # consume the same semantic master contour while retaining their independent
    # Top/Back target placements.
    _position_body_sources(doc, top_placement)
    contour_display = _source_display(contour)
    master = doc.getObject('Marz_Sketch_BodyMaster')
    top_source = contour
    top_source_display = contour_display
    if _usable_master(master):
        top_source = _master_contour_profile(doc, master, top_group)
        top_source_display = _source_display(master)

    pocket_sketch = doc.getObject('Marz_Sketch_BodyPockets')
    linked_pockets = (_pocket_cutters(doc, body, pocket_sketch,
                                     _source_display(pocket_sketch))
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
        half_placement = top_placement if side == 'top' else back_placement
        profile_source = top_source
        profile_display = top_source_display
        extrusion = _native_extrusion(doc, 'Marz_Body_' + side.title() + '_Extrusion',
                                      side.title() + ' blank (Part Extrusion)',
                                      profile_source, thickness, group, profile_display,
                                      half_placement)
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
        result.BodyPlacement = half_placement
        # The native blank is already located in this half's generated frame.
        # Undo that frame for the legacy SVG-local pocket cuts, then reapply it.
        result.SourceDisplay = half_placement
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
        # The native blank is positioned correctly but remains an uncut
        # construction stage. Keep it hidden by default so it cannot mask the
        # finished body result.
        if hasattr(extrusion.ViewObject, 'Visibility'):
            extrusion.ViewObject.Visibility = False
        _body_debug('Master contour profile' if profile_source is not contour
                    else 'Legacy body contour', profile_source)
        _body_debug('Contour link', extrusion.Base)
        _body_debug('Native extrusion', extrusion)
        _body_debug('Finished ' + side, result)
        MarzLogger.warn('[Marz Body debug] {} extrusion Base={} LinkedObject={} '
                        'Dir={} LengthFwd={} source_display={} body_placement={}'
                        .format(side, extrusion.Base.Name,
                                getattr(extrusion.Base.LinkedObject, 'Name', None),
                                extrusion.Dir, extrusion.LengthFwd,
                                profile_display, result.BodyPlacement))
    return (doc.getObject(BodyTopPart.name), doc.getObject(BodyBackPart.name))
