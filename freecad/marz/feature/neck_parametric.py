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


def _solid_shape(shape):
    """OCC Booleans can return a non-null *empty* compound on failure."""
    return (shape is not None and not shape.isNull()
            and len(shape.Solids) > 0 and abs(shape.Volume) > 1e-7)


def _shape_info(shape):
    if shape is None:
        return 'missing'
    if shape.isNull():
        return 'null'
    faces, solids = len(shape.Faces), len(shape.Solids)
    if not faces and not solids:
        return 'empty (faces=0 solids=0)'
    bounds = shape.BoundBox
    try:
        valid = shape.isValid()
    except Exception:
        valid = 'unknown'
    return ('faces={} solids={} valid={} volume={:.3f} mm^3 '
            'bounds=({:.2f}..{:.2f}, {:.2f}..{:.2f}, {:.2f}..{:.2f})').format(
                faces, solids, valid, shape.Volume,
                bounds.XMin, bounds.XMax, bounds.YMin, bounds.YMax,
                bounds.ZMin, bounds.ZMax)


def _covers_both(candidate, a, b, tolerance=0.1):
    """Reject OCC's nonempty but incomplete/disconnected Boolean results."""
    if not _solid_shape(candidate) or len(candidate.Solids) != 1 or not candidate.isValid():
        return False
    # A valid-looking solid can still omit most of an operand. A proper
    # union cannot have less volume than either input or exceed their sum.
    largest = max(abs(a.Volume), abs(b.Volume))
    combined = abs(a.Volume) + abs(b.Volume)
    if (abs(candidate.Volume) < largest - max(1.0, largest * 0.01) or
            abs(candidate.Volume) > combined + max(1.0, combined * 0.01)):
        return False
    bounds = candidate.BoundBox
    for axis in ('X', 'Y', 'Z'):
        lower = min(getattr(a.BoundBox, axis + 'Min'),
                    getattr(b.BoundBox, axis + 'Min'))
        upper = max(getattr(a.BoundBox, axis + 'Max'),
                    getattr(b.BoundBox, axis + 'Max'))
        if (getattr(bounds, axis + 'Min') > lower + tolerance or
                getattr(bounds, axis + 'Max') < upper - tolerance):
            return False
    return True


def _fuse_headstock(blank, head, report, warning, failed):
    """Fuse using the original OCC call, then tighter/shape-repaired inputs.

    The stock fuzzy fuse may return a *non-null empty compound* without raising.
    Only accept a single, valid solid spanning both source parts, never a
    compound of disconnected pieces or a neck blank lacking its headstock.
    """
    def input_variants():
        yield 'original', blank, head
        # OCC can fail to fuse an unorientable Gordon shell. Repair *copies*
        # of both sources, leaving the editable objects unchanged. Do not
        # repair preemptively if the ordinary fuse works.
        for tolerance in (0.01, 0.1):
            try:
                repaired_blank, repaired_head = blank.copy(), head.copy()
                repaired_blank.fix(tolerance, 0, 1)
                repaired_head.fix(tolerance, 0, 1)
                report('Repaired neck blank ({:.3g} mm)'.format(tolerance), repaired_blank)
                report('Repaired headstock ({:.3g} mm)'.format(tolerance), repaired_head)
                if (_solid_shape(repaired_blank) and _solid_shape(repaired_head) and
                        _covers_both(repaired_blank, blank, blank) and
                        _covers_both(repaired_head, head, head)):
                    yield ('repaired {:.3g} mm'.format(tolerance),
                           repaired_blank, repaired_head)
                else:
                    warning('fusion repair', 'repair {:.3g} mm did not preserve both source solids'.format(tolerance))
            except Exception:
                failed('prepare headstock fuse (repair {:.3g} mm)'.format(tolerance))

    for description, a, b in input_variants():
        for fuzzy in (1e-3, 1e-5, None):
            label = 'Headstock fuse {} {}'.format(
                description, 'default OCC' if fuzzy is None else 'fuzzy {:.3g}'.format(fuzzy))
            try:
                candidate = a.fuse(b) if fuzzy is None else a.fuse([b], fuzzy)
                report(label, candidate)
                if _covers_both(candidate, blank, head):
                    return candidate
                warning(label, 'not one valid solid containing the full blank AND headstock')
            except Exception:
                failed(label)

    return None


