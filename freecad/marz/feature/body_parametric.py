# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Native editable body extrusions and recomputable, linked body finishes.

The two halves share one editable Body Master sketch.  When Sketcher internal
faces are available, ordinary SVG pockets are native grouped PartDesign Pocket
features fed from semantic InternalFace selections through SubShapeBinders.
Neck-pocket and ergonomic finishing remain transitional linked results. Normal
FreeCAD recomputation never recreates upstream sketches or semantic geometry.
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
MASTER_POCKET_CUTTER_PREFIX = 'Marz_Body_MasterPocketCutters_'
OBSOLETE_MASTER_POCKET_PILOT = 'Marz_Body_MasterPocketPilot'


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




def _master_map(master):
    try:
        return json.loads(master.SVGElementMap)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Body Master Sketch has no valid semantic map') from exc



class MasterPocketCutters:
    """Derived body pocket cutters sourced entirely from Body Master Sketch.

    Geometry, start/depth and Top/Back/Both ownership all come from the
    master's semantic map.  The cutters deliberately remain on the proven
    0.1.66 Boolean finish path; native PartDesign Pocket ownership is a later
    migration step.
    """

    def __init__(self, obj):
        obj.Proxy = self
        for name, kind in (('Source', 'App::PropertyLink'),
                           ('SourceDisplay', 'App::PropertyPlacement')):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, 'Marz construction')
        if 'Target' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'Target', 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        master = obj.Source
        if not _usable_master(master):
            obj.BuildStatus = 'ERROR: Body Master Sketch unavailable'
            return
        try:
            data = _master_map(master)
            geometry = list(getattr(master, 'Geometry', []))
            cutters = []
            for item in data.get('elements', []):
                if item.get('role') != 'pocket' or item.get('target', '') != obj.Target:
                    continue
                indices = item.get('indices') or []
                start = float(item.get('start', 0))
                depth = float(item.get('depth', 0))
                if not indices or start < 0 or depth <= 0:
                    raise ValueError('invalid master pocket {}'.format(item.get('id')))
                edges = [geometry[index].toShape() for index in indices]
                wire = Part.Wire(edges)
                # The master is displayed on the guitar Top plane.  The
                # established Boolean cutter pipeline expects the original
                # SVG-local frame, so undo only Marz's display placement.
                wire.Placement = obj.SourceDisplay.inverse().multiply(master.Placement)
                if not wire.isClosed():
                    raise ValueError('master pocket {} is open'.format(item.get('id')))
                solid = Part.Face(wire).extrude(Vector(0, 0, -depth))
                solid.translate(Vector(0, 0, -start))
                if not _valid_solid(solid):
                    raise ValueError('master pocket {} produced invalid solid'.format(item.get('id')))
                cutters.append(solid)
            obj.Shape = Part.makeCompound(cutters) if cutters else Part.Shape()
            obj.BuildStatus = 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] {}: {}'.format(obj.Label, exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _master_pocket_cutters(doc, group, master):
    """Build the Both/Top/Back cutter subsets directly from the master."""
    targets = {}
    for target, label in (('', 'Both'), ('t', 'Top'), ('b', 'Back')):
        name = MASTER_POCKET_CUTTER_PREFIX + label
        obj = doc.getObject(name)
        if obj is None:
            obj = doc.addObject('Part::FeaturePython', name)
            obj.Label = label + ' pocket cutters (Body Master)'
            MasterPocketCutters(obj)
            obj.ViewObject.Visibility = False
        elif not isinstance(getattr(obj, 'Proxy', None), MasterPocketCutters):
            MasterPocketCutters(obj)
        _view(obj)
        obj.Source = master
        obj.SourceDisplay = _source_display(master)
        obj.Target = target
        _move_to_group(doc, obj, group)
        obj.recompute()
        if getattr(obj, 'BuildStatus', '') != 'OK':
            raise ValueError('{} is invalid: {}'.format(obj.Label, obj.BuildStatus))
        targets[target] = obj
    return targets


