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
import hashlib
import traceback

import Part  # type: ignore

from freecad.marz.extension.fc import App, Vector, Placement, Rotation
from freecad.marz.extension.paths import iconPath
from freecad.marz.feature.document import Group_Parts, NeckPart
from freecad.marz.feature.logging import MarzLogger
from freecad.marz.model import gordon_neck as geometry

PREFIX = 'Marz_Neck_'


class NeckViewProvider:
    """Use FreeCAD's built-in Part shape renderer with a type-specific icon.

    The view provider is available only on scripted Part::FeaturePython
    objects. Native Part::Feature objects retain FreeCAD's built-in renderer.
    """

    def __init__(self, icon):
        self.icon = icon

    def attach(self, view):
        pass

    def getIcon(self):
        return iconPath(self.icon)

    def __getstate__(self):
        return self.icon

    def __setstate__(self, state):
        self.icon = state


def _view(obj, icon):
    """Initialize missing view providers, including documents saved before 0.1.29.

    Never modify Visibility here: the user must control which construction
    stages are displayed, independently of regeneration and recomputation.
    """
    # Native Part::Feature cutters use PartGui.ViewProviderPartExt, which
    # has no Proxy attribute (FreeCAD 1.1). Only scripted features support
    # a Python view provider; leave native cutters' view untouched.
    if obj.TypeId != 'Part::FeaturePython':
        return
    view = obj.ViewObject
    if view is None:
        return
    provider = getattr(view, 'Proxy', None)
    if not isinstance(provider, NeckViewProvider) or provider.icon != icon:
        view.Proxy = NeckViewProvider(icon)



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


def _object(doc, name, label, proxy=None, group=None, shape=None, icon='neck_solid.svg'):
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
    _view(obj, icon)
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
        _property(obj, 'App::PropertyBool', 'Edited', description='Control points were manually changed')
        _property(obj, 'App::PropertyString', 'ProfileSignature', 'Construction',
                  'Last set of profiles used to generate this guide')
        self._updating = False

    def onChanged(self, obj, prop):
        if (prop in ('Poles', 'Knots', 'Multiplicities', 'Degree', 'Weights')
                and not getattr(self, '_updating', False)
                and 'Restore' not in getattr(obj, 'State', ())):
            if 'Edited' in obj.PropertiesList:
                obj.Edited = True
            if ('Profiles' in obj.PropertiesList and obj.Profiles and
                    'FollowProfiles' in obj.PropertiesList and obj.FollowProfiles):
                obj.FollowProfiles = False

    @staticmethod
    def profile_signature(profiles):
        # Persist a content signature: a fresh recompute with unchanged inputs
        # must NOT rebuild the original (potentially numerically sensitive)
        # interpolated guide curve.
        source = []
        for profile in profiles:
            source.append((tuple((v.x, v.y, v.z) for v in profile.Poles),
                           tuple(profile.Knots), tuple(profile.Multiplicities),
                           profile.Degree, tuple(profile.Weights)))
        return hashlib.sha256(repr(source).encode('ascii')).hexdigest()

    def execute(self, obj):
        if obj.FollowProfiles and obj.Profiles:
            signature = self.profile_signature(obj.Profiles)
            if obj.ProfileSignature != signature or obj.Edited or obj.Shape.isNull():
                edges = [p.Shape.Edges[0] for p in obj.Profiles]
                guides = geometry.create_guides(edges)
                self.set_curve(obj, guides[obj.GuideIndex])
                obj.ProfileSignature = signature
        elif obj.Edited and obj.Poles and obj.Knots:
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
            # Keep the EXACT input edge. Reconstructing it from pole properties
            # during every recompute changes the source representation used by
            # the original Gordon interpolation, even before a user edits it.
            obj.Shape = edge.copy()
            obj.Edited = False
        finally:
            self._updating = False

    def onDocumentRestored(self, obj):
        self._updating = False
        _property(obj, 'App::PropertyBool', 'Edited')
        _property(obj, 'App::PropertyString', 'ProfileSignature')

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

    # Some OCC versions fail a union across coplanar, overlapping top faces.
    # Subtract the shared material from one operand first; then attempt to
    # join the remaining pieces. Neither original source object is modified.
    for kept, trimmed, desc in ((head, blank, 'trim neck by headstock'),
                                (blank, head, 'trim headstock by neck')):
        try:
            difference = trimmed.cut(kept, 1e-5)
            report('Headstock fuse ' + desc + ' difference', difference)
            if not _solid_shape(difference):
                warning(desc, 'difference contained no remaining solid')
                continue
            for a, b in ((kept, difference), (difference, kept)):
                candidate = a.fuse([b], 1e-5)
                report('Headstock fuse ' + desc + ' result', candidate)
                if _covers_both(candidate, blank, head):
                    return candidate
        except Exception:
            failed('headstock fuse ' + desc)

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
                try:
                    overlap = neck.common(head, 1e-5)
                    report('Blank/headstock common volume (0 means only touching)', overlap)
                except Exception:
                    failed('headstock volume intersection diagnostic')
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


