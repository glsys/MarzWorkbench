# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Editable Sketcher sources for SVG reference paths.

Keep Marz's original imported wires alongside the sketches. The sketches are
created only from a valid, already transformed and anchored import shape;
none of the SVG coordinate conversion is repeated here.
"""

from freecad.marz.extension.fc import App
import json

# Source IDs remain unchanged for legacy documents and SVG import metadata.
SKETCH_NAMES = {
    'Marz_Body_Contour': 'Marz_Sketch_BodyContour',
    'Marz_Body_Bridge': 'Marz_Sketch_BridgeRef',
    'Marz_Headstock_Contour': 'Marz_Sketch_HeadstockContour',
    'Marz_Headstock_Transition': 'Marz_Sketch_HeadstockTransition',
}
GROUP_NAME = 'Marz_Group_SVG_Sketches'
POCKET_SKETCH_NAMES = {
    'body': 'Marz_Sketch_BodyPockets',
    'headstock': 'Marz_Sketch_HeadstockPockets',
}


def _configure_sketcher_display_defaults():
    """Hide the curvature comb once; respect later user GUI toggles."""
    if not hasattr(App, 'ParamGet'):  # headless test stubs
        return
    own = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Marz')
    if not own.GetBool('SvgSketchDisplayInitialized', False):
        # FreeCAD 1.1.4: EditModeCoinManager::ParameterObserver.
        App.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher/General').SetBool(
            'BSplineCombVisible', False)
        own.SetBool('SvgSketchDisplayInitialized', True)

# Permitted SVG-to-Sketch geometric drift (mm); topology is still checked.
SVG_SKETCH_TOLERANCE_MM = 0.5
# Only join endpoints already coincident to within a micron; the 0.5 mm
# import-fidelity tolerance is NOT a snapping tolerance.
SVG_ENDPOINT_TOLERANCE_MM = 0.001

# The pilot has one original SVG element per sketch. This is the first form of
# the geometry-index map required by the eventual one-sketch-per-SVG importer.
# Store the *SVG* ID, not the generated FreeCAD object name; Marz's pocket
# identifiers encode starting depth, cutting depth and side in that ID.
SOURCE_IDS = {
    'Marz_Body_Contour': ('body', 'contour'),
    'Marz_Body_Bridge': ('body', 'bridge'),
    'Marz_Headstock_Contour': ('headstock', 'contour'),
    'Marz_Headstock_Transition': ('headstock', 'transition'),
}


def _persist_source_ids(sketch, source_name, geometry_indices=None):
    """Persist a stable SVG-ID -> Sketcher geometry-index association."""
    source_document, element_id = SOURCE_IDS[source_name]
    if 'SVGSourceName' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyString', 'SVGSourceName', 'Marz SVG',
                           'Original Marz reference object')
    if 'SVGSourceDocument' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyString', 'SVGSourceDocument', 'Marz SVG',
                           'Imported SVG category (body or headstock)')
    if 'SVGElementMap' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyString', 'SVGElementMap', 'Marz SVG',
                           'JSON: SVG element ID and associated Sketcher geometry indices')
    sketch.SVGSourceName = source_name
    sketch.SVGSourceDocument = source_document
    # Exposing B-spline poles creates Sketcher *internal construction* geometry.
    # Those helper indices must not be mistaken for SVG source elements.
    indices = (list(range(sketch.GeometryCount)) if geometry_indices is None
               else list(geometry_indices))
    sketch.SVGElementMap = json.dumps({
        'version': 1,
        'elements': [{'id': element_id, 'indices': indices}],
    }, separators=(',', ':'), sort_keys=True)


def _show_overlay(source, sketch):
    """Compare imported reference (red) and Sketcher result (green) in 3D."""
    # Never move the imported wire or the sketch merely to improve the view.
    # Only exact-geometry translation correction (below) may alter Placement.
    source.ViewObject.Visibility = True
    sketch.ViewObject.Visibility = True
    offset = sketch.Shape.BoundBox.Center - source.Shape.BoundBox.Center
    App.Console.PrintMessage('[Marz SVG] Overlay: red=imported reference, '
                             'green=Sketcher, relative center '
                             f'({offset.x:.6g}, {offset.y:.6g}, {offset.z:.6g}) mm\n')
    for view, rgb, width in ((source.ViewObject, (1.0, 0.0, 0.0), 3.0),
                             (sketch.ViewObject, (0.0, 1.0, 0.0), 2.0)):
        if 'LineColor' in view.PropertiesList:
            view.LineColor = rgb
        if 'LineWidth' in view.PropertiesList:
            view.LineWidth = width


def _align_pure_translation(original, sketch, tolerance=1e-4):
    """Correct Draft's global offset only if *all* geometry becomes exact."""
    delta = original.BoundBox.Center - sketch.Shape.BoundBox.Center
    if delta.Length <= tolerance:
        return False
    placement = sketch.Placement
    previous_base = placement.Base
    try:
        placement.Base = previous_base + delta
        sketch.Placement = placement
        sketch.recompute()
        if _shape_difference(original, sketch.Shape, tolerance) is None:
            App.Console.PrintMessage('[Marz SVG] Corrected rigid Sketcher offset '
                                     f'({delta.x:.6g}, {delta.y:.6g}, {delta.z:.6g}) mm\n')
            return True
    finally:
        # Do not hide an actual shape change by centering a rejected sketch.
        if _shape_difference(original, sketch.Shape, tolerance) is not None:
            placement.Base = previous_base
            sketch.Placement = placement
            sketch.recompute()
    return False