def _remove_obsolete_pocket_helpers(doc):
    """Remove staged pilot/legacy cutter objects once the master is authoritative."""
    names = [OBSOLETE_MASTER_POCKET_PILOT]
    names += ['Marz_Body_CombinedPocketCutters_' + suffix
              for suffix in ('Both', 'Top', 'Back')]
    names += ['Marz_Body_SketchCutters_' + suffix
              for suffix in ('Both', 'Top', 'Back')]
    for name in names:
        if doc.getObject(name) is not None:
            doc.removeObject(name)


def _relink_existing_pocket_consumers(doc, cutters):
    """Move already-parametric Body results to master cutters during migration.

    Selective Regenerate Body Top/Back must not leave the untouched half linked
    to a cutter object that is about to be removed.  Re-linking the dependent
    result is a normal recompute, not a reset of that half's authored inputs.
    """
    for side, target in (('Top', 't'), ('Back', 'b')):
        result = doc.getObject('Marz_Body_' + side)
        if (result is None or result.TypeId != 'Part::FeaturePython'
                or 'GlobalPockets' not in result.PropertiesList
                or 'SidePockets' not in result.PropertiesList):
            continue
        history = doc.getObject('Marz_Body_' + side + NATIVE_HISTORY_SUFFIX)
        if history is not None and getattr(result, 'Blank', None) is not None:
            # The native history Tip already contains all ordinary SVG pockets.
            # Never relink the transitional cutter compounds onto it or the
            # untouched half would be cut twice during selective regeneration.
            result.GlobalPockets = None
            result.SidePockets = None
        else:
            result.GlobalPockets = cutters['']
            result.SidePockets = cutters[target]
        result.recompute()


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
                      carve_neck=False, neck_pocket_local=False,
                      ergo_top=None, ergo_back=None,
                      top_placement=None, back_placement=None, failures=None,
                      source_display=None):
    """Reapply the existing body cutter transforms using linked FreeCAD shapes."""
    if not _valid_solid(blank):
        raise ValueError('Body extrusion did not produce one valid solid')
    # The native Part::Extrusion is already in this half's final body frame.
    # Keep it there.  Master/legacy SVG pocket cutters are derived in SVG-local
    # coordinates, so move each cutter into the same body frame before the
    # Boolean.  Do not move the result after a Boolean: OCCT may bake/normalize
    # Shape.Placement during cut(), which made the final body jump when the
    # semantic neckpocket cut first succeeded.  This world-frame cutter model is
    # also the direct precursor to replacing these scripted cuts with native
    # Part/PartDesign subtractive features.
    shape = blank.copy()

    def world_tool(local_tool, shift):
        tool = local_tool.Shape.copy()
        tool.translate(Vector(0, 0, shift))
        tool.Placement = placement.multiply(tool.Placement)
        return tool

    for name, pockets, shift in (
            ('Global pockets', global_pockets, height + top_thickness if back else height),
            ('Side pockets', side_pockets, height)):
        if pockets is None or pockets.Shape.isNull():
            continue
        tool = world_tool(pockets, shift)
        for solid in tool.Solids:
            shape = _cut(shape, solid, name, failures)
    if carve_neck and neck_pocket_local:
        if neck_pocket is None or neck_pocket.Shape.isNull():
            if failures is not None:
                failures.append('Neck pocket: cutter unavailable')
        else:
            # Same path as the ordinary Body Master pockets; only the dedicated
            # depth semantics differ.  The pocket starts at the complete body
            # top, therefore Back uses the Both/global-pocket shift.
            tool = world_tool(
                neck_pocket, height + top_thickness if back else height)
            for solid in tool.Solids:
                shape = _cut(shape, solid, 'Neck pocket', failures)
    if carve_neck and not neck_pocket_local:
        if neck_pocket is None or neck_pocket.Shape.isNull():
            if failures is not None:
                failures.append('Neck pocket: cutter unavailable')
        else:
            # Generated fallback remains on the established world-space path.
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
            for pocket in (obj.GlobalPockets, obj.SidePockets, obj.NeckPocket):
                if pocket is not None and hasattr(pocket, 'BuildStatus') and pocket.BuildStatus != 'OK':
                    failures.append('{}: {}'.format(pocket.Label, pocket.BuildStatus))
            result = finish_body_shape(
                obj.Blank.Shape,
                height=getattr(obj.ExtrusionHeight, 'Value', obj.ExtrusionHeight),
                top_thickness=getattr(obj.TopThickness, 'Value', obj.TopThickness),
                back=obj.IsBack,
                placement=obj.BodyPlacement,
                global_pockets=obj.GlobalPockets,
                side_pockets=obj.SidePockets,
                neck_pocket=obj.NeckPocket,
                carve_neck=obj.CarveNeckPocket,
                neck_pocket_local=isinstance(
                    getattr(getattr(obj, 'NeckPocket', None), 'Proxy', None),
                    MasterNeckPocketCutter),
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
        if 'ExcludedIDs' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'ExcludedIDs', 'Marz construction')
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
            excluded = set(json.loads(obj.ExcludedIDs or '[]'))
            cutters = []
            for item in elements:
                if item['target'] != obj.Target or item.get('id') in excluded:
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