def _sources(doc, inst, fbd, neckd, cutter_group, *,
             reset_cutters=False, reset_headstock=False, reset_trussrod=False):
    """Reset only the selected source family; never overwrite other edits.

    The headstock plate and SVG pockets are now one persistent native
    PartDesign::Body driven by the Headstock Master Sketch. Top/volute cutters
    remain separate neck-assembly tools for the next staged migration step.
    """
    headstock = doc.getObject(PREFIX + 'Headstock')
    migrate_headstock = (headstock is None or headstock.TypeId != 'PartDesign::Body')
    if reset_headstock or migrate_headstock:
        from freecad.marz.feature.headstock_parametric import regenerate_headstock
        headstock = regenerate_headstock(inst, fbd, doc)

    names = ('TopCutter', 'VoluteCutter', 'PocketCutter', 'TrussRod')
    to_reset = set()
    if reset_headstock:
        to_reset.update(('TopCutter', 'VoluteCutter', 'PocketCutter'))
    elif migrate_headstock:
        # The old SVG Boolean pocket cutter must be cleared in the same update
        # that first installs native PartDesign pockets.
        to_reset.add('PocketCutter')
    if reset_cutters:
        to_reset.update(names)
    if reset_trussrod:
        to_reset.add('TrussRod')
    to_reset.update(name for name in names if doc.getObject(PREFIX + name) is None)
    shapes = _source_shapes(inst, fbd, neckd) if to_reset else {}
    result = {'Headstock': headstock}
    for name in names:
        obj = _object(doc, PREFIX + name, name.replace('Cutter', ' cutter'),
                      group=cutter_group, icon='neck_cutter.svg')
        if name in to_reset:
            if name == 'PocketCutter':
                # SVG pockets are already native PartDesign::Pocket features in
                # the headstock Body. Leaving the old Boolean cutter populated
                # would cut the same pockets twice in FinishedNeck.
                obj.Shape = Part.Shape()
            else:
                shape = shapes.get(name)
                obj.Shape = shape if shape is not None else Part.Shape()
        result[name] = obj
    return result


