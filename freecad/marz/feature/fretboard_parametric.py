# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Editable/recomputable FreeCAD construction tree for the fretboard.

The proven Marz geometry functions still generate the compound-radius blank,
nut cutter and fret-slot cutters on explicit regeneration.  Those stages are
persisted as individual document objects.  Imported inlays are native Sketcher
sources with linked derived cutters.  The final fretboard is a FeaturePython
that recomputes only from those persisted construction inputs.
"""

import json
import Part  # type: ignore

from freecad.marz.extension.fc import App, Vector
from freecad.marz.extension.paths import iconPath
from freecad.marz.feature.document import FretboardPart
from freecad.marz.feature.logging import MarzLogger

ROOT_GROUP = 'Marz_Group_Fretboard'
CONSTRUCTION_GROUP = 'Marz_Group_Fretboard_Construction'
SLOT_GROUP = 'Marz_Group_Fretboard_FretSlots'
INLAY_GROUP = 'Marz_Group_Fretboard_InlayCutters'
SLOT_PREFIX = 'Marz_Fretboard_FretSlot_'
INLAY_CUTTER_PREFIX = 'Marz_Fretboard_InlayCutter_'


def _group(doc, name, label, parent=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('App::DocumentObjectGroup', name)
        obj.Label = label
    if parent is not None and obj not in parent.Group:
        parent.addObject(obj)
    return obj


def groups(doc):
    parts = doc.getObject('Marz_Group_Parts') or _group(doc, 'Marz_Group_Parts', 'Generated parts')
    root = _group(doc, ROOT_GROUP, 'Fretboard', parts)
    construction = _group(doc, CONSTRUCTION_GROUP, 'Fretboard construction', root)
    slots = _group(doc, SLOT_GROUP, 'Fret slot cutters', construction)
    inlays = _group(doc, INLAY_GROUP, 'Inlay cutters', construction)
    return root, construction, slots, inlays


def _move(doc, obj, group):
    if obj is None:
        return
    for owner in doc.Objects:
        if (owner is not group and getattr(owner, 'TypeId', '') == 'App::DocumentObjectGroup'
                and obj in owner.Group):
            owner.removeObject(obj)
    if obj not in group.Group:
        group.addObject(obj)


def _valid_shape(shape):
    return shape is not None and not shape.isNull() and shape.isValid()


class FretboardViewProvider:
    def __init__(self, icon='fretboard.svg'):
        self.icon = icon

    def attach(self, view):
        pass

    def getIcon(self):
        return iconPath(self.icon)

    def __getstate__(self):
        return self.icon

    def __setstate__(self, state):
        self.icon = state


def _view(obj, icon='fretboard.svg'):
    if obj is None or obj.TypeId != 'Part::FeaturePython' or obj.ViewObject is None:
        return
    proxy = getattr(obj.ViewObject, 'Proxy', None)
    if not isinstance(proxy, FretboardViewProvider) or proxy.icon != icon:
        obj.ViewObject.Proxy = FretboardViewProvider(icon)


def _feature(doc, name, label, shape, group, visibility=False):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('Part::Feature', name)
        obj.Label = label
        if obj.ViewObject is not None:
            obj.ViewObject.Visibility = visibility
    obj.Shape = shape
    _move(doc, obj, group)
    return obj


def _remove_prefix(doc, prefix, keep):
    for obj in list(doc.Objects):
        if obj.Name.startswith(prefix) and obj.Name not in keep:
            doc.removeObject(obj.Name)


def _wire_from_indices(sketch, indices):
    edges = [sketch.Geometry[index].toShape() for index in indices]
    wire = Part.Wire(edges)
    wire.Placement = sketch.Placement
    if not wire.isClosed():
        raise ValueError('edited inlay profile is open')
    return wire


class InlayCutter:
    def __init__(self, obj):
        obj.Proxy = self
        for kind, name in (('App::PropertyLink', 'Source'),
                           ('App::PropertyVector', 'Position'),
                           ('App::PropertyLength', 'CutLength'),
                           ('App::PropertyInteger', 'Fret')):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        sketch = obj.Source
        if sketch is None:
            return
        try:
            if not getattr(sketch, 'SVGConversionValid', True):
                raise ValueError('inlay sketch is marked invalid')
            data = json.loads(sketch.SVGElementMap)
            solids = []
            direction = Vector(0, 0, -obj.CutLength.Value)
            for profile in data['profiles']:
                wires = [_wire_from_indices(sketch, indices)
                         for indices in profile['wires']]
                if not wires:
                    continue
                solid = Part.Face(wires[0]).extrude(direction)
                for hole in wires[1:]:
                    solid = solid.cut(Part.Face(hole).extrude(direction))
                solid.translate(obj.Position)
                if not _valid_shape(solid) or not solid.Solids:
                    raise ValueError('inlay profile produced no valid solid')
                solids.append(solid)
            if not solids:
                raise ValueError('inlay sketch contains no closed profile')
            obj.Shape = Part.makeCompound(solids)
            obj.BuildStatus = 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Fretboard] {}: {}; retained previous cutter'.format(
                obj.Label, exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj, 'import_fret_inlays.svg')

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


class FretboardResult:
    def __init__(self, obj):
        obj.Proxy = self
        for kind, name in (('App::PropertyLink', 'Blank'),
                           ('App::PropertyLink', 'NutSlot'),
                           ('App::PropertyLinkList', 'FretSlots'),
                           ('App::PropertyLinkList', 'InlayCutters')):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, 'Marz construction')
        if 'BuildStatus' not in obj.PropertiesList:
            obj.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    def execute(self, obj):
        if obj.Blank is None:
            return
        try:
            shape = obj.Blank.Shape
            if not _valid_shape(shape) or not shape.Solids:
                raise ValueError('fretboard blank is invalid')
            tools = [slot.Shape for slot in obj.FretSlots
                     if slot is not None and _valid_shape(slot.Shape)]
            if obj.NutSlot is not None and _valid_shape(obj.NutSlot.Shape):
                tools.append(obj.NutSlot.Shape)
            if tools:
                cut = shape.cut(tuple(tools))
                if not cut.Solids:
                    raise ValueError('fret/nut cuts produced no solid')
                shape = cut.Solids[0].removeSplitter()
            inlays = [cutter.Shape for cutter in obj.InlayCutters
                      if cutter is not None and _valid_shape(cutter.Shape)]
            if inlays:
                shape = shape.cut(Part.makeCompound(inlays))
            if not _valid_shape(shape) or not shape.Solids:
                raise ValueError('finished fretboard is invalid')
            obj.Shape = shape
            failures = [c.BuildStatus for c in obj.InlayCutters
                        if c is not None and getattr(c, 'BuildStatus', 'OK') != 'OK']
            obj.BuildStatus = ('INCOMPLETE: ' + '; '.join(failures)) if failures else 'OK'
        except Exception as exc:
            obj.BuildStatus = 'ERROR: {}'.format(exc)
            MarzLogger.warn('[Marz Fretboard] {}: {}; retained previous result'.format(
                obj.Label, exc))

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        _view(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _result(doc, root):
    obj = doc.getObject(FretboardPart.name)
    previous_shape = None
    if obj is not None and obj.TypeId != 'Part::FeaturePython':
        visible = obj.ViewObject.Visibility if obj.ViewObject is not None else True
        shape = getattr(obj, 'Shape', None)
        if _valid_shape(shape):
            previous_shape = shape.copy()
        doc.removeObject(obj.Name)
        obj = None
    else:
        visible = True
    if obj is None:
        obj = doc.addObject('Part::FeaturePython', FretboardPart.name)
        obj.Label = FretboardPart.label
        FretboardResult(obj)
        if previous_shape is not None:
            # Migration is intentionally non-destructive if the first linked
            # recompute later fails: the old generated solid remains visible.
            obj.Shape = previous_shape
        if FretboardPart.style is not None:
            FretboardPart.style.apply(obj.ViewObject)
        obj.ViewObject.Visibility = visible
    elif not isinstance(getattr(obj, 'Proxy', None), FretboardResult):
        FretboardResult(obj)
    _view(obj)
    _move(doc, obj, root)
    return obj


def _inlay_sketches(doc):
    from freecad.marz.feature.svg_sketch import (FRET_INLAY_SKETCH_PREFIX,
                                                  create_fret_inlay_sketches)
    create_fret_inlay_sketches(doc)
    found = []
    for obj in doc.Objects:
        if obj.Name.startswith(FRET_INLAY_SKETCH_PREFIX) and getattr(obj, 'SVGConversionValid', False):
            found.append((int(obj.FretNumber), obj))
    return sorted(found, key=lambda item: item[0])


def regenerate(inst, fbd, doc):
    """Explicitly rebuild fretboard construction sources; recompute thereafter."""
    from freecad.marz.feature import fretboard as legacy

    root, construction, slot_group, inlay_group = groups(doc)
    blank_shape = legacy.base(inst, fbd)
    nut_shape = legacy.nutSlot(inst, fbd)
    slot_shapes = legacy.fretsCut(inst, fbd)
    if not _valid_shape(blank_shape):
        raise ValueError('Fretboard blank generation failed')

    blank = _feature(doc, 'Marz_Fretboard_Blank', 'Fretboard blank',
                     blank_shape, construction, False)
    nut = _feature(doc, 'Marz_Fretboard_NutSlot', 'Nut slot cutter',
                   nut_shape, construction, False)

    slot_numbers = [index for index in range(len(fbd.frets))
                    if inst.fretboard.isZeroFret or index != 0]
    slots = []
    keep_slots = set()
    for number, shape in zip(slot_numbers, slot_shapes):
        name = SLOT_PREFIX + str(number)
        keep_slots.add(name)
        slots.append(_feature(doc, name, 'Fret {} slot cutter'.format(number),
                              shape, slot_group, False))
    _remove_prefix(doc, SLOT_PREFIX, keep_slots)

    cutters = []
    keep_cutters = set()
    scale_line = fbd.scaleFrame.midLine
    for fret, sketch in _inlay_sketches(doc):
        if fret >= len(fbd.frets):
            continue
        name = INLAY_CUTTER_PREFIX + str(fret)
        keep_cutters.add(name)
        cutter = doc.getObject(name)
        if cutter is None:
            cutter = doc.addObject('Part::FeaturePython', name)
            cutter.Label = 'Fret {} inlay cutter'.format(fret)
            InlayCutter(cutter)
            cutter.ViewObject.Visibility = False
        elif not isinstance(getattr(cutter, 'Proxy', None), InlayCutter):
            InlayCutter(cutter)
        _view(cutter, 'import_fret_inlays.svg')
        cutter.Source = sketch
        cutter.Fret = fret
        cutter.Position = legacy.fretPos(fret, scale_line, inst.fretboard.thickness)
        cutter.CutLength = inst.fretboard.inlayDepth + 1
        _move(doc, cutter, inlay_group)
        cutter.recompute()
        cutters.append(cutter)
    _remove_prefix(doc, INLAY_CUTTER_PREFIX, keep_cutters)

    result = _result(doc, root)
    result.Blank = blank
    result.NutSlot = nut
    result.FretSlots = slots
    result.InlayCutters = cutters
    result.recompute()
    return result