def _initial_endpoint_constraints(source_shape, draft_sketch):
    """Build Sketcher joins from the *original* connected SVG wire edges.

    Draft's Bezier -> BSpline conversion may shift individual curve endpoints.
    Detecting coincident points on the converted sketch therefore misses
    connections. Match the source endpoints to each converted curve even
    when Draft changes the curve ordering or orientation. Map them to
    the corresponding native constraints before the final
    Sketcher object is recomputed for the first time.
    """
    from Sketcher import Constraint

    edges = source_shape.Edges
    geometry = draft_sketch.Geometry
    if len(edges) != len(geometry):
        raise ValueError('Draft changed edge count; cannot map SVG connections '
                         f'({len(edges)} -> {len(geometry)})')

    def target_points(geom):
        if type(geom).__name__ in ('Circle', 'Ellipse'):
            return None
        try:
            return (draft_sketch.Placement.multVec(geom.StartPoint),
                    draft_sketch.Placement.multVec(geom.EndPoint))
        except (AttributeError, TypeError):
            return None

    targets = [target_points(geom) for geom in geometry]
    sources = []
    for index, edge in enumerate(edges):
        start = edge.valueAt(edge.FirstParameter)
        end = edge.valueAt(edge.LastParameter)
        if (start - end).Length > SVG_ENDPOINT_TOLERANCE_MM:
            sources.append((index, start, end))

    # Match source edges to Sketcher geometry by *world endpoints*, not
    # enumeration: a change of edge order must not connect wrong curves.
    options = []
    for index, start, end in sources:
        candidates = []
        for target_idx, target in enumerate(targets):
            if target is None:
                continue
            first, last = target
            direct = max((start - first).Length, (end - last).Length)
            reverse = max((start - last).Length, (end - first).Length)
            cost = min(direct, reverse)
            if cost <= SVG_SKETCH_TOLERANCE_MM:
                candidates.append((cost, target_idx,
                                   (1, 2) if direct <= reverse else (2, 1)))
        candidates.sort()
        if not candidates:
            raise ValueError(f'Draft edge for SVG edge {index} cannot be mapped '
                             'within the 0.5 mm conversion tolerance')
        options.append(candidates)

    matches = {}  # target index -> source index in sources
    def assign(source_idx, visited):
        for _, target_idx, positions in options[source_idx]:
            if target_idx in visited:
                continue
            visited.add(target_idx)
            previous = matches.get(target_idx)
            if previous is None or assign(previous, visited):
                matches[target_idx] = (source_idx, positions)
                return True
        return False

    for source_idx in range(len(sources)):
        if not assign(source_idx, set()):
            raise ValueError('Draft geometry cannot be matched one-to-one to '
                             'the connected SVG edges')

    endpoints = []
    for target_idx, (source_idx, (first, last)) in matches.items():
        _, start, end = sources[source_idx]
        endpoints.extend(((start, target_idx, first),
                          (end, target_idx, last)))

    # Connect all source endpoints at a shared vertex with a spanning tree.
    # Avoid redundant pairwise constraints at 3+-way junctions.
    clusters = []
    for point, geom_idx, pos in endpoints:
        for members in clusters:
            if (point - members[0][0]).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                members.append((point, geom_idx, pos))
                break
        else:
            clusters.append([(point, geom_idx, pos)])
    joins = []
    for cluster in clusters:
        for _, other_idx, other_pos in cluster[1:]:
            _, first_idx, first_pos = cluster[0]
            if other_idx != first_idx:
                joins.append(Constraint('Coincident', first_idx, first_pos,
                                        other_idx, other_pos))
    return joins