def _heel_plane(doc, edge, inst, cutters, reset=False):
    name = PREFIX + 'HeelPlane'
    obj = doc.getObject(name)
    created = obj is None
    if created:
        obj = doc.addObject('Part::Plane', name)
        obj.Label = 'Heel cutting plane'
        obj.ViewObject.Visibility = False

    # Part.makePlane() stores the world-space origin in its face vertices,
    # NOT necessarily in Shape.Placement. The original heel face has identity
    # Placement even though its bounds are far from (0, 0, 0). Using that
    # Placement on Part::Plane put the editable cutter at the global origin.
    reference = geometry.heel_cutting_plane(edge, inst)
    bounds = reference.BoundBox
    _property(obj, 'App::PropertyBool', 'MarzPlacementInitialized', 'Construction',
              'Whether the editable heel plane has the correct initial world placement')

    # Migrate only the exact legacy-origin cutter created by versions <=0.1.31.
    # A user-moved/resized plane must remain untouched on Update Parts and on
    # normal FreeCAD recompute; Regenerate Neck Cutters explicitly resets it.
    # Part::Plane Length and Width are unit-bearing FreeCAD Quantities; OCC
    # bounding-box dimensions are plain floats in millimetres.
    legacy_at_origin = (
        not obj.MarzPlacementInitialized
        and obj.Placement.Base.Length < 1e-7
        and abs(obj.Length.Value - bounds.XLength) < 1e-4
        and abs(obj.Width.Value - bounds.YLength) < 1e-4
    )
    if created or reset or legacy_at_origin:
        obj.Length = bounds.XLength
        obj.Width = bounds.YLength
        obj.Placement = Placement(Vector(bounds.XMin, bounds.YMin, bounds.ZMin), Rotation())
        obj.MarzPlacementInitialized = True
        if legacy_at_origin and not created:
            App.Console.PrintMessage(
                '[Marz Neck] Corrected legacy heel plane placement to '
                '({:.3f}, {:.3f}, {:.3f}) mm\n'.format(
                    bounds.XMin, bounds.YMin, bounds.ZMin))
    elif not obj.MarzPlacementInitialized:
        # Non-default placements predate the marker too. Treat them as manual
        # edits, not as permission to overwrite the cutter.
        obj.MarzPlacementInitialized = True

    if obj not in cutters.Group:
        cutters.addObject(obj)
    return obj