def _pocket_cutters(doc, group, sketch, source_display, excluded_ids=()):
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
        obj.ExcludedIDs = json.dumps(list(excluded_ids), separators=(',', ':'))
        _move_to_group(doc, obj, group)
        obj.recompute()
        targets[target] = obj
    return targets


NATIVE_HISTORY_SUFFIX = '_History'
NATIVE_PAD_PROFILE_SUFFIX = '_PadProfile'
NATIVE_POCKET_PROFILE_PREFIX = '_PocketProfile_'
NATIVE_POCKET_PREFIX = '_Pocket_'


def _master_internal_faces(master):
    """Return selectable Sketcher ``InternalFaceN`` regions in local coordinates."""
    internal = getattr(master, 'InternalShape', None)
    faces = list(getattr(internal, 'Faces', [])) if internal is not None else []
    return [('InternalFace{}'.format(index + 1), face)
            for index, face in enumerate(faces)]


def _semantic_face(master, item):
    indices = item.get('indices') or []
    if not indices:
        raise ValueError('semantic region {} has no geometry'.format(item.get('id')))
    geometry = list(getattr(master, 'Geometry', []))
    edges = [geometry[index].toShape() for index in indices]
    wire = Part.Wire(edges)
    if not wire.isClosed():
        raise ValueError('semantic region {} is open'.format(item.get('id')))
    return Part.Face(wire)


def _shape_area(shape):
    return float(getattr(shape, 'Area', 0.0))


def _common_area(left, right):
    common = left.common(right)
    return _shape_area(common)


def _area_matches(actual, expected):
    tolerance = max(1.0e-7, abs(expected) * 1.0e-6)
    return abs(actual - expected) <= tolerance


