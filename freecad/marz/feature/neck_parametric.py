# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Persistent, editable FreeCAD construction history for Marz necks.

Edit spline poles or a Gordon surface pole in the FreeCAD property editor.
The input splines, surface, cutter plane, blank, and finished solid participate
in ordinary document recomputation.  Regeneration from Marz parameters is an
explicit operation so that recompute never silently replaces manual edits.
"""

import math
import re

import Part  # type: ignore

from freecad.marz.extension.fc import App, Vector
from freecad.marz.feature.document import Group_Parts, NeckPart
from freecad.marz.feature.logging import MarzLogger
from freecad.marz.model import gordon_neck as geometry

PREFIX = 'Marz_Neck_'


def _property(obj, kind, name, group='Construction', description=''):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, description)


def _group(doc, name, label, parent=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('App::DocumentObjectGroup', name)
        obj.Label = label
    if parent and obj not in parent.Group:
        parent.addObject(obj)
    return obj


def _object(doc, name, label, proxy=None, group=None, shape=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('Part::FeaturePython' if proxy else 'Part::Feature', name)
        obj.Label = label
        if proxy:
            proxy(obj)
        if shape is not None:
            obj.Shape = shape
        obj.ViewObject.Visibility = False
    if group and obj not in group.Group:
        group.addObject(obj)
    return obj


class Spline:
    """An editable *exact* B-spline: its OCC poles and knot vector are stored.

    Guides default to following the profiles; changing their poles switches
    them to manual mode, while recompute continues to preserve those poles.
    """

    def __init__(self, obj):
        obj.Proxy = self
        _property(obj, 'App::PropertyVectorList', 'Poles', description='Editable B-spline control points')
        _property(obj, 'App::PropertyFloatList', 'Knots')
        _property(obj, 'App::PropertyIntegerList', 'Multiplicities')
        _property(obj, 'App::PropertyInteger', 'Degree')
        _property(obj, 'App::PropertyFloatList', 'Weights')
        _property(obj, 'App::PropertyBool', 'FollowProfiles', description='Regenerate guide when profiles change')
        _property(obj, 'App::PropertyLinkList', 'Profiles')
        _property(obj, 'App::PropertyInteger', 'GuideIndex')
        self._updating = False

    def onChanged(self, obj, prop):
        if (prop in ('Poles', 'Knots', 'Multiplicities', 'Degree', 'Weights')
                and not getattr(self, '_updating', False)
                and 'Restore' not in getattr(obj, 'State', ())):
            if obj.Profiles and obj.FollowProfiles:
                obj.FollowProfiles = False

    def execute(self, obj):
        if obj.FollowProfiles and obj.Profiles:
            edges = [p.Shape.Edges[0] for p in obj.Profiles]
            guides = geometry.create_guides(edges)
            self.set_curve(obj, guides[obj.GuideIndex])
        elif obj.Poles and obj.Knots:
            curve = Part.BSplineCurve()
            weights = list(obj.Weights) if obj.Weights else None
            curve.buildFromPolesMultsKnots(list(obj.Poles), list(obj.Multiplicities),
                                           list(obj.Knots), False, obj.Degree, weights)
            obj.Shape = curve.toShape()

    def set_curve(self, obj, edge):
        curve = edge.Curve.toBSpline(edge.FirstParameter, edge.LastParameter)
        self._updating = True
        try:
            obj.Poles = curve.getPoles()
            obj.Knots = curve.getKnots()
            obj.Multiplicities = curve.getMultiplicities()
            obj.Degree = curve.Degree
            obj.Weights = curve.getWeights()
            obj.Shape = curve.toShape()
        finally:
            self._updating = False

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._updating = False


class GordonSurface:
    """Derived surface with an optional independently edited control net."""

    def __init__(self, obj):
        obj.Proxy = self
        _property(obj, 'App::PropertyLinkList', 'Profiles')
        _property(obj, 'App::PropertyLinkList', 'Guides')
        _property(obj, 'App::PropertyVectorList', 'Poles', description='Editable U-major surface control net')
        _property(obj, 'App::PropertyInteger', 'UPoles')
        _property(obj, 'App::PropertyInteger', 'VPoles')
        _property(obj, 'App::PropertyBool', 'Manual', description='Preserve edited surface poles on recompute')
        self._updating = False

    def onChanged(self, obj, prop):
        if (prop == 'Poles' and not getattr(self, '_updating', False)
                and 'Restore' not in getattr(obj, 'State', ()) and obj.Poles):
            obj.Manual = True

    def execute(self, obj):
        if obj.Manual:
            surface = obj.Shape.Surface.copy()
            if len(obj.Poles) != surface.NbUPoles * surface.NbVPoles:
                raise ValueError('Gordon surface control net size does not match its dimensions')
            for u in range(1, surface.NbUPoles + 1):
                for v in range(1, surface.NbVPoles + 1):
                    surface.setPole(u, v, obj.Poles[(u-1)*surface.NbVPoles + v-1])
            obj.Shape = surface.toShape()
        else:
            face = geometry.interpolate_neck_surface(
                [p.Shape.Edges[0] for p in obj.Profiles],
                [g.Shape.Edges[0] for g in obj.Guides])
            surface = face.Surface
            self._updating = True
            try:
                obj.Shape = face
                obj.UPoles = surface.NbUPoles
                obj.VPoles = surface.NbVPoles
                obj.Poles = [surface.getPole(u, v)
                             for u in range(1, surface.NbUPoles + 1)
                             for v in range(1, surface.NbVPoles + 1)]
            finally:
                self._updating = False

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._updating = False


class NeckBlank:
    def __init__(self, obj):
        obj.Proxy = self
        _property(obj, 'App::PropertyLink', 'Surface')
        _property(obj, 'App::PropertyLink', 'HeelPlane')

    def execute(self, obj):
        obj.Shape = geometry.blank_from_gordon(obj.Surface.Shape.Faces[0],
                                               obj.HeelPlane.Shape.Faces[0])

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


class FinishedNeck:
    def __init__(self, obj):
        obj.Proxy = self
        for name in ('Blank', 'Headstock', 'TopCutter', 'VoluteCutter',
                     'PocketCutter', 'TrussRod'):
            _property(obj, 'App::PropertyLink', name)
        _property(obj, 'App::PropertyFloat', 'HeelFillet', description='Heel fillet radius (mm)')

    def execute(self, obj):
        from freecad.marz.feature.neck import heel_fillet
        blank = obj.Blank.Shape
        neck = blank.fuse([obj.Headstock.Shape], 1e-3)
        cutters = [obj.TopCutter.Shape, obj.VoluteCutter.Shape]
        if obj.PocketCutter and not obj.PocketCutter.Shape.isNull():
            cutters.append(obj.PocketCutter.Shape)
        neck = neck.cut(cutters, 1e-3).removeSplitter()
        try:
            neck = heel_fillet(neck, obj.HeelFillet)
        except Exception:
            MarzLogger.error('Error filleting the heel with radius: {}', obj.HeelFillet)
        if obj.TrussRod and not obj.TrussRod.Shape.isNull():
            neck.fix(0.1, 0, 1)
            try:
                neck = neck.cut(obj.TrussRod.Shape, 1e-3)
            except Exception:
                MarzLogger.warn('Truss rod channel was not carved: degenerate neck geometry.')
        obj.Shape = neck.removeSplitter()

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass


def _source_shapes(inst, fbd, neckd):
    """Generate cutter solids using the original Marz algorithms."""
    from freecad.marz.model.headstock_builder import getTop, BoundProfile
    from freecad.marz.model.neck_profile import getNeckProfile
    profile = BoundProfile(getNeckProfile(inst.neck.profile), fbd.widthAt, neckd.thicknessAt)
    line = fbd.neckFrame.midLine
    pos = Vector(line.start.x, line.start.y, 0)
    angle = math.radians(inst.headStock.angle)
    thickness = inst.headStock.thickness + (0 if angle > 0 else inst.headStock.depth)
    contour, transition = getTop(pos, angle, inst.headStock.width,
                                 inst.headStock.length, profile, 30)
    head = geometry.extrude_headstock_plate(contour, thickness, transition).get()
    top = geometry.top_cut(inst, pos, angle).get()
    pockets = geometry.pocket_cut(angle, pos, inst.headStock.depth).get()
    if inst.headStock.voluteRadius > 0:
        volute = geometry.volute_cutter_arc(inst.headStock.voluteRadius,
                                           transition, thickness, head.normal).get()
    else:
        nut = geometry.neck_profiles(inst, fbd, neckd).nut_edge
        volute = geometry.volute_cutter_flat(transition, thickness, nut, head.normal).get()
    from freecad.marz.feature.neck import trussRodChannel
    line = fbd.neckFrame.midLine
    tr = inst.trussRod
    rod = trussRodChannel(line, tr.start, tr.length, tr.width, tr.depth,
                          tr.headLength, tr.headWidth, tr.headDepth,
                          tr.tailLength, tr.tailWidth, tr.tailDepth).get()
    return {'Headstock': head.solid, 'TopCutter': top,
            'VoluteCutter': volute, 'PocketCutter': pockets, 'TrussRod': rod}


def _sources(doc, inst, fbd, neckd, cutter_group, reset=False):
    shapes = _source_shapes(inst, fbd, neckd) if reset or not doc.getObject(PREFIX + 'Headstock') else {}
    result = {}
    for name in ('Headstock', 'TopCutter', 'VoluteCutter', 'PocketCutter', 'TrussRod'):
        existing = doc.getObject(PREFIX + name)
        shape = shapes.get(name)
        if existing is None and shape is None:
            result[name] = None
            continue
        obj = _object(doc, PREFIX + name, name.replace('Cutter', ' cutter'), group=cutter_group)
        if reset or existing is None:
            obj.Shape = shape if shape is not None else Part.Shape()
        result[name] = obj
    return result


def _heel_plane(doc, edge, inst, cutters, reset=False):
    name = PREFIX + 'HeelPlane'
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject('Part::Plane', name)
        obj.Label = 'Heel cutting plane'
        obj.ViewObject.Visibility = False
    if reset or obj not in cutters.Group:
        plane = geometry.heel_cutting_plane(edge, inst)
        obj.Length = plane.BoundBox.XLength
        obj.Width = plane.BoundBox.YLength
        obj.Placement = plane.Placement
    if obj not in cutters.Group:
        cutters.addObject(obj)
    return obj


def create(inst, fbd, neckd, *, regenerate_splines=False, regenerate_cutters=False):
    """Create or reuse the dependency tree without discarding manual edits."""
    doc = App.ActiveDocument
    root = _group(doc, PREFIX + 'Construction', 'Neck construction',
                  Group_Parts.create(doc))
    profiles_group = _group(doc, PREFIX + 'Profiles', 'Profiles (edit poles)', root)
    guides_group = _group(doc, PREFIX + 'Guides', 'Guides (edit poles)', root)
    cutters_group = _group(doc, PREFIX + 'Cutters', 'Cutting tools', root)
    stages_group = _group(doc, PREFIX + 'Stages', 'Derived geometry', root)

    new_tree = doc.getObject(PREFIX + 'Profile_00') is None
    generate_curves = new_tree or regenerate_splines
    if generate_curves:
        heel, neck, all_edges, selected, guide_edges = geometry.neck_curve_network(inst, fbd, neckd)
    else:
        all_edges = guide_edges = None

    profile_ids = (range(len(all_edges)) if generate_curves else
                   sorted(int(obj.Name[-2:]) for obj in doc.Objects
                          if re.fullmatch(PREFIX + r'Profile_\d{2}', obj.Name)))
    profiles = []
    for idx in profile_ids:
        name = f'{PREFIX}Profile_{idx:02d}'
        obj = _object(doc, name, f'Profile {idx:02d}', Spline, profiles_group)
        if generate_curves:
            obj.Proxy.set_curve(obj, all_edges[idx])
        profiles.append(obj)

    guide_ids = (range(len(guide_edges)) if generate_curves else
                 sorted(int(obj.Name[-2:]) for obj in doc.Objects
                        if re.fullmatch(PREFIX + r'Guide_\d{2}', obj.Name)))
    guides = []
    for idx in guide_ids:
        name = f'{PREFIX}Guide_{idx:02d}'
        obj = _object(doc, name, f'Guide {idx:02d}', Spline, guides_group)
        if generate_curves:
            obj.Profiles = profiles
            obj.GuideIndex = idx
            obj.Proxy.set_curve(obj, guide_edges[idx])
            obj.FollowProfiles = True
        guides.append(obj)

    surface = _object(doc, PREFIX + 'Gordon', 'Gordon surface (editable poles)', GordonSurface, stages_group)
    surface.Profiles = [p for i, p in enumerate(profiles) if i not in geometry.GORDON_PROFILE_EXCLUDE]
    surface.Guides = guides
    if regenerate_splines:
        surface.Manual = False

    # Cutting sources are ordinary FreeCAD Part objects; placements and shapes
    # remain user editable and are not recreated by standard recompute.
    cutters = _sources(doc, inst, fbd, neckd, cutters_group, regenerate_cutters)
    heel_edge = heel.edges[-1] if generate_curves else profiles[-1].Shape.Edges[0]
    heel_plane = _heel_plane(doc, heel_edge, inst, cutters_group,
                             reset=regenerate_cutters)

    blank = _object(doc, PREFIX + 'Blank', 'Trimmed neck blank', NeckBlank, stages_group)
    blank.Surface, blank.HeelPlane = surface, heel_plane

    output = doc.getObject('Marz_Neck')
    if output is None or output.TypeId != 'Part::FeaturePython':
        if output:
            doc.removeObject(output.Name)  # One-time migration of the legacy static neck.
        output = _object(doc, 'Marz_Neck', 'Neck', FinishedNeck, Group_Parts.create(doc))
        NeckPart.style.apply(output.ViewObject)
        output.ViewObject.Visibility = True
    output.Blank = blank
    for name, obj in cutters.items():
        setattr(output, name, obj)
    if new_tree or regenerate_cutters:
        output.HeelFillet = inst.neck.heelFillet
    doc.recompute()
    return output