def _diagnose_original_geometry(doc, inst, fbd, neckd, profiles, guides, surface, blank, output):
    """Automatically locate first deviation from stock Marz construction.

    Diagnostic-only: never substitutes a stock shape for an edited object or
    regenerates a user's poles/cutters. Failures must not abort Update Parts.
    """
    prefix = '[Marz Neck Reference] '

    def log(message):
        App.Console.PrintMessage(prefix + message + '\n')

    def warn(message):
        App.Console.PrintWarning(prefix + message + '\n')

    def comparison(label, reference, editable):
        log('{}: original={} / editable={}'.format(
            label, _shape_info(reference), _shape_info(editable)))
        if reference is None or editable is None or reference.isNull() or editable.isNull():
            return
        try:
            bb1, bb2 = reference.BoundBox, editable.BoundBox
            differences = [abs(getattr(bb1, name) - getattr(bb2, name))
                           for name in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax')]
            log('{}: max bound delta={:.8g} mm, volume delta={:.8g} mm^3, center delta={:.8g} mm'.format(
                label, max(differences), abs(reference.Volume - editable.Volume),
                (reference.CenterOfMass - editable.CenterOfMass).Length))
        except Exception:
            warn('{}: could not compare bounds: {}'.format(label, traceback.format_exc()))

    def curve_comparison(label, original, current):
        # Compare matching fractional parameters, not only coincident bounds:
        # reversed guides and modified interpolation can have identical boxes.
        if current is None or current.isNull() or len(current.Edges) != 1:
            warn('{}: missing/invalid persisted curve'.format(label))
            return
        edge = current.Edges[0]
        deltas = []
        try:
            for i in range(21):
                t = i / 20.0
                a = original.valueAt(original.FirstParameter + t * (original.LastParameter-original.FirstParameter))
                b = edge.valueAt(edge.FirstParameter + t * (edge.LastParameter-edge.FirstParameter))
                deltas.append((a-b).Length)
            log('{}: sampled deviation max={:.9g} mm, endpoints={:.9g}/{:.9g} mm'.format(
                label, max(deltas), deltas[0], deltas[-1]))
        except Exception:
            warn('{}: failed to sample curves: {}'.format(label, traceback.format_exc()))

    log('Starting independent stock-vs-editable geometry comparison (read-only).')
    try:
        heel, _, raw_profiles, selected_profiles, raw_guides = geometry.neck_curve_network(inst, fbd, neckd)
        log('Curve counts: original profiles={} guides={}; editable profiles={} guides={}'.format(
            len(raw_profiles), len(raw_guides), len(profiles), len(guides)))
        for idx, (original, persisted) in enumerate(zip(raw_profiles, profiles)):
            curve_comparison('Profile {:02d}'.format(idx), original, persisted.Shape)
        for idx, (original, persisted) in enumerate(zip(raw_guides, guides)):
            curve_comparison('Guide {:02d}'.format(idx), original, persisted.Shape)

        ref_surface = geometry.interpolate_neck_surface(selected_profiles, raw_guides)
        comparison('Gordon surface', ref_surface, surface.Shape)
        try:
            if ref_surface.Faces and surface.Shape.Faces:
                f1, f2 = ref_surface.Faces[0], surface.Shape.Faces[0]
                u1a, u1b, v1a, v1b = f1.ParameterRange
                u2a, u2b, v2a, v2b = f2.ParameterRange
                deviations = []
                for i in range(7):
                    for j in range(7):
                        u, v = i / 6.0, j / 6.0
                        a = f1.valueAt(u1a + (u1b-u1a)*u, v1a + (v1b-v1a)*v)
                        b = f2.valueAt(u2a + (u2b-u2a)*u, v2a + (v2b-v2a)*v)
                        deviations.append((a-b).Length)
                log('Gordon surface sampled deviation: max={:.9g} mm'.format(max(deviations)))
        except Exception:
            warn('Gordon surface sampling failed: {}'.format(traceback.format_exc()))
        ref_heel_plane = geometry.heel_cutting_plane(heel.edges[-1], inst)
        comparison('Heel cutting plane', ref_heel_plane, blank.HeelPlane.Shape)
        ref_blank = geometry.blank_from_gordon(ref_surface, ref_heel_plane)
        comparison('Trimmed blank', ref_blank, blank.Shape)

        ref_head = _source_shapes(inst, fbd, neckd)['Headstock']
        comparison('Headstock', ref_head, output.Headstock.Shape if output.Headstock else None)
        try:
            ref_fused = ref_blank.fuse([ref_head], 1e-3)
            comparison('Original fuse (before cuts)', ref_fused, None)
            if not _solid_shape(ref_fused):
                warn('Original algorithm ALSO fails to fuse: inspect actual overlap and shape orientation.')
            else:
                log('Original algorithm fuse succeeded: compare earlier stages for the first deviation.')
        except Exception:
            warn('Original fuse raised: {}'.format(traceback.format_exc()))
        try:
            ref_overlap = ref_blank.common(ref_head)
            log('Original blank/headstock common volume={:.9g} mm^3'.format(ref_overlap.Volume))
        except Exception:
            warn('Original common-volume test failed: {}'.format(traceback.format_exc()))
        try:
            current_overlap = blank.Shape.common(output.Headstock.Shape)
            log('Editable blank/headstock common volume={:.9g} mm^3'.format(current_overlap.Volume))
        except Exception:
            warn('Editable common-volume test failed: {}'.format(traceback.format_exc()))
    except Exception:
        warn('Reference geometry comparison failed:\n{}'.format(traceback.format_exc()))
    log('End reference comparison. No document objects were modified.')


def create(inst, fbd, neckd, *, regenerate_splines=False, regenerate_cutters=False,
           regenerate_neck=False, regenerate_headstock=False):
    """Create or reuse the dependency tree without discarding manual edits."""
    doc = App.ActiveDocument
    root = _group(doc, PREFIX + 'Construction', 'Neck construction',
                  Group_Parts.create(doc))
    profiles_group = _group(doc, PREFIX + 'Profiles', 'Profiles (edit poles)', root)
    guides_group = _group(doc, PREFIX + 'Guides', 'Guides (edit poles)', root)
    cutters_group = _group(doc, PREFIX + 'Cutters', 'Cutting tools', root)
    stages_group = _group(doc, PREFIX + 'Stages', 'Derived geometry', root)

    new_tree = doc.getObject(PREFIX + 'Profile_00') is None
    generate_curves = new_tree or regenerate_splines or regenerate_neck
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
        obj = _object(doc, name, f'Profile {idx:02d}', Spline, profiles_group, icon='neck_profile.svg')
        if generate_curves:
            obj.Proxy.set_curve(obj, all_edges[idx])
        profiles.append(obj)

    guide_ids = (range(len(guide_edges)) if generate_curves else
                 sorted(int(obj.Name[-2:]) for obj in doc.Objects
                        if re.fullmatch(PREFIX + r'Guide_\d{2}', obj.Name)))
    guides = []
    for idx in guide_ids:
        name = f'{PREFIX}Guide_{idx:02d}'
        obj = _object(doc, name, f'Guide {idx:02d}', Spline, guides_group, icon='neck_guide.svg')
        if generate_curves:
            obj.Profiles = profiles
            obj.GuideIndex = idx
            obj.Proxy.set_curve(obj, guide_edges[idx])
            obj.ProfileSignature = Spline.profile_signature(profiles)
            obj.FollowProfiles = True
        guides.append(obj)

    surface = _object(doc, PREFIX + 'Gordon', 'Gordon surface (editable poles)', GordonSurface, stages_group, icon='neck_surface.svg')
    surface.Profiles = [p for i, p in enumerate(profiles) if i not in geometry.GORDON_PROFILE_EXCLUDE]
    surface.Guides = guides
    if regenerate_splines or regenerate_neck:
        surface.Manual = False

    # Cutting sources are ordinary FreeCAD Part objects; placements and shapes
    # remain user editable and are not recreated by standard recompute.
    cutters = _sources(doc, inst, fbd, neckd, cutters_group,
                       reset_cutters=regenerate_cutters,
                       reset_headstock=regenerate_headstock,
                       reset_trussrod=regenerate_neck)
    heel_edge = heel.edges[-1] if generate_curves else profiles[-1].Shape.Edges[0]
    heel_plane = _heel_plane(doc, heel_edge, inst, cutters_group,
                             reset=regenerate_cutters or regenerate_neck)

    blank = _object(doc, PREFIX + 'Blank', 'Trimmed neck blank', NeckBlank, stages_group, icon='neck_solid.svg')
    blank.Surface, blank.HeelPlane = surface, heel_plane

    output = doc.getObject('Marz_Neck')
    if output is None or output.TypeId != 'Part::FeaturePython':
        if output:
            doc.removeObject(output.Name)  # One-time migration of the legacy static neck.
        output = _object(doc, 'Marz_Neck', 'Neck', FinishedNeck, Group_Parts.create(doc))
        NeckPart.style.apply(output.ViewObject)
        output.ViewObject.Visibility = True
    # Also initialize the view provider on a previously saved finished neck.
    _view(output, 'neck.svg')
    # Existing documents need the diagnostics property as well.
    FinishedNeck._ensure_debug(output)
    # The previous implementation did not have a persisted "edited" marker.
    # Do not reset any old curves: they may already contain manual edits.
    for curve in profiles + guides:
        _property(curve, 'App::PropertyBool', 'Edited')
        _property(curve, 'App::PropertyString', 'ProfileSignature')
    output.Blank = blank
    for name, obj in cutters.items():
        setattr(output, name, obj)
    if new_tree or regenerate_cutters or regenerate_neck:
        output.HeelFillet = inst.neck.heelFillet
    # A code-only change to the neck blank generator does not automatically
    # mark its FreeCAD object dirty. Update Parts must execute it again.
    blank.touch()
    output.touch()
    doc.recompute()
    # This runs automatically on an incomplete neck, using the SAME document
    # and parameters as the old generator. No user console script is needed.
    if (getattr(output, 'Debug', False) and
            str(getattr(output, 'BuildStatus', '')).startswith('INCOMPLETE')):
        _diagnose_original_geometry(doc, inst, fbd, neckd,
                                    profiles, guides, surface, blank, output)
    return output