class FinishedNeck:
    """Assemble the editable inputs; report and isolate silent OCC failures."""

    def __init__(self, obj):
        obj.Proxy = self
        for name in ('Blank', 'Headstock', 'TopCutter', 'VoluteCutter',
                     'PocketCutter', 'TrussRod'):
            _property(obj, 'App::PropertyLink', name)
        _property(obj, 'App::PropertyFloat', 'HeelFillet', description='Heel fillet radius (mm)')
        self._ensure_debug(obj)

    @staticmethod
    def _ensure_debug(obj):
        if 'Debug' not in obj.PropertiesList:
            _property(obj, 'App::PropertyBool', 'Debug', 'Diagnostics',
                      'Print intermediate geometry and cutting operations to the Report view')
            obj.Debug = True
        _property(obj, 'App::PropertyString', 'BuildStatus', 'Diagnostics',
                  'Last neck assembly status; INCOMPLETE means geometry was omitted')

    def onDocumentRestored(self, obj):
        self._ensure_debug(obj)

    def execute(self, obj):
        from freecad.marz.feature.neck import heel_fillet
        import traceback

        debug = getattr(obj, 'Debug', True)

        def report(stage, shape):
            if debug:
                App.Console.PrintMessage('[Marz Neck] {}: {}\n'.format(stage, _shape_info(shape)))

        def warning(stage, reason):
            MarzLogger.warn('Neck {}: {}'.format(stage, reason))

        def failed(stage):
            MarzLogger.error('Neck {} raised an exception:\n{}'.format(stage, traceback.format_exc()))

        blank = obj.Blank.Shape if obj.Blank else None
        report('Blank', blank)
        if not _solid_shape(blank):
            message = 'No valid neck blank; check Gordon surface and heel cutting plane'
            MarzLogger.error('Neck: {}. {}'.format(message, _shape_info(blank)))
            raise ValueError(message)

        # Preserve the last usable shape, but never misreport a missing
        # headstock or fillet as a successfully completed assembly.
        incomplete = []
        neck = blank.copy()
        head = obj.Headstock.Shape if obj.Headstock else None
        report('Headstock input', head)
        if _solid_shape(head):
            if debug:
                try:
                    distance, _, _ = neck.distToShape(head)
                    App.Console.PrintMessage('[Marz Neck] Blank/headstock minimum gap: {:.6f} mm\n'.format(distance))
                except Exception:
                    failed('headstock proximity check')
            fused = _fuse_headstock(neck, head, report, warning, failed)
            if fused is not None:
                neck = fused
            else:
                incomplete.append('headstock fuse')
                warning('headstock fuse', 'all OCC attempts failed; finished shape will be incomplete')
        else:
            incomplete.append('headstock missing')
            warning('headstock', 'missing or empty; finished shape will be incomplete')

        tools = []
        for name in ('VoluteCutter', 'TopCutter', 'PocketCutter'):
            source = getattr(obj, name)
            shape = source.Shape if source else None
            report(name + ' input', shape)
            if shape is None or shape.isNull():
                if name != 'PocketCutter':
                    warning(name, 'missing or null; cut omitted')
                    incomplete.append(name + ' missing')
                continue
            if not _solid_shape(shape):
                warning(name, 'does not contain a solid; cut omitted')
                incomplete.append(name + ' invalid')
                continue
            tools.append((name, shape))

        # Preserve Marz's original multi-tool cut for the normal path. If OCC
        # silently returns no solid, retry individually to identify the cutter
        # that destroyed the geometry and keep the usable result visible.
        if tools:
            combined_ok = False
            try:
                cut = neck.cut([shape for _, shape in tools], 1e-3)
                report('Combined top/volute/pockets cut', cut)
                combined_ok = _solid_shape(cut)
                if combined_ok:
                    neck = cut
                else:
                    warning('combined cut', 'returned no solid; diagnosing cutters individually')
            except Exception:
                failed('combined cut')
            if not combined_ok:
                for name, tool in tools:
                    try:
                        candidate = neck.cut(tool, 1e-3)
                        report('Individual cut ' + name, candidate)
                        if _solid_shape(candidate):
                            neck = candidate
                        else:
                            warning(name, 'cut removed the entire neck; skipped')
                            incomplete.append(name + ' cut')
                    except Exception:
                        failed('individual cut ' + name)
                        incomplete.append(name + ' cut')

        try:
            refined = neck.removeSplitter()
            report('Refine before heel fillet', refined)
            if _solid_shape(refined):
                neck = refined
            else:
                warning('refine', 'returned no solid; retaining unrefined neck')
                incomplete.append('pre-fillet refine')
        except Exception:
            failed('refine before heel fillet')
            incomplete.append('pre-fillet refine')

        if 'headstock fuse' in incomplete or 'headstock missing' in incomplete:
            warning('heel fillet', 'not attempted: the headstock has not been fused')
            incomplete.append('heel fillet not attempted')
        else:
            # A failed fuse can leave misleading fillet errors. Once the
            # complete solid exists, first try the original heel selector;
            # if OCC still rejects it, retry on a fixed copy, at the requested
            # radius (never silently change the design radius).
            rounded = None
            for label, base in [('original', neck), ('repaired', None)]:
                if label == 'repaired':
                    try:
                        base = neck.copy()
                        base.fix(0.1, 0, 1)
                        report('Pre-fillet repair', base)
                    except Exception:
                        failed('prepare fillet repair')
                        break
                try:
                    candidate = heel_fillet(base, obj.HeelFillet)
                    report('Heel fillet {} (radius {:.3f} mm)'.format(label, obj.HeelFillet), candidate)
                    if _solid_shape(candidate) and candidate.isValid():
                        rounded = candidate
                        break
                    warning('heel fillet ' + label, 'returned an invalid or empty solid')
                except Exception:
                    failed('heel fillet ' + label)
            if rounded is None:
                incomplete.append('heel fillet')
                warning('heel fillet', 'failed at requested radius {:.3f} mm'.format(obj.HeelFillet))
            else:
                neck = rounded

        truss = obj.TrussRod.Shape if obj.TrussRod else None
        report('Truss rod input', truss)
        if truss is not None and not truss.isNull():
            if not _solid_shape(truss):
                warning('truss rod', 'does not contain a solid; cut omitted')
                incomplete.append('truss rod invalid')
            else:
                try:
                    # fix() mutates the shape; do not mutate our last valid copy
                    # if the repair or following cut produces an empty solid.
                    repaired = neck.copy()
                    repaired.fix(0.1, 0, 1)
                    report('Before truss rod cut (after fix)', repaired)
                    if _solid_shape(repaired):
                        carved = repaired.cut(truss, 1e-3)
                        report('Truss rod cut', carved)
                        if _solid_shape(carved):
                            neck = carved
                        else:
                            warning('truss rod', 'cut returned no solid; retaining neck without channel')
                            incomplete.append('truss rod cut')
                    else:
                        warning('truss rod', 'shape repair removed solid; cut omitted')
                        incomplete.append('truss rod repair')
                except Exception:
                    failed('truss rod cut')
                    incomplete.append('truss rod cut')

        try:
            refined = neck.removeSplitter()
            report('Final refine', refined)
            if _solid_shape(refined):
                neck = refined
            else:
                warning('final refine', 'returned no solid; retaining unrefined neck')
                incomplete.append('final refine')
        except Exception:
            failed('final refine')
            incomplete.append('final refine')

        obj.Shape = neck
        obj.BuildStatus = ('INCOMPLETE: ' + ', '.join(incomplete)) if incomplete else 'OK'
        report('Finished neck', obj.Shape)
        App.Console.PrintMessage('[Marz Neck] Assembly status: {}\n'.format(obj.BuildStatus))

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
    # Existing documents need the diagnostics property as well.
    FinishedNeck._ensure_debug(output)
    output.Blank = blank
    for name, obj in cutters.items():
        setattr(output, name, obj)
    if new_tree or regenerate_cutters:
        output.HeelFillet = inst.neck.heelFillet
    output.touch()  # Re-run the pipeline even when only its implementation changed.
    doc.recompute()
    return output