def _contour_bspline_geometry(source_shape):
    """Rebuild SVG contour *paths*, not their independently imported edges.

    The current Marz SVG importer represents each cubic SVG segment as a
    separate Part edge. Draft.make_sketch retains that fragmentation: a set of
    coincident Sketcher B-splines is not one editable spline. For the two
    contour references we can preserve the *exact* source path as one cubic,
    multi-span B-spline, with a knot at every original SVG segment boundary.

    Only complete cubic Beziers and straight segments are eligible. Do not
    approximate unsupported geometry: return None and use the existing Draft
    path instead. No external FreeCAD workbench is required.
    """
    import Part

    edges = list(source_shape.Edges)
    if not edges:
        return None
    segments = []
    for edge in edges:
        curve = edge.Curve
        kind = type(curve).__name__
        if kind == 'BezierCurve' and curve.Degree == 3:
            poles = list(curve.getPoles())
            if len(poles) != 4 or (hasattr(curve, 'isRational')
                                   and curve.isRational()):
                return None
        elif kind == 'BSplineCurve' and curve.Degree == 1:
            source_poles = list(curve.getPoles())
            if len(source_poles) != 2:
                return None
            start, end = source_poles
            poles = [start, start + (end - start) / 3.0,
                     start + (end - start) * (2.0 / 3.0), end]
        elif kind == 'BSplineCurve' and curve.Degree == 3:
            # Accept an untrimmed, single-span polynomial cubic as well.
            source_poles = list(curve.getPoles())
            if (len(source_poles) != 4 or len(curve.getKnots()) != 2
                    or (hasattr(curve, 'getWeights') and any(
                        abs(w - 1.0) > 1e-12 for w in curve.getWeights()))):
                return None
            poles = source_poles
        else:
            return None
        # Refuse trimmed curves, which require a true Bezier extraction before
        # assembling poles. Never substitute an untrimmed control polygon.
        first, last = (edge.valueAt(edge.FirstParameter),
                       edge.valueAt(edge.LastParameter))
        if ((poles[0] - first).Length <= SVG_ENDPOINT_TOLERANCE_MM and
                (poles[-1] - last).Length <= SVG_ENDPOINT_TOLERANCE_MM):
            pass
        elif ((poles[-1] - first).Length <= SVG_ENDPOINT_TOLERANCE_MM and
              (poles[0] - last).Length <= SVG_ENDPOINT_TOLERANCE_MM):
            poles.reverse()
        else:
            return None
        segments.append(poles)

    # Restore the original SVG path ordering, even if FreeCAD reorders edges.
    # A contour must consist of a single, nonbranching closed path. Branches
    # and multiple disconnected wires require the future full-SVG importer.
    ordered = [segments.pop(0)]
    while segments:
        end = ordered[-1][-1]
        candidates = []
        for i, poles in enumerate(segments):
            if (poles[0] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                candidates.append((i, False))
            elif (poles[-1] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                candidates.append((i, True))
        if len(candidates) != 1:
            return None
        i, reversed_direction = candidates[0]
        poles = segments.pop(i)
        if reversed_direction:
            poles.reverse()
        ordered.append(poles)

    if (ordered[-1][-1] - ordered[0][0]).Length > SVG_ENDPOINT_TOLERANCE_MM:
        return None

    # [4, 3, 3, ..., 3, 4] = a single degree-three curve with C0 joins.
    # Sharing the pole at every join guarantees geometric connectivity as the
    # user moves poles. It also preserves intentional SVG corners; forcing
    # C1/G1 or fewer knots would alter the source curve's shape.
    poles = list(ordered[0])
    for segment in ordered[1:]:
        poles.extend(segment[1:])
    poles[-1] = poles[0]  # exact closure at the final knot
    count = len(ordered)
    bspline = Part.BSplineCurve()
    bspline.buildFromPolesMultsKnots(
        poles, [4] + [3] * (count - 1) + [4],
        [float(i) for i in range(count + 1)], False, 3)
    return [bspline]





def svg_pocket_primitive_types(svg_path):
    """Read SVG element types by *original* ID, before importSVG loses them.

    Parsing source metadata does not change Marz's existing coordinate/anchor
    pipeline. Only recognized SVG geometry tags influence Sketcher conversion.
    """
    from xml.etree import ElementTree
    types = {}
    for element in ElementTree.parse(svg_path).iter():
        kind = element.tag.rsplit('}', 1)[-1]
        if kind in ('circle', 'ellipse'):
            element_id = element.get('id')
            if element_id:
                types[element_id] = kind
    return types


def _sample_pocket_edges(wire):
    """Sample actual imported edges, not just their control polygons."""
    return [point for edge in wire.Edges
            for point in edge.discretize(Number=65)]


def _sample_extents(points):
    """Do not use Shape.BoundBox: B-spline control polygons can overshoot."""
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    zs = [point.z for point in points]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _fitted_circle(wire, tolerance):
    """Recover a native circle from imported spline geometry by sampling."""
    import Part
    from math import hypot
    points = _sample_pocket_edges(wire)
    if not points:
        return None
    xmin, xmax, ymin, ymax, zmin, zmax = _sample_extents(points)
    if min(xmax - xmin, ymax - ymin) <= 1e-7 or zmax - zmin > 0.001:
        return None
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    r = (xmax - xmin + ymax - ymin) / 4
    if all(abs(hypot(point.x - cx, point.y - cy) - r) <= tolerance
           for point in points):
        return Part.Circle(App.Vector(cx, cy, zmin),
                           App.Vector(0, 0, 1), r)
    return None


def _fitted_axis_ellipse(wire, tolerance=0.01):
    """Use a native ellipse for axis-aligned imported SVG ellipses.

    Rotated/skewed or nonelliptical wires fall back to their exact B-splines
    instead of replacing them with an inaccurate oval.
    """
    import Part
    from math import hypot
    points = _sample_pocket_edges(wire)
    if not points:
        return None
    xmin, xmax, ymin, ymax, zmin, zmax = _sample_extents(points)
    a, b = (xmax - xmin) / 2, (ymax - ymin) / 2
    if min(a, b) <= 1e-7 or zmax - zmin > 0.001:
        return None
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    if any(abs(hypot((point.x - cx) / a,
                     (point.y - cy) / b) - 1) * max(a, b) > tolerance
           for point in points):
        return None
    center = App.Vector(cx, cy, zmin)
    major = App.Vector(cx + a, cy, zmin)
    minor = App.Vector(cx, cy + b, zmin)
    if b > a:
        major, minor = minor, major
    return Part.Ellipse(major, minor, center)


def _straight_edge_vertices(edge):
    """Return endpoints when the entire imported edge is a straight segment.

    The SVG importer often represents SVG H/V/L commands as cubic Beziers.
    Converting those into a multispan cubic spline creates unnecessary pole
    helpers in Sketcher and loses native line editing. Sample the evaluated
    edge, since OCC control poles can extend beyond its actual geometry.
    """
    start = edge.valueAt(edge.FirstParameter)
    end = edge.valueAt(edge.LastParameter)
    direction = end - start
    length = direction.Length
    if length <= 1e-7:
        return None
    curve = edge.Curve
    kind = type(curve).__name__
    if kind in ('Line', 'LineSegment'):
        return start, end
    if kind not in ('BezierCurve', 'BSplineCurve'):
        return None
    try:
        samples = edge.discretize(Number=33)
    except (AttributeError, TypeError):
        return None
    last_fraction = -1e-8
    for point in samples:
        fraction = (point - start).dot(direction) / (length * length)
        nearest = start + direction * fraction
        if ((point - nearest).Length > 1e-6 or
                fraction < last_fraction or fraction > 1.0 + 1e-8):
            return None
        last_fraction = fraction
    return start, end


def _closed_straight_pocket(wire):
    """Make ordered native lines from a closed, all-straight SVG pocket.

    Do not merge a rectangle into a cubic B-spline. Each resulting sketch
    line shares its endpoint with the next, and the caller adds corner
    coincidence constraints before recomputation.
    """
    import Part
    if len(wire.Edges) < 3:
        return None
    remaining = [_straight_edge_vertices(edge) for edge in wire.Edges]
    if any(pair is None for pair in remaining):
        return None
    ordered = [remaining.pop(0)]
    while remaining:
        tip = ordered[-1][1]
        matches = []
        for index, (start, end) in enumerate(remaining):
            if (start - tip).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                matches.append((index, False))
            elif (end - tip).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                matches.append((index, True))
        if len(matches) != 1:
            return None
        index, reverse = matches[0]
        pair = remaining.pop(index)
        ordered.append((pair[1], pair[0]) if reverse else pair)
    if (ordered[-1][1] - ordered[0][0]).Length > SVG_ENDPOINT_TOLERANCE_MM:
        return None
    # SVG line paths can contain redundant collinear subsegments. Merge them
    # before creating Sketcher geometry; keep genuine corners as independent
    # native line segments with Coincident constraints.
    changed = True
    while changed and len(ordered) > 3:
        changed = False
        for i in range(len(ordered)):
            j = (i + 1) % len(ordered)
            first, corner = ordered[i]
            _, last = ordered[j]
            u, v = corner - first, last - corner
            if u.Length <= 1e-7 or v.Length <= 1e-7:
                continue
            if (u.dot(v) > 0 and
                    (last - first).Length > 0 and
                    (corner - (first + (last - first) *
                     ((corner - first).dot(last - first) /
                      ((last - first).Length ** 2)))).Length < 1e-6):
                ordered[i] = (first, last)
                ordered.pop(j)
                changed = True
                break
    return [Part.LineSegment(start, end) for start, end in ordered]


def _pocket_geometry(wire, svg_kind=None):
    """Choose native Sketcher primitives, preserving source SVG semantics.

    Native <circle> and <ellipse> are recognized from source XML IDs rather
    than relying on importSVG's Bezier/BSpline representation. Unlabeled SVG
    paths are only upgraded to a circle when the geometry fits to 0.01 mm.
    Unsupported profiles retain their exact multispan B-spline geometry.
    """
    import Part

    if not wire.isClosed():
        raise ValueError('pocket path is not closed')
    if len(wire.Edges) == 1:
        curve = wire.Edges[0].Curve
        if type(curve).__name__ in ('Circle', 'Ellipse'):
            return [curve]
    if svg_kind == 'circle':
        circle = _fitted_circle(wire, 0.01)
        if circle is not None:
            return [circle]
        # A nonuniform SVG transform can legitimately turn a circle into an
        # ellipse: preserve that affine geometry instead of distorting it.
        ellipse = _fitted_axis_ellipse(wire)
        if ellipse is not None:
            return [ellipse]
        # Final fallback for importSVG approximation drift only (<= 0.5 mm).
        circle = _fitted_circle(wire, SVG_SKETCH_TOLERANCE_MM)
        if circle is not None:
            return [circle]
    if svg_kind == 'ellipse':
        ellipse = _fitted_axis_ellipse(wire)
        if ellipse is not None:
            return [ellipse]
    # Keep detection of circular <path> elements, but require a close fit.
    circle = _fitted_circle(wire, 0.01)
    if circle is not None:
        return [circle]
    lines = _closed_straight_pocket(wire)
    if lines is not None:
        return lines
    spline = _contour_bspline_geometry(wire)
    if spline is not None:
        return spline
    if len(wire.Edges) == 1:
        return [wire.Edges[0].Curve]
    raise ValueError('unsupported multi-edge pocket geometry')


def create_pocket_sketch(doc, pockets, source_document, anchor):
    """Create one Sketcher object for ALL pockets from this SVG import.

    Keep the original fused cutter solids unchanged for compatibility. Each
    pocket's geometry indices and original SVG ID/start/depth/side are stored
    in the sketch for future parametric cutter integration.
    """
    if not pockets:
        return None
    import Part
    name = POCKET_SKETCH_NAMES[source_document]
    previous = doc.getObject(name)
    if previous is not None:
        # The imported SVG is explicitly being replaced, never overwrite edits
        # during a normal Create editable SVG sketches command.
        doc.removeObject(name)
    sketch = doc.addObject('Sketcher::SketchObject', name)
    elements = []
    try:
        for pocket in pockets:
            wire = Part.Wire(pocket.edges)
            wire.translate(-anchor)
            indices = []
            curves = _pocket_geometry(wire, getattr(pocket, 'svg_kind', None))
            for curve in curves:
                index = sketch.addGeometry(curve, False)
                indices.append(index)
                if type(curve).__name__ == 'BSplineCurve':
                    sketch.exposeInternalGeometry(index)
            if len(curves) >= 3 and all(
                    type(curve).__name__ == 'LineSegment' for curve in curves):
                # Native Sketcher lines are individually movable: constrain
                # corners now, before the first sketch recompute. The path
                # is ordered and closed by _closed_straight_pocket().
                from Sketcher import Constraint
                sketch.addConstraint([
                    Constraint('Coincident', indices[i], 2,
                               indices[(i + 1) % len(indices)], 1)
                    for i in range(len(indices))])
            App.Console.PrintMessage('[Marz SVG] Pocket {}: {} Sketcher geometries ({})\n'.format(
                pocket.name, len(curves), ', '.join(type(c).__name__ for c in curves)))
            elements.append({'id': pocket.name, 'indices': indices,
                             'start': pocket.start, 'depth': pocket.depth,
                             'target': pocket.target})
        if 'SVGSourceDocument' not in sketch.PropertiesList:
            sketch.addProperty('App::PropertyString', 'SVGSourceDocument', 'Marz SVG', 'Source SVG category')
        if 'SVGElementMap' not in sketch.PropertiesList:
            sketch.addProperty('App::PropertyString', 'SVGElementMap', 'Marz SVG', 'SVG pocket IDs and geometry indices')
        sketch.SVGSourceDocument = source_document
        if 'SVGConversionValid' not in sketch.PropertiesList:
            sketch.addProperty('App::PropertyBool', 'SVGConversionValid', 'Marz SVG',
                               'Whether the pocket sketch may be used as a cutter source')
        sketch.SVGConversionValid = True
        sketch.SVGElementMap = json.dumps({'version': 1, 'elements': elements},
                                          sort_keys=True, separators=(',', ':'))
        sketch.Label = ('Body' if source_document == 'body' else 'Headstock') + ' pockets (edit in Sketcher)'
        sketch.recompute()
        sketch.ViewObject.Visibility = False
        _group_sketch(doc, sketch)
        _configure_sketcher_display_defaults()
        App.Console.PrintMessage('[Marz SVG] Pocket sketch ready: {} ({} SVG IDs)\n'.format(
            name, len(elements)))
        return sketch
    except Exception as exc:
        # Keep failed conversions available for inspection; never use a
        # partially converted sketch as a replacement for original cutters.
        if 'SVGConversionValid' not in sketch.PropertiesList:
            sketch.addProperty('App::PropertyBool', 'SVGConversionValid', 'Marz SVG',
                               'Whether the pocket sketch may be used as a cutter source')
        if 'SVGConversionError' not in sketch.PropertiesList:
            sketch.addProperty('App::PropertyString', 'SVGConversionError', 'Marz SVG',
                               'Pocket sketch conversion error')
        sketch.SVGConversionValid = False
        sketch.SVGConversionError = str(exc)
        sketch.Label = name + ' (conversion incomplete)'
        _group_sketch(doc, sketch)
        sketch.ViewObject.Visibility = True
        App.Console.PrintWarning('[Marz SVG] Could not create pocket sketch {}: {}; '
                                 'partial sketch kept for inspection; original cutters retained\n'
                                 .format(name, exc))
        return sketch




def refresh_pocket_cutters(doc, source_document, *, clear_empty=False):
    """Rebuild legacy Boolean cutters from edited pocket Sketcher geometry.

    Return False without touching cutters if the sketch is missing or contains
    unsupported/open geometry. The preexisting original cutter solids remain
    intact, so a failed edit cannot silently remove imported pockets.
    """
    sketch = doc.getObject(POCKET_SKETCH_NAMES[source_document])
    if sketch is None or not getattr(sketch, 'SVGConversionValid', False):
        return False
    import Part
    from freecad.marz.feature.document import (BodyPockets, BodyTopPockets,
                                                 BodyBackPockets, HeadstockPockets)
    target_features = ({'': BodyPockets, 't': BodyTopPockets,
                        'b': BodyBackPockets} if source_document == 'body'
                       else {'': HeadstockPockets})
    groups = {target: [] for target in target_features}
    try:
        metadata = json.loads(sketch.SVGElementMap)['elements']
        for element in metadata:
            indices = element['indices']
            if not indices or not element['depth'] or element['depth'] < 0:
                raise ValueError('invalid pocket geometry indices or depth: ' + element['id'])
            if element['target'] not in groups:
                raise ValueError('unsupported target: ' + element['id'])
            edges = [sketch.Geometry[i].toShape() for i in indices]
            wire = Part.Wire(edges)
            wire.Placement = sketch.Placement
            if not wire.isClosed():
                raise ValueError('edited pocket has an open profile: ' + element['id'])
            cutter = Part.Face(wire).extrude(App.Vector(0, 0, -element['depth']))
            cutter.translate(App.Vector(0, 0, -element['start']))
            if cutter.isNull() or not cutter.Solids or not cutter.isValid():
                raise ValueError('edited pocket produced no valid solid: ' + element['id'])
            groups[element['target']].append(cutter)
        # Commit only after every pocket validates. Do not partially replace.
        for target, solids in groups.items():
            if solids:
                target_features[target].set(Part.makeCompound(solids),
                                            visibility=False, doc=doc)
            elif clear_empty:
                # Editing a pocket's target can leave its former group empty.
                # Remove that group's stale cutter instead of continuing to
                # cut the old side of the guitar.
                target_features[target].remove(doc=doc)
        return True
    except Exception as exc:
        App.Console.PrintWarning('[Marz SVG] {} pocket sketch not applied: {}; '
                                 'retaining previous cutters\n'.format(source_document, exc))
        return False


def _create_contour_sketch(doc, source_shape, name):
    """Create an editable single-spline contour with a constrained seam.

    A clamped (non-periodic) spline preserves SVG C0 corners exactly, but
    repeating the first pole at the last pole does *not* keep them together
    when either endpoint moves. Join both ends in Sketcher and expose its
    internal B-spline geometry so the intermediate poles can be dragged.
    """
    geometry = _contour_bspline_geometry(source_shape)
    if geometry is None:
        raise ValueError('SVG contour cannot be represented exactly as one '
                         'cubic B-spline; original source is retained')
    _configure_sketcher_display_defaults()
    sketch = doc.addObject('Sketcher::SketchObject', name)
    try:
        from Sketcher import Constraint
        spline_index = sketch.addGeometry(geometry[0], False)
        # The contour must remain closed after an endpoint is dragged. Unlike
        # a periodic spline, this keeps the original SVG seam's C0 corner.
        sketch.addConstraint(Constraint('Coincident', spline_index, 1,
                                        spline_index, 2))
        # A spline inserted with addGeometry does not automatically expose the
        # internal pole/knot helper geometry that native Sketcher-created
        # B-splines have. Without it only its first/last points are draggable.
        helpers_added = sketch.exposeInternalGeometry(spline_index)
        if helpers_added is not None and helpers_added <= 0:
            raise ValueError('Sketcher failed to expose B-spline pole geometry')
        sketch.recompute()
        if getattr(sketch, 'RedundantConstraints', []):
            raise ValueError('Closed-contour seam constraints are redundant')
        if getattr(sketch, 'ConflictingConstraints', []):
            raise ValueError('Closed-contour seam constraints conflict')
    except Exception:
        doc.removeObject(sketch.Name)
        raise
    App.Console.PrintMessage('[Marz SVG] Created editable closed contour spline '
                             f'{name} from {len(source_shape.Edges)} SVG segments; '
                             f'{len(geometry[0].getPoles())} poles exposed\n')
    return sketch

def _create_constrained_sketch(doc, source_shape, name):
    """Convert edges with Draft, but construct the persistent sketch *with* joins.

    Draft's temporary unconnected representation is never exposed as the
    editable model. This also avoids adding or repairing constraints on an
    existing manually edited Sketcher object in a later pass.
    """
    import Draft
    _configure_sketcher_display_defaults()

    temporary = None
    try:
        temporary = Draft.make_sketch(source_shape, autoconstraints=False,
                                      delete=False, name=name + '_Draft', tol=1e-5)
        if temporary is None:
            raise ValueError('Draft.make_sketch returned no sketch')
        constraints = _initial_endpoint_constraints(source_shape, temporary)
        sketch = doc.addObject('Sketcher::SketchObject', name)
        try:
            sketch.Placement = temporary.Placement
            sketch.addGeometry(list(temporary.Geometry), False)
            if constraints:
                sketch.addConstraint(constraints)
            sketch.recompute()
        except Exception:
            doc.removeObject(sketch.Name)
            raise
        App.Console.PrintMessage('[Marz SVG] Created ' + name + ' with '
                                 f'{len(constraints)} initial coincidence constraints\n')
        return sketch
    finally:
        if temporary is not None and doc.getObject(temporary.Name) is not None:
            doc.removeObject(temporary.Name)


def source_object(doc, source_name):
    """Return the native editor when present, otherwise the old wire object."""
    sketch_name = SKETCH_NAMES.get(source_name)
    if sketch_name:
        sketch = doc.getObject(sketch_name)
        # A failed conversion stays in the tree for inspection, but must not
        # silently replace the original wire as a model-building input.
        # Sketches created before this status property existed are valid.
        if sketch is not None and getattr(sketch, 'SVGConversionValid', True):
            return sketch
    return doc.getObject(source_name)


def remove_sketches(doc, source_names):
    """Only explicit SVG reimport resets the corresponding editable sketches."""
    for source_name in source_names:
        sketch_name = SKETCH_NAMES.get(source_name)
        if sketch_name and doc.getObject(sketch_name) is not None:
            doc.removeObject(sketch_name)


def _wire_closed(shape):
    """Sketcher can return a compound of edges instead of a single wire."""
    if shape.isClosed():
        return True
    try:
        import Part
        wire = Part.Wire(shape.Edges)
        return wire.isClosed() and len(wire.Edges) == len(shape.Edges)
    except Exception:
        return False


def _edge_deviation(src_points, dst_points):
    """A Draft-to-Sketch conversion may reverse a curve's parameter direction."""
    if len(src_points) != len(dst_points):
        return float('inf')
    forward = max((p - q).Length for p, q in zip(src_points, dst_points))
    reverse = max((p - q).Length for p, q in zip(src_points, reversed(dst_points)))
    return min(forward, reverse)


def _shape_difference(original, converted, tolerance=SVG_SKETCH_TOLERANCE_MM):
    """Return a real geometric discrepancy, or None for equivalent geometry.

    Draft.make_sketch converts Bezier segments to equivalent B-splines and
    orients the segments to the sketch plane. Sketcher may also enumerate
    segments differently. None of those operations changes the actual curve;
    matching edge *indices* and directions would reject valid SVG contours.

    Still require the same number of edges, their complete sampled paths,
    total length, world bounds and closed/open status. Deviations up to the
    explicitly configured 0.5 mm tolerance are accepted.
    """
    if converted.isNull():
        return 'empty Sketcher shape'
    source_edges, sketch_edges = original.Edges, converted.Edges
    merged_contour = (len(source_edges) > 1 and len(sketch_edges) == 1
                      and all(hasattr(edge, 'Curve') for edge in source_edges))
    if len(source_edges) != len(sketch_edges) and not merged_contour:
        return f'edge count changed: {len(source_edges)} -> {len(sketch_edges)}'
    if _wire_closed(original) != _wire_closed(converted):
        return 'open/closed contour changed'
    delta = abs(original.Length - converted.Length)
    if delta > tolerance:
        return f'total curve length changed by {delta:.6g} mm'
    a, b = original.BoundBox, converted.BoundBox
    for field in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax'):
        diff = abs(getattr(a, field) - getattr(b, field))
        if diff > tolerance:
            return f'world-space {field} changed by {diff:.6g} mm'

    if merged_contour:
        # Joining cubic SVG segments necessarily changes edge count. Verify
        # the *geometry* bidirectionally instead of comparing edge indices.
        # Both directions are important: an added spurious loop could pass a
        # source-to-sketch-only distance check.
        import Part
        for edge_set, other in ((source_edges, converted),
                                (sketch_edges, original)):
            for edge in edge_set:
                num_points = 21 if not (edge_set is sketch_edges) else (
                    21 * len(source_edges))
                for point in edge.discretize(Number=num_points):
                    deviation = Part.Vertex(point).distToShape(other)[0]
                    if deviation > tolerance:
                        return f'merged contour curve deviation {deviation:.6g} mm'
        return None

    # Match the entire shape, not an assumed OCC edge enumeration order.
    # Curves are matched one-to-one, and each match is sampled in both
    # directions. Reject even one changed segment. An augmenting matcher also
    # handles coincident/doubled segments without depending on their order.
    source_samples = [edge.discretize(Number=21) for edge in source_edges]
    sketch_samples = [edge.discretize(Number=21) for edge in sketch_edges]
    options = []
    for idx, points in enumerate(source_samples):
        candidates = [(_edge_deviation(points, other), target)
                      for target, other in enumerate(sketch_samples)]
        candidates.sort()
        options.append([target for distance, target in candidates
                        if distance <= tolerance])
        if not options[-1]:
            return f'edge {idx} curve deviation {candidates[0][0]:.6g} mm'

    matches = [None] * len(sketch_edges)

    def assign(source_idx, visited):
        for target in options[source_idx]:
            if target in visited:
                continue
            visited.add(target)
            previous = matches[target]
            if previous is None or assign(previous, visited):
                matches[target] = source_idx
                return True
        return False

    for idx in range(len(source_edges)):
        if not assign(idx, set()):
            return f'edge {idx} has no unique geometric match'
    return None


def _matching_shape(original, converted, tolerance=SVG_SKETCH_TOLERANCE_MM):
    """True for the *same* outline regardless of edge ordering or winding."""
    return _shape_difference(original, converted, tolerance) is None


def _group_sketch(doc, sketch):
    """Put accepted and rejected sketches in the same editable source group."""
    group = doc.getObject(GROUP_NAME)
    if group is None:
        group = doc.addObject('App::DocumentObjectGroup', GROUP_NAME)
        group.Label = 'Editable SVG sketches'
        imports = doc.getObject('Marz_Group_Imports')
        if imports is not None:
            imports.addObject(group)
    group.addObject(sketch)


def _mark_failed_sketch(sketch, original, reason):
    """Persist failure status so reopening the document keeps the SVG fallback."""
    if 'SVGConversionValid' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyBool', 'SVGConversionValid', 'Marz SVG',
                           'True only if the SVG-to-Sketch geometry was validated')
    sketch.SVGConversionValid = False
    if 'SVGConversionError' not in sketch.PropertiesList:
        sketch.addProperty('App::PropertyString', 'SVGConversionError', 'Marz SVG',
                           'Reason this sketch is not being used for model generation')
    sketch.SVGConversionError = str(reason)
    sketch.Label = original.Label + ' (conversion mismatch)'
    sketch.ViewObject.Visibility = True


def create_sketch(doc, source_name):
    """Convert one stored SVG reference to a native, editable Sketcher object.

    Does not modify the original wire or overwrite previously edited sketches.
    Explicit SVG reimport removes the old sketches first.
    """
    sketch_name = SKETCH_NAMES[source_name]
    existing = doc.getObject(sketch_name)
    if existing is not None:
        # Never replace manually edited sketches through a normal command.
        # Explicit SVG reimport removes this sketch before calling here.
        # The tolerance can change between versions. Revalidate an existing
        # rejected sketch *as-is*; never recreate or alter its geometry.
        original = doc.getObject(source_name)
        if (original is not None and
                not getattr(existing, 'SVGConversionValid', True)):
            if _shape_difference(original.Shape, existing.Shape) is None:
                existing.SVGConversionValid = True
                existing.SVGConversionError = ''
                existing.Label = original.Label + ' (edit in Sketcher)'
                App.Console.PrintMessage('[Marz SVG] Accepted existing sketch within '
                                         f'{SVG_SKETCH_TOLERANCE_MM:g} mm tolerance: '
                                         + source_name + '\n')
            else:
                _show_overlay(original, existing)
        return existing
    original = doc.getObject(source_name)
    if original is None or original.Shape.isNull() or not original.Shape.Edges:
        return None

    # Draft converts the source geometry; the final Sketcher object is created
    # with its coincidence constraints in the initial construction.
    # It uses the active document, which must be our source document.
    if App.ActiveDocument is not doc:
        App.setActiveDocument(doc.Name)
    source_shape = original.Shape.copy()
    temp = None
    try:
        is_contour = (source_name in ('Marz_Body_Contour', 'Marz_Headstock_Contour')
                      and all(hasattr(edge, 'Curve') for edge in source_shape.Edges))
        if is_contour:
            temp = _create_contour_sketch(doc, source_shape, sketch_name)
        else:
            temp = _create_constrained_sketch(doc, source_shape, sketch_name)
        if getattr(temp, 'RedundantConstraints', []):
            raise ValueError('Initial endpoint joins are redundant')
        if getattr(temp, 'ConflictingConstraints', []):
            raise ValueError('Initial endpoint joins conflict')
        _persist_source_ids(temp, source_name, [0] if is_contour else None)
        # First attempt exact equivalence so pure rigid Draft placement errors
        # are still corrected, even when smaller than the allowed drift.
        exact_difference = _shape_difference(source_shape, temp.Shape, 1e-4)
        if exact_difference is not None and _align_pure_translation(source_shape, temp):
            exact_difference = None
        difference = _shape_difference(source_shape, temp.Shape)
        if difference is not None:
            raise ValueError('Sketch geometry differs from SVG reference: ' + difference)
        if exact_difference is not None:
            App.Console.PrintMessage('[Marz SVG] Accepted conversion within '
                                     f'{SVG_SKETCH_TOLERANCE_MM:g} mm tolerance: '
                                     + source_name + ' (' + exact_difference + ')\n')
        temp.Label = original.Label + ' (edit in Sketcher)'
        temp.ViewObject.Visibility = False
        _group_sketch(doc, temp)
        App.Console.PrintMessage('[Marz SVG] Sketch ready: ' + source_name + '\n')
        return temp
    except Exception as exc:
        if temp is not None and doc.getObject(temp.Name) is not None:
            # Keep the actual Draft conversion, including its changed geometry,
            # for inspection in Sketcher. Only the model source falls back.
            # Set the persistent guard *before* exposing the rejected sketch.
            _mark_failed_sketch(temp, original, exc)
            _group_sketch(doc, temp)
            _show_overlay(original, temp)
            App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                     + '; left rejected sketch visible for inspection; '
                                     'original SVG remains model source\n')
            return temp
        App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                 + '; no sketch was created; original SVG remains model source\n')
        return existing