def _resolve_master_internal_regions(master):
    """Resolve semantic SVG regions to current ``InternalFaceN`` names.

    Internal-face numbering is deliberately not persisted.  Every explicit
    regeneration rebuilds this map from geometric overlap/containment so the
    PartDesign history follows the current master sketch rather than stale
    ``InternalFaceN`` indices.
    """
    candidates = _master_internal_faces(master)
    if not candidates:
        raise ValueError('Body Master Sketch exposes no InternalFace regions')
    data = _master_map(master)
    contour_item = next((item for item in data.get('elements', [])
                         if item.get('role') == 'body-contour'
                         or item.get('id') == 'contour'), None)
    if contour_item is None:
        raise ValueError('Body Master Sketch has no contour semantic region')
    contour_face = _semantic_face(master, contour_item)
    contour_area = _shape_area(contour_face)
    if contour_area <= 0:
        raise ValueError('Body Master contour has no area')

    # The blank Pad must fill the complete outer body contour.  MakeInternals
    # partitions that contour into multiple selectable faces (body material and
    # every enclosed pocket region), so padding all contained regions recreates
    # the uncut blank without inventing another sketch.
    pad_faces = []
    for name, candidate in candidates:
        area = _shape_area(candidate)
        if area <= 0:
            continue
        if _area_matches(_common_area(candidate, contour_face), area):
            pad_faces.append(name)
    if not pad_faces:
        raise ValueError('Body contour contains no selectable InternalFace regions')

    semantic = {}
    for item in data.get('elements', []):
        if item.get('role') != 'pocket':
            continue
        region = _semantic_face(master, item)
        # A machining profile may intentionally protrude beyond the body
        # contour.  Sketcher InternalFace regions only represent selectable
        # material partitions inside the outer contour, so the native Pocket
        # must cover the in-body intersection rather than the full authored
        # SVG profile.  This is equivalent to the established Boolean path,
        # where geometry outside the body simply removes no material.
        clipped_area = _common_area(region, contour_face)
        if clipped_area <= 0:
            raise ValueError(
                'pocket {} does not intersect the Body contour'.format(item.get('id')))
        matches = []
        matched_area = 0.0
        pad_face_names = set(pad_faces)
        for name, candidate in candidates:
            if name not in pad_face_names:
                continue
            candidate_area = _shape_area(candidate)
            if candidate_area <= 0:
                continue
            overlap = _common_area(candidate, region)
            # MakeInternals partitions the complete body contour.  A semantic
            # pocket therefore need not correspond to exactly one InternalFace:
            # another closed profile (for example neckpocket) can split its
            # in-body portion into several disjoint selectable regions.
            if _area_matches(overlap, candidate_area):
                matches.append(name)
                matched_area += candidate_area
        if not matches or not _area_matches(matched_area, clipped_area):
            raise ValueError(
                'pocket {} InternalFace coverage is incomplete: {} regions, '
                '{:.6f}/{:.6f} mm^2 inside Body contour'.format(
                    item.get('id'), len(matches), matched_area, clipped_area))
        semantic[item['id']] = matches
    return pad_faces, semantic


def _native_operation_groups(master):
    groups = {}
    for item in _master_map(master).get('elements', []):
        if item.get('role') != 'pocket':
            continue
        start = float(item.get('start', 0))
        depth = float(item.get('depth', 0))
        if start < 0 or depth <= 0:
            raise ValueError('invalid master pocket {}'.format(item.get('id')))
        end = start + depth
        key = (item.get('target', ''), start, end)
        groups.setdefault(key, []).append(item['id'])
    return [(target, start, end, ids)
            for (target, start, end), ids in sorted(
                groups.items(), key=lambda pair: (pair[0][0], pair[0][1], pair[0][2]))]


def _operation_intersects_half(side, target, start, end, top_thickness, back_thickness):
    if target == 't':
        return side == 'top' and start < top_thickness and end > 0
    if target == 'b':
        return side == 'back' and start < back_thickness and end > 0
    if target != '':
        return False
    if side == 'top':
        return start < top_thickness and end > 0
    # Both-target depths are measured from the complete body's top surface.
    return start < top_thickness + back_thickness and end > top_thickness


def _offset_vector(master, distance):
    normal = master.Placement.Rotation.multVec(Vector(0, 0, 1))
    return Vector(normal.x * distance, normal.y * distance, normal.z * distance)


def _set_binder_offset(binder, master, distance):
    placement = binder.Placement
    placement.Base = _offset_vector(master, distance)
    binder.Placement = placement