def create_pocket_sketches_from_embedded_svg(doc):
    """Create missing pocket sketches from saved SVGs without a destructive reimport.

    The normal Create editable SVG sketches command should include pockets.
    Import the *embedded* SVG into an isolated temporary document to recover
    original IDs, cut depths and geometry. Do not replace imported reference
    shapes, generated parts or any previously edited sketches.
    """
    from freecad.marz import utils
    from freecad.marz.feature.document import File_Svg_Body, File_Svg_Headstock
    from freecad.marz.feature.import_svg import (import_svg, extract_pocket,
                                                  NAME_ID_PATTERN)

    result = []
    for category, stored_file in (('body', File_Svg_Body),
                                  ('headstock', File_Svg_Headstock)):
        name = POCKET_SKETCH_NAMES[category]
        existing = doc.getObject(name)
        if existing is not None:
            result.append(existing)
            continue
        path = stored_file.path(doc=doc)
        if not path:
            App.Console.PrintWarning('[Marz SVG] No embedded {} SVG; pocket sketch not created\n'
                                     .format(category))
            continue

        temp_doc = App.newDocument(utils.randomString(16), 'Importing', True, True)
        try:
            import_svg(path, temp_doc.Name)
            primitive_types = svg_pocket_primitive_types(path)
            contour = midline = None
            pockets = []
            for obj in temp_doc.Objects:
                match = NAME_ID_PATTERN.match(obj.Name)
                source_id = match.group(1) if match else None
                if source_id == 'contour':
                    contour = obj
                elif source_id == 'midline':
                    midline = obj
                else:
                    extract_pocket(obj, pockets, primitive_types)

            if not pockets:
                App.Console.PrintWarning('[Marz SVG] No pocket IDs found in embedded {} SVG\n'
                                         .format(category))
                continue
            if contour is None or midline is None:
                raise ValueError('missing contour/midline required to align pocket geometry')
            distance, vertices, _edges = midline.Shape.distToShape(contour.Shape)
            if distance > 1e-7 or not vertices:
                raise ValueError('contour/midline do not intersect at the import anchor')
            anchor = vertices[0][0]

            App.setActiveDocument(doc.Name)
            result.append(create_pocket_sketch(doc, pockets, category, anchor))
        except Exception as exc:
            App.Console.PrintWarning('[Marz SVG] Could not create {} pocket sketch '
                                     'from embedded SVG: {}\n'.format(category, exc))
        finally:
            App.setActiveDocument(doc.Name)
            App.closeDocument(temp_doc.Name)
    return result


def create_all(doc, source_names=None):
    names = list(source_names) if source_names is not None else list(SKETCH_NAMES)
    return [create_sketch(doc, name) for name in names
            if name in SKETCH_NAMES and doc.getObject(name) is not None]