def _profile_binder(history, name, label, master, subnames, offset=0.0):
    binder = history.newObject('PartDesign::SubShapeBinder', name)
    binder.Label = label
    binder.Support = [(master, list(subnames))]
    if hasattr(binder, 'MakeFace'):
        binder.MakeFace = True
    if hasattr(binder, 'Fuse'):
        binder.Fuse = False
    if offset:
        _set_binder_offset(binder, master, offset)
    if binder.ViewObject is not None:
        binder.ViewObject.Visibility = False
    return binder


def _add_operation_metadata(obj, target, start, end, ids):
    for name, kind in (('MarzTarget', 'App::PropertyString'),
                       ('MarzStart', 'App::PropertyLength'),
                       ('MarzEnd', 'App::PropertyLength'),
                       ('MarzSVGIDs', 'App::PropertyString')):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, 'Marz operation')
    obj.MarzTarget = target or 'Both'
    obj.MarzStart = start
    obj.MarzEnd = end
    obj.MarzSVGIDs = ','.join(ids)


def _remove_native_history(doc, side):
    history = doc.getObject('Marz_Body_' + side.title() + NATIVE_HISTORY_SUFFIX)
    if history is not None:
        children = list(getattr(history, 'Group', []))
        for child in reversed(children):
            if doc.getObject(child.Name) is not None:
                doc.removeObject(child.Name)
        if doc.getObject(history.Name) is not None:
            doc.removeObject(history.Name)
    # Migration from the preceding Part::Extrusion stage reuses the established
    # blank name for the native Pad, therefore remove any surviving old objects.
    blank_name = 'Marz_Body_' + side.title() + '_Extrusion'
    if doc.getObject(blank_name) is not None:
        doc.removeObject(blank_name)
    link = doc.getObject(blank_name + '_ContourLink')
    if link is not None:
        doc.removeObject(link.Name)


def _set_native_direction(feature, direction, *, reversed_fallback=False):
    """Use an explicit local-normal vector; binders can otherwise flip normals."""
    if hasattr(feature, 'UseCustomVector') and hasattr(feature, 'Direction'):
        feature.UseCustomVector = True
        feature.Direction = direction
        if hasattr(feature, 'AlongSketchNormal'):
            feature.AlongSketchNormal = False
        feature.Reversed = False
    else:
        feature.Reversed = reversed_fallback


def _native_body_history(doc, side, master, bodyd, group):
    """Build one native PartDesign history from Body Master internal regions."""
    pad_faces, semantic_faces = _resolve_master_internal_regions(master)
    groups = _native_operation_groups(master)
    _remove_native_history(doc, side)

    prefix = 'Marz_Body_' + side.title()
    history = doc.addObject('PartDesign::Body', prefix + NATIVE_HISTORY_SUFFIX)
    history.Label = 'Body {} native history'.format(side.title())
    _move_to_group(doc, history, group)

    pad_profile = _profile_binder(
        history, prefix + NATIVE_PAD_PROFILE_SUFFIX,
        '{} blank regions (Body Master)'.format(side.title()),
        master, pad_faces)
    pad = history.newObject('PartDesign::Pad', prefix + '_Extrusion')
    pad.Label = '{} blank (Part Design Pad)'.format(side.title())
    pad.Profile = pad_profile
    if hasattr(pad, 'AllowMultiFace'):
        pad.AllowMultiFace = True
    pad.Length = bodyd.topThickness if side == 'top' else bodyd.backThickness
    normal = master.Placement.Rotation.multVec(Vector(0, 0, 1))
    pad_direction = (normal if side == 'top' else
                     Vector(-normal.x, -normal.y, -normal.z))
    _set_native_direction(pad, pad_direction, reversed_fallback=(side == 'back'))
    if hasattr(pad, 'Refine'):
        pad.Refine = True
    doc.recompute()
    if not _valid_solid(pad.Shape):
        raise ValueError('{} PartDesign Pad produced no valid solid'.format(side.title()))

    tip = pad
    op_index = 0
    for target, start, end, ids in groups:
        if not _operation_intersects_half(
                side, target, start, end,
                bodyd.topThickness, bodyd.backThickness):
            continue
        op_index += 1
        subnames = []
        for item_id in ids:
            for subname in semantic_faces[item_id]:
                if subname not in subnames:
                    subnames.append(subname)
        # Both/Top pocket starts are measured from the complete body top.
        # Back-only starts are measured from the Top/Back interface.  Moving
        # the binder, not the master sketch, preserves the master-workflow
        # coordinate contract and naturally supports depth-group operations.
        surface = bodyd.topThickness if target in ('', 't') else 0.0
        offset = surface - start
        binder = _profile_binder(
            history,
            prefix + NATIVE_POCKET_PROFILE_PREFIX + '{:03d}'.format(op_index),
            'Pocket profile {} {}..{} mm'.format(target or 'Both', start, end),
            master, subnames, offset)
        pocket = history.newObject(
            'PartDesign::Pocket',
            prefix + NATIVE_POCKET_PREFIX + '{:03d}'.format(op_index))
        pocket.Label = 'Pocket {} {}..{} mm'.format(target or 'Both', start, end)
        pocket.Profile = binder
        if hasattr(pocket, 'AllowMultiFace'):
            pocket.AllowMultiFace = True
        pocket.Length = end - start
        down = Vector(-normal.x, -normal.y, -normal.z)
        _set_native_direction(pocket, down, reversed_fallback=False)
        if hasattr(pocket, 'Refine'):
            pocket.Refine = True
        _add_operation_metadata(pocket, target, start, end, ids)
        doc.recompute()
        if not _valid_solid(pocket.Shape):
            raise ValueError('{} produced no valid solid'.format(pocket.Label))
        tip = pocket

    history.Tip = tip
    if history.ViewObject is not None:
        # The final Marz_Body_Top/Back still owns neck-pocket and ergonomic
        # transitional finishes.  Keep the native history inspectable but avoid
        # rendering its pre-finish solid on top of the final result.
        history.ViewObject.Visibility = False
    return history, pad, tip


def _can_build_native_history(master):
    return bool(_usable_master(master)
                and getattr(master, 'MakeInternals', False)
                and _master_internal_faces(master))


def relink_native_body_master(doc, master):
    """Reconnect surviving native profile binders after explicit SVG reimport.

    Reimport deliberately replaces the master Sketcher object.  Native history
    objects are preserved, so reconnect their LinkSubList supports by semantic
    SVG identity rather than preserving old InternalFace numbers.  Operation
    topology/depth changes remain the job of explicit Regenerate Body.
    """
    if not _can_build_native_history(master):
        return
    pad_faces, semantic_faces = _resolve_master_internal_regions(master)
    for side in ('Top', 'Back'):
        prefix = 'Marz_Body_' + side
        history = doc.getObject(prefix + NATIVE_HISTORY_SUFFIX)
        if history is None:
            continue
        pad_profile = doc.getObject(prefix + NATIVE_PAD_PROFILE_SUFFIX)
        if pad_profile is not None and hasattr(pad_profile, 'Support'):
            pad_profile.Support = [(master, list(pad_faces))]
        index = 1
        while True:
            pocket = doc.getObject(prefix + NATIVE_POCKET_PREFIX + '{:03d}'.format(index))
            binder = doc.getObject(prefix + NATIVE_POCKET_PROFILE_PREFIX + '{:03d}'.format(index))
            if pocket is None and binder is None:
                break
            if pocket is None or binder is None:
                raise ValueError('{} native pocket history is incomplete at operation {}'.format(
                    side, index))
            ids = [value for value in getattr(pocket, 'MarzSVGIDs', '').split(',') if value]
            missing = [value for value in ids if value not in semantic_faces]
            if missing:
                raise ValueError('{} native pocket operation references missing SVG IDs: {}'.format(
                    side, ', '.join(missing)))
            subnames = []
            for value in ids:
                for subname in semantic_faces[value]:
                    if subname not in subnames:
                        subnames.append(subname)
            binder.Support = [(master, subnames)]
            index += 1
    doc.recompute()


def _master_neckpocket_item(master):
    """Return the semantic neckpocket region; never infer it from InternalFaceN."""
    if master is None or not getattr(master, 'SVGElementMap', ''):
        return None
    try:
        import json
        elements = json.loads(master.SVGElementMap).get('elements', [])
    except (TypeError, ValueError):
        return None
    for item in elements:
        if item.get('id') == 'neckpocket' and item.get('indices'):
            return item
    return None


class MasterNeckPocketCutter:
    """Recomputable cutter from the Body Master Sketch ``neckpocket`` profile.

    The master lies on the Top/Back interface. ``Depth`` keeps Marz's existing
    meaning: measured from the body top surface down along the body's local -Z.
    The profile may cross or protrude beyond the outer contour; the Boolean
    intersection with the body decides what material is actually removed.
    """

    def __init__(self, obj):
        obj.Proxy = self
        for name, kind in (('Source', 'App::PropertyLink'),
                           ('SourceDisplay', 'App::PropertyPlacement')):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, 'Marz construction')
        for name in ('TopThickness', 'Depth'):
            if name not in obj.PropertiesList:
                obj.addProperty('App::PropertyLength', name, 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        master = obj.Source
        item = _master_neckpocket_item(master)
        if master is None or item is None:
            obj.BuildStatus = 'ERROR: Body Master Sketch has no neckpocket profile'
            return
        try:
            depth = getattr(obj.Depth, 'Value', obj.Depth)
            if depth <= 0:
                raise ValueError('neck pocket depth must be positive')
            edges = [master.Geometry[i].toShape() for i in item['indices']]
            wire = Part.Wire(edges)
            # Match the ordinary Body Master pocket contract exactly: keep the
            # cutter in the original SVG-local frame. finish_body_shape() moves
            # it to the body top surface before the Boolean, then applies the
            # half's final guitar placement.
            wire.Placement = obj.SourceDisplay.inverse().multiply(master.Placement)
            if not wire.isClosed():
                raise ValueError('neckpocket profile is open')
            solid = Part.Face(wire).extrude(Vector(0, 0, -depth))
            if not _valid_solid(solid):
                raise ValueError('neckpocket profile produced no valid solid')
            obj.Shape = solid.removeSplitter()
            obj.BuildStatus = 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Body] {}: {}; retained previous cutter'.format(
                obj.Label, exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _master_neck_pocket_cutter(doc, group, master, bodyd):
    if _master_neckpocket_item(master) is None:
        return None
    name = 'Marz_Body_MasterNeckPocketTool'
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('Part::FeaturePython', name)
        obj.Label = 'Neck pocket cutter (Body Master Sketch)'
        MasterNeckPocketCutter(obj)
        obj.ViewObject.Visibility = False
    elif not isinstance(getattr(obj, 'Proxy', None), MasterNeckPocketCutter):
        MasterNeckPocketCutter(obj)
    _view(obj)
    obj.Source = master
    obj.SourceDisplay = _source_display(master)
    obj.TopThickness = bodyd.topThickness
    obj.Depth = bodyd.neckPocketDepth
    _move_to_group(doc, obj, group)
    obj.recompute()
    if obj.BuildStatus != 'OK':
        MarzLogger.warn('[Marz Body] Master neckpocket is authoritative but invalid: {}'
                        .format(obj.BuildStatus))
    return obj


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
    if _usable_master(master):
        # Once the master exists it is the sole Body SVG pocket authority.
        # Remove staged/legacy derived cutter helpers so stale geometry cannot
        # remain linked or appear as a second active pocket path.
        linked_pockets = _master_pocket_cutters(doc, body, master)
        _relink_existing_pocket_consumers(doc, linked_pockets)
        _remove_obsolete_pocket_helpers(doc)
    else:
        linked_pockets = (_pocket_cutters(doc, body, pocket_sketch,
                                         _source_display(pocket_sketch))
                          if _usable(pocket_sketch) else None)
    # Shared neck pocket cutter, not a duplicated hidden Boolean inside each half.
    master = doc.getObject('Marz_Sketch_BodyMaster')
    tool = (_master_neck_pocket_cutter(doc, body, master, bodyd)
            if bodyd.neckPocketCarve else None)
    if bodyd.neckPocketCarve and tool is None:
        tool = doc.getObject('Marz_Body_NeckPocketTool')
        cutter = make_neck_pocket(inst, bodyd.neckd.fbd)
        if cutter is not None:
            if tool is None:
                tool = doc.addObject('Part::Feature', 'Marz_Body_NeckPocketTool')
                tool.Label = 'Neck pocket cutter (generated fallback)'
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
            _remove_native_history(doc, side)
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
        native_tip = None
        native_history = None
        if _can_build_native_history(master):
            try:
                native_history, extrusion, native_tip = _native_body_history(
                    doc, side, master, bodyd, group)
                MarzLogger.warn('[Marz Body] {} ordinary pockets use native grouped '
                                'PartDesign operations'.format(side.title()))
            except Exception as exc:
                MarzLogger.warn('[Marz Body] {} native grouped operations failed: {}; '
                                'retaining proven Boolean pocket path'.format(
                                    side.title(), exc))
                _remove_native_history(doc, side)
                native_history = None
                native_tip = None
        if native_tip is None:
            extrusion = _native_extrusion(
                doc, 'Marz_Body_' + side.title() + '_Extrusion',
                side.title() + ' blank (Part Extrusion)',
                profile_source, thickness, group, profile_display, half_placement)
            blank = extrusion
        else:
            blank = native_tip
        result = _result(doc, part_def.name, part_def.label, group, part_def.style)
        _link(result, 'App::PropertyLink', 'Blank', blank)
        _link(result, 'App::PropertyLink', 'TopExtrusion',
              extrusion if side == 'top' else doc.getObject('Marz_Body_Top_Extrusion'))
        if native_tip is None:
            _link(result, 'App::PropertyLink', 'GlobalPockets',
                  linked_pockets[''] if linked_pockets else BodyPockets.get(doc=doc))
            _link(result, 'App::PropertyLink', 'SidePockets',
                  linked_pockets['t' if side == 'top' else 'b'] if linked_pockets
                  else (BodyTopPockets if side == 'top' else BodyBackPockets).get(doc=doc))
        else:
            # Ordinary SVG pockets are already real PartDesign Pocket features
            # in ``blank``.  Only neck-pocket/ergonomic transitional finishes
            # remain in BodyResult.
            _link(result, 'App::PropertyLink', 'GlobalPockets', None)
            _link(result, 'App::PropertyLink', 'SidePockets', None)
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
        if native_tip is None:
            _body_debug('Contour link', extrusion.Base)
            _body_debug('Native extrusion', extrusion)
            MarzLogger.warn('[Marz Body debug] {} extrusion Base={} LinkedObject={} '
                            'Dir={} LengthFwd={} source_display={} body_placement={}'
                            .format(side, extrusion.Base.Name,
                                    getattr(extrusion.Base.LinkedObject, 'Name', None),
                                    extrusion.Dir, extrusion.LengthFwd,
                                    profile_display, result.BodyPlacement))
        else:
            _body_debug('PartDesign Pad', extrusion)
            _body_debug('PartDesign Tip', native_tip)
        _body_debug('Finished ' + side, result)
    return (doc.getObject(BodyTopPart.name), doc.getObject(BodyBackPart.name))
