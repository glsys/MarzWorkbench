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
FRET_INLAY_SKETCH_PREFIX = 'Marz_Sketch_FretInlay_'
BODY_MASTER_SKETCH_NAME = 'Marz_Sketch_BodyMaster'


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


def _initial_endpoint_constraints(source_shape, draft_sketch, index_offset=0):
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
                joins.append(Constraint('Coincident', first_idx + index_offset, first_pos,
                                        other_idx + index_offset, other_pos))
    return joins




def _cubic_edge_poles(edge):
    """Return exact cubic poles for one untrimmed polynomial SVG edge."""
    curve = edge.Curve
    kind = type(curve).__name__
    if kind == 'BezierCurve' and curve.Degree == 3:
        poles = list(curve.getPoles())
        if len(poles) != 4 or (hasattr(curve, 'isRational')
                               and curve.isRational()):
            return None
    elif kind == 'BSplineCurve' and curve.Degree == 3:
        poles = list(curve.getPoles())
        if (len(poles) != 4 or len(curve.getKnots()) != 2
                or (hasattr(curve, 'getWeights') and any(
                    abs(w - 1.0) > 1e-12 for w in curve.getWeights()))):
            return None
    else:
        return None

    # Refuse trimmed curves: their full control polygon is not necessarily the
    # geometry represented by this edge. Reverse only when OCC parameterizes
    # the complete source cubic in the opposite direction.
    first, last = (edge.valueAt(edge.FirstParameter),
                   edge.valueAt(edge.LastParameter))
    if ((poles[0] - first).Length <= SVG_ENDPOINT_TOLERANCE_MM and
            (poles[-1] - last).Length <= SVG_ENDPOINT_TOLERANCE_MM):
        return poles
    if ((poles[-1] - first).Length <= SVG_ENDPOINT_TOLERANCE_MM and
            (poles[0] - last).Length <= SVG_ENDPOINT_TOLERANCE_MM):
        return list(reversed(poles))
    return None


def _ordered_contour_segments(source_shape):
    """Order one closed contour while retaining each source primitive kind.

    Straight SVG segments stay straight lines. Cubic Bezier/single-span cubic
    B-spline edges keep their exact four control poles. This deliberately does
    not force the whole contour into one spline merely to make it connected;
    Sketcher coincidence constraints provide that connectivity instead.
    """
    edges = list(source_shape.Edges)
    if not edges:
        return None
    segments = []
    for edge in edges:
        straight = _straight_edge_vertices(edge)
        if straight is not None:
            data = list(straight)
            kind = 'line'
        else:
            data = _cubic_edge_poles(edge)
            kind = 'cubic'
            if data is None:
                return None
        segments.append((kind, data))

    ordered = [segments.pop(0)]
    while segments:
        end = ordered[-1][1][-1]
        candidates = []
        for i, (_, data) in enumerate(segments):
            if (data[0] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                candidates.append((i, False))
            elif (data[-1] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                candidates.append((i, True))
        if len(candidates) != 1:
            return None
        i, reversed_direction = candidates[0]
        kind, data = segments.pop(i)
        if reversed_direction:
            data = list(reversed(data))
        ordered.append((kind, data))

    if ((ordered[-1][1][-1] - ordered[0][1][0]).Length >
            SVG_ENDPOINT_TOLERANCE_MM):
        return None
    return ordered


def _contour_sketch_geometry(source_shape):
    """Create exact mixed Sketcher geometry for a body/headstock contour.

    Lines are native ``Part.LineSegment`` objects. Curved cubic source spans
    are exact single-span cubic B-splines. The returned spline indices tell the
    caller which geometries need their internal pole helpers exposed.
    """
    import Part
    ordered = _ordered_contour_segments(source_shape)
    if ordered is None:
        return None
    geometry, spline_indices = [], []
    for kind, data in ordered:
        if kind == 'line':
            curve = Part.LineSegment(data[0], data[-1])
        else:
            curve = Part.BSplineCurve()
            curve.buildFromPolesMultsKnots(
                data, [4, 4], [0.0, 1.0], False, 3)
            spline_indices.append(len(geometry))
        geometry.append(curve)
    return geometry, spline_indices


def _contour_bspline_geometry(source_shape):
    """Legacy exact multispan B-spline fallback used by pocket conversion.

    Body/headstock *contour sketches* no longer use this representation: they
    preserve native straight lines and separate cubic spans. Pocket conversion
    still uses a single exact B-spline when no better native primitive applies.
    """
    import Part
    ordered = _ordered_contour_segments(source_shape)
    if ordered is None:
        return None

    cubic_segments = []
    for kind, data in ordered:
        if kind == 'line':
            start, end = data
            cubic_segments.append([
                start, start + (end - start) / 3.0,
                start + (end - start) * (2.0 / 3.0), end])
        else:
            cubic_segments.append(list(data))

    poles = list(cubic_segments[0])
    for segment in cubic_segments[1:]:
        poles.extend(segment[1:])
    poles[-1] = poles[0]
    count = len(cubic_segments)
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
    curve = getattr(edge, 'Curve', None)
    kind = type(curve).__name__
    if kind in ('Line', 'LineSegment'):
        return start, end
    if kind == 'BSplineCurve' and getattr(curve, 'Degree', None) == 1:
        # A complete two-pole degree-1 B-spline is exactly a line; no sampling
        # is needed and importSVG frequently uses this representation for L/H/V.
        try:
            poles = list(curve.getPoles())
            if len(poles) == 2 and (
                    ((poles[0] - start).Length <= SVG_ENDPOINT_TOLERANCE_MM and
                     (poles[1] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM) or
                    ((poles[1] - start).Length <= SVG_ENDPOINT_TOLERANCE_MM and
                     (poles[0] - end).Length <= SVG_ENDPOINT_TOLERANCE_MM)):
                return start, end
        except (AttributeError, TypeError):
            pass
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


def _create_straight_reference_sketch(doc, source_shape, name):
    """Build native lines for straight SVG references, without Draft splines.

    SVG H/V/L commands can arrive as Bezier or B-spline edges. Work from
    evaluated edge endpoints and preserve their world-space geometry, rather
    than keeping Draft's interpolated B-spline representation. Return None
    for genuinely curved or non-XY geometry, which keeps the Draft fallback.
    """
    import Part
    from Sketcher import Constraint

    segments = [_straight_edge_vertices(edge) for edge in source_shape.Edges]
    if not segments or any(pair is None for pair in segments):
        return None
    z = segments[0][0].z
    if any(abs(point.z - z) > 1e-6
           for pair in segments for point in pair):
        return None
    offset = App.Vector(0, 0, z)
    sketch = doc.addObject('Sketcher::SketchObject', name)
    try:
        if z:
            placement = sketch.Placement
            placement.Base = offset
            sketch.Placement = placement
        indices = [sketch.addGeometry(Part.LineSegment(a - offset, b - offset),
                                      False) for a, b in segments]
        endpoints = [(point, index, position)
                     for index, (a, b) in zip(indices, segments)
                     for point, position in ((a, 1), (b, 2))]
        # Connect shared vertices in the initial construction; unrelated
        # endpoints remain free. Use a spanning tree to avoid redundancy.
        clusters = []
        for point, index, position in endpoints:
            for cluster in clusters:
                if (point - cluster[0][0]).Length <= SVG_ENDPOINT_TOLERANCE_MM:
                    cluster.append((point, index, position))
                    break
            else:
                clusters.append([(point, index, position)])
        for cluster in clusters:
            _, first_index, first_position = cluster[0]
            for _, index, position in cluster[1:]:
                if index != first_index:
                    sketch.addConstraint(Constraint('Coincident',
                                                    first_index, first_position,
                                                    index, position))
        sketch.recompute()
    except Exception:
        doc.removeObject(sketch.Name)
        raise
    App.Console.PrintMessage('[Marz SVG] Created native line reference '
                             f'{name}: {len(segments)} straight segment(s)\n')
    return sketch


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
        if type(curve).__name__ == 'Circle':
            return [curve]
        # FreeCAD may supply a native Ellipse even when both semi-axes are
        # equal. Recognize that *geometric* circle before preserving Ellipse.
        if type(curve).__name__ == 'Ellipse':
            circle = _fitted_circle(wire, 0.01)
            return [circle] if circle is not None else [curve]
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
        # An SVG <ellipse> with coincident foci (equal effective radii) is a
        # circle. Use the imported, transformed geometry to decide: nonuniform
        # SVG transforms may turn an originally circular ellipse into an oval.
        circle = _fitted_circle(wire, 0.01)
        if circle is not None:
            return [circle]
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
    mixed = _contour_sketch_geometry(wire)
    if mixed is not None:
        return mixed[0]
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
            if len(curves) >= 2:
                # Every multi-edge pocket is one closed semantic region. Keep
                # line/B-spline joins explicit in Sketcher instead of relying
                # on matching imported coordinates alone.
                _join_master_loop(sketch, indices)
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
            display = (sketch.MarzBodySketchTransform
                       if source_document == 'body' and
                       'MarzBodySketchTransform' in sketch.PropertiesList
                       else None)
            wire.Placement = (display.inverse().multiply(sketch.Placement)
                              if display is not None else sketch.Placement)
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


def _initial_contour_joins(sketch, indices):
    """Make every mixed contour endpoint a persistent Sketcher coincidence.

    Connectivity is part of the editable model, not an optional fidelity aid.
    Sketcher's solver may move under-constrained B-spline poles while enforcing
    these joins; that geometric drift is reported later, but it must not cause
    Marz to remove the endpoint constraints or fall back to the SVG source.
    """
    from Sketcher import Constraint

    sketch.addConstraint([
        Constraint('Coincident', indices[i], 2,
                   indices[(i + 1) % len(indices)], 1)
        for i in range(len(indices))
    ])
    sketch.recompute()
    if getattr(sketch, 'RedundantConstraints', []):
        raise ValueError('Contour endpoint joins are redundant')
    if getattr(sketch, 'ConflictingConstraints', []):
        raise ValueError('Contour endpoint joins conflict')


def _usable_connected_contour(sketch):
    """True when a solved contour is closed and its endpoint joins still exist."""
    if sketch is None or getattr(sketch, 'Shape', None) is None:
        return False
    if sketch.Shape.isNull():
        return False
    if getattr(sketch, 'RedundantConstraints', []):
        return False
    if getattr(sketch, 'ConflictingConstraints', []):
        return False
    constraints = getattr(sketch, 'Constraints', [])
    def is_coincident(constraint):
        if isinstance(constraint, (tuple, list)):
            return bool(constraint) and constraint[0] == 'Coincident'
        return getattr(constraint, 'Type', None) == 'Coincident'
    # A multi-edge contour is only promoted when its editing topology is
    # actually linked.  This avoids treating older rejected, unconstrained
    # Draft sketches as the new mixed-contour representation.
    if len(sketch.Shape.Edges) > 1 and not any(is_coincident(c) for c in constraints):
        return False
    return _wire_closed(sketch.Shape)


def _create_contour_sketch(doc, source_shape, name):
    """Create an editable contour from native lines and exact cubic spans."""
    converted = _contour_sketch_geometry(source_shape)
    if converted is None:
        raise ValueError('SVG contour contains unsupported or disconnected '
                         'geometry; original source is retained')
    geometry, spline_indices = converted
    _configure_sketcher_display_defaults()
    sketch = doc.addObject('Sketcher::SketchObject', name)
    try:
        indices = sketch.addGeometry(geometry, False)
        if not isinstance(indices, (list, tuple)):
            indices = [indices]
        # Endpoint connectivity is mandatory for the editable contour.  Solver
        # movement is diagnosed after construction but never used to remove
        # these joins.
        _initial_contour_joins(sketch, indices)
        for index in spline_indices:
            helpers_added = sketch.exposeInternalGeometry(indices[index])
            if helpers_added is not None and helpers_added <= 0:
                raise ValueError('Sketcher failed to expose B-spline pole geometry')
        sketch.recompute()
    except Exception:
        doc.removeObject(sketch.Name)
        raise
    line_count = len(geometry) - len(spline_indices)
    App.Console.PrintMessage('[Marz SVG] Created editable mixed contour '
                             f'{name}: {line_count} native line(s), '
                             f'{len(spline_indices)} cubic B-spline segment(s)\n')
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



def _json_element_map(sketch):
    """Return the persisted semantic SVG map for a Sketcher source."""
    if sketch is None or not getattr(sketch, 'SVGElementMap', ''):
        return {}
    try:
        return json.loads(sketch.SVGElementMap)
    except (TypeError, ValueError):
        return {}


def _copy_master_geometry(master, source, indices, *, construction=False):
    """Copy only source-mapped geometry, never exposed B-spline helpers."""
    copied = []
    geometry = list(getattr(source, 'Geometry', []))
    for index in indices:
        if index < 0 or index >= len(geometry):
            raise ValueError('{} geometry index {} is unavailable'.format(
                getattr(source, 'Name', 'source'), index))
        new_index = master.addGeometry(geometry[index], construction)
        copied.append(new_index)
        if type(geometry[index]).__name__ == 'BSplineCurve':
            helpers = master.exposeInternalGeometry(new_index)
            if helpers is not None and helpers <= 0:
                raise ValueError('Sketcher failed to expose master B-spline controls')
    return copied


def _join_master_loop(master, indices):
    """Keep every multi-edge semantic region connected in the master sketch."""
    if len(indices) < 2:
        return
    from Sketcher import Constraint
    master.addConstraint([
        Constraint('Coincident', indices[i], 2,
                   indices[(i + 1) % len(indices)], 1)
        for i in range(len(indices))
    ])


def _master_operation_groups(elements):
    """Group pocket semantic IDs by the native operation they will share."""
    groups = {}
    for item in elements:
        if item.get('role') != 'pocket':
            continue
        start = item.get('start', 0)
        end = start + item.get('depth', 0)
        key = (item.get('target', ''), start, end)
        groups.setdefault(key, []).append(item['id'])
    return [
        {'target': target, 'start': start, 'end': end, 'ids': ids}
        for (target, start, end), ids in sorted(
            groups.items(), key=lambda pair: (pair[0][0], pair[0][1], pair[0][2]))
    ]


def _relink_body_master_consumers(doc, master):
    """Reconnect persistent master-driven consumers after explicit SVG reimport.

    Reimport deletes/recreates the master by design. Existing contour-profile,
    pocket-cutter and semantic neck-pocket features survive, so reconnect them
    to the new master Sketcher object.
    """
    profile = doc.getObject('Marz_Body_Top_MasterContour')
    if profile is not None and 'Source' in getattr(profile, 'PropertiesList', []):
        profile.Source = master
        profile.recompute()
        for name in ('Marz_Body_Top_Extrusion_ContourLink',
                     'Marz_Body_Back_Extrusion_ContourLink'):
            link = doc.getObject(name)
            if link is not None:
                link.LinkedObject = profile

    for suffix in ('Both', 'Top', 'Back'):
        cutter = doc.getObject('Marz_Body_MasterPocketCutters_' + suffix)
        if cutter is None or 'Source' not in getattr(cutter, 'PropertiesList', []):
            continue
        cutter.Source = master
        if ('SourceDisplay' in getattr(cutter, 'PropertiesList', [])
                and 'MarzBodySketchTransform' in getattr(master, 'PropertiesList', [])):
            cutter.SourceDisplay = master.MarzBodySketchTransform
        cutter.recompute()

    tool = doc.getObject('Marz_Body_MasterNeckPocketTool')
    if tool is not None and 'Source' in getattr(tool, 'PropertiesList', []):
        tool.Source = master

    # Native PartDesign histories keep their own profile binders.  Re-resolve
    # those binders against the replacement master by semantic SVG identity;
    # never persist old InternalFace numbers across a reimport.
    try:
        from freecad.marz.feature.body_parametric import relink_native_body_master
        relink_native_body_master(doc, master)
    except Exception as exc:
        App.Console.PrintWarning(
            '[Marz SVG] Native Body history could not be relinked during reimport; Update Parts will rebuild it: {}\n'
            .format(exc))


def _append_body_master_special_profile(master, profile_id, wire):
    """Add one missing semantic profile without replacing edited master geometry."""
    if wire is None:
        return False
    data = _json_element_map(master)
    elements = list(data.get('elements', []))
    if any(item.get('id') == profile_id for item in elements):
        return False
    curves = _pocket_geometry(wire)
    indices = []
    for curve in curves:
        index = master.addGeometry(curve, False)
        indices.append(index)
        if type(curve).__name__ == 'BSplineCurve':
            helpers = master.exposeInternalGeometry(index)
            if helpers is not None and helpers <= 0:
                raise ValueError('Sketcher failed to expose master B-spline controls')
    _join_master_loop(master, indices)
    elements.append({
        'id': profile_id, 'role': 'neck-pocket', 'indices': indices,
        'source': 'body-svg',
    })
    data['version'] = max(2, data.get('version', 2))
    data['source_document'] = 'body'
    data['elements'] = elements
    data['operations'] = _master_operation_groups(elements)
    master.SVGElementMap = json.dumps(data, sort_keys=True, separators=(',', ':'))
    master.recompute()
    if getattr(master, 'RedundantConstraints', []):
        raise ValueError('Body Master Sketch has redundant constraints')
    if getattr(master, 'ConflictingConstraints', []):
        raise ValueError('Body Master Sketch has conflicting constraints')
    App.Console.PrintMessage('[Marz SVG] Added {} semantic profile to Body Master Sketch\n'
                             .format(profile_id))
    return True


def create_body_master_sketch(doc, special_profiles=None):
    """Create the FreeCAD 1.1 Body Master Sketch foundation.

    This is deliberately the first migration step only.  The master contains
    the body contour, bridge reference and every successfully converted pocket
    region with stable SVG IDs and depth/target metadata.  ``MakeInternals`` is
    enabled so subsequent native Part Design operations can bind selected
    closed regions.  Once present, the master is the authoritative Body contour
    and SVG-pocket source; the older separate sketches remain import/fallback
    sources during the staged native-operation migration.

    Normal conversion is idempotent and never overwrites an edited master.
    Explicit Body SVG reimport removes it through ``remove_sketches``.
    """
    existing = doc.getObject(BODY_MASTER_SKETCH_NAME)
    if existing is not None:
        _group_sketch(doc, existing)
        for profile_id, wire in (special_profiles or {}).items():
            _append_body_master_special_profile(existing, profile_id, wire)
        _relink_body_master_consumers(doc, existing)
        return existing

    contour = doc.getObject(SKETCH_NAMES['Marz_Body_Contour'])
    bridge = doc.getObject(SKETCH_NAMES['Marz_Body_Bridge'])
    pockets = doc.getObject(POCKET_SKETCH_NAMES['body'])
    if contour is None or not getattr(contour, 'SVGConversionValid', True):
        return None

    contour_map = _json_element_map(contour)
    contour_elements = contour_map.get('elements', [])
    if len(contour_elements) != 1 or not contour_elements[0].get('indices'):
        raise ValueError('Body contour has no usable SVG element map')

    master = doc.addObject('Sketcher::SketchObject', BODY_MASTER_SKETCH_NAME)
    try:
        # All current body SVG sources share one anchored local coordinate
        # system.  Keep that placement on the master and copy only semantic
        # source geometry, excluding exposed B-spline construction helpers.
        master.Placement = contour.Placement
        # The master mirrors the established contour display transform but is
        # not itself an input to body placement.  Recording the transform here
        # makes the coordinate ownership explicit and prevents future code from
        # mistaking an already-positioned master for an unpositioned source.
        if 'MarzBodySketchTransform' in getattr(contour, 'PropertiesList', []):
            master.addProperty('App::PropertyPlacement', 'MarzBodySketchTransform',
                               'Marz SVG',
                               'Guitar positioning mirrored from Body contour')
            master.MarzBodySketchTransform = contour.MarzBodySketchTransform
        elements = []

        contour_indices = _copy_master_geometry(
            master, contour, contour_elements[0]['indices'])
        _join_master_loop(master, contour_indices)
        elements.append({
            'id': 'contour', 'role': 'body-contour',
            'indices': contour_indices,
            'source': contour.Name,
        })

        if bridge is not None and getattr(bridge, 'SVGConversionValid', True):
            bridge_map = _json_element_map(bridge)
            for item in bridge_map.get('elements', []):
                copied = _copy_master_geometry(
                    master, bridge, item.get('indices', []), construction=True)
                if copied:
                    elements.append({
                        'id': item.get('id', 'bridge'),
                        'role': 'reference', 'indices': copied,
                        'construction': True, 'source': bridge.Name,
                    })

        if pockets is not None and getattr(pockets, 'SVGConversionValid', False):
            pocket_map = _json_element_map(pockets)
            for item in pocket_map.get('elements', []):
                copied = _copy_master_geometry(
                    master, pockets, item.get('indices', []))
                if not copied:
                    continue
                _join_master_loop(master, copied)
                elements.append({
                    'id': item['id'], 'role': 'pocket', 'indices': copied,
                    'start': item.get('start', 0),
                    'depth': item.get('depth', 0),
                    'target': item.get('target', ''),
                    'source': pockets.Name,
                })

        for profile_id, wire in (special_profiles or {}).items():
            if wire is None:
                continue
            curves = _pocket_geometry(wire)
            indices = []
            for curve in curves:
                index = master.addGeometry(curve, False)
                indices.append(index)
                if type(curve).__name__ == 'BSplineCurve':
                    helpers = master.exposeInternalGeometry(index)
                    if helpers is not None and helpers <= 0:
                        raise ValueError('Sketcher failed to expose master B-spline controls')
            _join_master_loop(master, indices)
            elements.append({
                'id': profile_id, 'role': 'neck-pocket', 'indices': indices,
                'source': 'body-svg',
            })

        if not hasattr(master, 'MakeInternals'):
            raise ValueError('This FreeCAD build does not expose Sketcher MakeInternals')
        master.MakeInternals = True
        if 'SVGSourceDocument' not in master.PropertiesList:
            master.addProperty('App::PropertyString', 'SVGSourceDocument',
                               'Marz SVG', 'Imported SVG category')
        if 'SVGElementMap' not in master.PropertiesList:
            master.addProperty('App::PropertyString', 'SVGElementMap',
                               'Marz SVG',
                               'Semantic regions in the Body Master Sketch')
        if 'SVGConversionValid' not in master.PropertiesList:
            master.addProperty('App::PropertyBool', 'SVGConversionValid',
                               'Marz SVG', 'Whether this master sketch is usable')
        master.SVGSourceDocument = 'body'
        master.SVGConversionValid = True
        master.SVGElementMap = json.dumps({
            'version': 2, 'source_document': 'body', 'elements': elements,
            'operations': _master_operation_groups(elements),
        }, sort_keys=True, separators=(',', ':'))
        master.Label = 'Body Master Sketch'
        master.recompute()
        if getattr(master, 'RedundantConstraints', []):
            raise ValueError('Body Master Sketch has redundant constraints')
        if getattr(master, 'ConflictingConstraints', []):
            raise ValueError('Body Master Sketch has conflicting constraints')
        master.ViewObject.Visibility = False
        _group_sketch(doc, master)
        App.Console.PrintMessage(
            '[Marz SVG] Body Master Sketch ready: {} semantic region(s); '
            'MakeInternals enabled\n'.format(len(elements)))
        _relink_body_master_consumers(doc, master)
        return master
    except Exception:
        if doc.getObject(master.Name) is not None:
            doc.removeObject(master.Name)
        raise

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
    names = list(source_names)
    for source_name in names:
        sketch_name = SKETCH_NAMES.get(source_name)
        if sketch_name and doc.getObject(sketch_name) is not None:
            doc.removeObject(sketch_name)
    if any(name.startswith('Marz_Body_') for name in names):
        master = doc.getObject(BODY_MASTER_SKETCH_NAME)
        if master is not None:
            doc.removeObject(master.Name)


def _relink_body_contour(doc):
    """An explicit SVG reimport replaces the sketch; update native Body bases.

    A deleted Sketcher object leaves an old App::Link pointing at nothing.
    Attach each existing extrusion's contour Link to the newly imported
    source (or the original wire when conversion was rejected). Never
    regenerate either body's independent dimensions or cutter parameters.
    """
    contour = source_object(doc, 'Marz_Body_Contour')
    if contour is None:
        return
    # Existing derived parts already expect SVG sketches in the body frame.
    # A newly imported sketch starts at SVG coordinates; migrate the fresh
    # contour/pockets/bridge to the same frame without regenerating the body.
    result = doc.getObject('Marz_Body_Top') or doc.getObject('Marz_Body_Back')
    if result is not None:
        # The editable shared source always lives on the Top plane.  Since
        # 0.1.60 SourceDisplay is half-specific (the Back result stores the
        # Back frame), so use the persisted TopPlacement when available.
        frame = (result.TopPlacement if 'TopPlacement' in result.PropertiesList
                 else result.SourceDisplay if 'SourceDisplay' in result.PropertiesList
                 else None)
        if frame is not None:
            from freecad.marz.feature.body_parametric import _position_body_sources
            _position_body_sources(doc, frame)
    profile = doc.getObject('Marz_Body_Top_MasterContour')
    link_source = (profile if profile is not None and getattr(profile, 'Source', None) is not None
                   else contour)
    for name in ('Marz_Body_Top_Extrusion_ContourLink',
                 'Marz_Body_Back_Extrusion_ContourLink'):
        link = doc.getObject(name)
        if link is not None and link.LinkedObject is not link_source:
            link.LinkedObject = link_source


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


def _move_sketch(doc, sketch, group):
    """A sketch has exactly one owning group in the tree."""
    for owner in doc.Objects:
        if (owner is not group and getattr(owner, 'TypeId', '') == 'App::DocumentObjectGroup'
                and sketch in owner.Group):
            owner.removeObject(sketch)
    if sketch not in group.Group:
        group.addObject(sketch)


def _child_group(doc, name, label, parent=None):
    group = doc.getObject(name)
    if group is None:
        group = doc.addObject('App::DocumentObjectGroup', name)
        group.Label = label
    if parent is not None and group not in parent.Group:
        parent.addObject(group)
    return group


def _group_sketch(doc, sketch):
    """Store editable geometry with its consumer, not under Imported objects."""
    if sketch.Name.startswith('Marz_Sketch_Body') or sketch.Name == 'Marz_Sketch_BridgeRef':
        parts = _child_group(doc, 'Marz_Group_Parts', 'Generated parts')
        group = _child_group(doc, 'Marz_Group_Body', 'Body', parts)
    elif sketch.Name.startswith(FRET_INLAY_SKETCH_PREFIX):
        parts = _child_group(doc, 'Marz_Group_Parts', 'Generated parts')
        fretboard = _child_group(doc, 'Marz_Group_Fretboard', 'Fretboard', parts)
        group = _child_group(doc, 'Marz_Group_Fretboard_InlaySources',
                             'Inlay sources', fretboard)
    elif sketch.Name.startswith('Marz_Sketch_Headstock'):
        parts = _child_group(doc, 'Marz_Group_Parts', 'Generated parts')
        group = _child_group(doc, 'Marz_Group_Headstock', 'Headstock construction', parts)
    else:
        imports = doc.getObject('Marz_Group_Imports')
        group = _child_group(doc, GROUP_NAME, 'Editable SVG sketches', imports)
    _move_sketch(doc, sketch, group)


def organize_sketch_tree(doc):
    """Rehome existing sketches without regenerating, modifying or deleting them."""
    names = (list(SKETCH_NAMES.values()) + list(POCKET_SKETCH_NAMES.values())
             + [BODY_MASTER_SKETCH_NAME])
    names += [obj.Name for obj in doc.Objects
              if obj.Name.startswith(FRET_INLAY_SKETCH_PREFIX)]
    for name in names:
        sketch = doc.getObject(name)
        if sketch is not None:
            _group_sketch(doc, sketch)
    legacy = doc.getObject(GROUP_NAME)
    if legacy is not None and not legacy.Group:
        doc.removeObject(GROUP_NAME)
    _relink_body_contour(doc)


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
            is_connected_contour = (
                source_name in ('Marz_Body_Contour', 'Marz_Headstock_Contour')
                and len(original.Shape.Edges) > 1
                and _usable_connected_contour(existing))
            difference = _shape_difference(original.Shape, existing.Shape)
            if is_connected_contour or difference is None:
                existing.SVGConversionValid = True
                existing.SVGConversionError = ''
                existing.Label = original.Label + ' (edit in Sketcher)'
                if source_name == 'Marz_Body_Contour':
                    _relink_body_contour(doc)
                if difference is None:
                    App.Console.PrintMessage('[Marz SVG] Accepted existing sketch within '
                                             f'{SVG_SKETCH_TOLERANCE_MM:g} mm tolerance: '
                                             + source_name + '\n')
                else:
                    App.Console.PrintWarning('[Marz SVG] {}: connected contour accepted; '
                                             'Sketcher solver changed the SVG geometry: {}\n'
                                             .format(source_name, difference))
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
            # Directly convert straight SVG paths (including the bridge
            # reference) to native Sketcher lines. Draft remains the fallback
            # for genuinely curved references.
            temp = _create_straight_reference_sketch(doc, source_shape,
                                                      sketch_name)
            if temp is None:
                temp = _create_constrained_sketch(doc, source_shape, sketch_name)
        if getattr(temp, 'RedundantConstraints', []):
            raise ValueError('Initial endpoint joins are redundant')
        if getattr(temp, 'ConflictingConstraints', []):
            raise ValueError('Initial endpoint joins conflict')
        _persist_source_ids(temp, source_name,
                            list(range(len(source_shape.Edges))) if is_contour else None)
        # For ordinary references geometry fidelity remains a validity gate.
        # Mixed contours are different: endpoint Coincident constraints are
        # mandatory, and Sketcher may move under-constrained spline poles while
        # satisfying them.  A structurally valid, closed contour remains the
        # model source; report its drift instead of discarding connectivity.
        exact_difference = _shape_difference(source_shape, temp.Shape, 1e-4)
        difference = _shape_difference(source_shape, temp.Shape)
        if is_contour and len(source_shape.Edges) > 1:
            if not _usable_connected_contour(temp):
                raise ValueError('Sketch contour is not a connected closed loop')
            if difference is not None:
                App.Console.PrintWarning('[Marz SVG] {}: connected contour accepted; '
                                         'Sketcher solver changed the SVG geometry: {}\n'
                                         .format(source_name, difference))
            elif exact_difference is not None:
                App.Console.PrintMessage('[Marz SVG] Accepted connected contour with '
                                         'minor solver adjustment: {} ({})\n'
                                         .format(source_name, exact_difference))
        else:
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
        if source_name == 'Marz_Body_Contour':
            _relink_body_contour(doc)
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
            if source_name == 'Marz_Body_Contour':
                _relink_body_contour(doc)
            App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                     + '; left rejected sketch visible for inspection; '
                                     'original SVG remains model source\n')
            return temp
        App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                 + '; no sketch was created; original SVG remains model source\n')
        return existing



def _editable_closed_wire_geometry(wire):
    """Return natural Sketcher geometry for one closed imported inlay wire.

    Unlike the body/headstock contour, inlays may contain exact circular or
    elliptical *arcs*. Keep those as native Sketcher conics rather than forcing
    a crescent/arc chain through the cubic-only contour converter.
    """
    import Part
    if not wire.isClosed():
        raise ValueError('inlay wire is open')
    if len(wire.Edges) == 1:
        curve = wire.Edges[0].Curve
        if type(curve).__name__ in ('Circle', 'Ellipse'):
            return [curve], []
    geometry, spline_indices = [], []
    for edge in wire.Edges:
        straight = _straight_edge_vertices(edge)
        if straight is not None:
            geometry.append(Part.LineSegment(straight[0], straight[1]))
            continue
        curve = edge.Curve
        kind = type(curve).__name__
        if kind == 'Circle':
            geometry.append(Part.ArcOfCircle(curve, edge.FirstParameter,
                                             edge.LastParameter))
            continue
        if kind == 'Ellipse':
            geometry.append(Part.ArcOfEllipse(curve, edge.FirstParameter,
                                              edge.LastParameter))
            continue
        poles = _cubic_edge_poles(edge)
        if poles is not None:
            spline = Part.BSplineCurve()
            spline.buildFromPolesMultsKnots(
                poles, [4, 4], [0.0, 1.0], False, 3)
            spline_indices.append(len(geometry))
            geometry.append(spline)
            continue
        # Last exact fallback for already-native B-spline edges. Segment the
        # curve to this edge's parameter interval rather than importing its
        # full underlying curve.
        if kind == 'BSplineCurve' and hasattr(curve, 'copy'):
            spline = curve.copy()
            if hasattr(spline, 'segment'):
                spline.segment(edge.FirstParameter, edge.LastParameter)
            spline_indices.append(len(geometry))
            geometry.append(spline)
            continue
        raise ValueError('unsupported inlay edge type: ' + kind)
    return geometry, spline_indices


def _inlay_source_objects(doc):
    import re
    found = []
    pattern = re.compile(r'^Marz_FInlay_Fret(\d+)$')
    for obj in doc.Objects:
        match = pattern.match(obj.Name)
        if match and getattr(obj, 'Shape', None) is not None and not obj.Shape.isNull():
            found.append((int(match.group(1)), obj))
    return sorted(found, key=lambda item: item[0])


def remove_fret_inlay_sketches(doc):
    """Explicit inlay SVG reimport resets only its editable inlay sources."""
    for obj in list(doc.Objects):
        if obj.Name.startswith(FRET_INLAY_SKETCH_PREFIX):
            doc.removeObject(obj.Name)


def create_fret_inlay_sketches(doc):
    """Create one editable local Sketcher profile per imported fret inlay.

    The legacy `Marz_FInlay_FretN` objects are retained as compatibility
    references. Their shapes are already centered locally by the original
    importer; each sketch therefore remains easy to edit around its own origin,
    while the fretboard construction places it at the proper fret later.
    """
    import Part
    result = []
    _configure_sketcher_display_defaults()
    for fret, source in _inlay_source_objects(doc):
        name = FRET_INLAY_SKETCH_PREFIX + str(fret)
        existing = doc.getObject(name)
        if existing is not None:
            _group_sketch(doc, existing)
            result.append(existing)
            continue
        sketch = doc.addObject('Sketcher::SketchObject', name)
        profiles = []
        try:
            faces = list(source.Shape.Faces)
            if not faces:
                raise ValueError('imported inlay contains no face')
            for face in faces:
                wire_maps = []
                wires = list(getattr(face, 'Wires', [])) or [face.OuterWire]
                # Put the outer wire first so the cutter can preserve holes.
                outer = getattr(face, 'OuterWire', None)
                if outer is not None:
                    def same_wire(wire):
                        try:
                            return wire.isSame(outer)
                        except Exception:
                            return wire is outer
                    wires = [outer] + [wire for wire in wires if not same_wire(wire)]
                for wire in wires:
                    geometry, spline_rel = _editable_closed_wire_geometry(wire)
                    added = sketch.addGeometry(geometry, False)
                    indices = list(added) if isinstance(added, (list, tuple)) else [added]
                    if len(indices) > 1:
                        # Use the original wire topology to select the proper
                        # endpoints even when a conic/curve is reversed.
                        draft_like = type('InlayGeometry', (), {
                            'Geometry': geometry, 'Placement': App.Placement()})()
                        sketch.addConstraint(_initial_endpoint_constraints(
                            wire, draft_like, index_offset=indices[0]))
                        sketch.recompute()
                    for rel in spline_rel:
                        helpers = sketch.exposeInternalGeometry(indices[rel])
                        if helpers is not None and helpers <= 0:
                            raise ValueError('Sketcher failed to expose inlay B-spline controls')
                    wire_maps.append(indices)
                profiles.append({'wires': wire_maps})
            if 'SVGSourceDocument' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyString', 'SVGSourceDocument', 'Marz SVG',
                                   'Imported SVG category')
            if 'SVGElementMap' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyString', 'SVGElementMap', 'Marz SVG',
                                   'Inlay face/wire geometry index map')
            if 'FretNumber' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyInteger', 'FretNumber', 'Marz SVG',
                                   'Fret receiving this inlay')
            if 'SVGConversionValid' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyBool', 'SVGConversionValid', 'Marz SVG',
                                   'Whether this inlay sketch is usable')
            sketch.SVGSourceDocument = 'inlays'
            sketch.FretNumber = fret
            sketch.SVGConversionValid = True
            sketch.SVGElementMap = json.dumps({'version': 1, 'fret': fret,
                                               'profiles': profiles},
                                              sort_keys=True, separators=(',', ':'))
            sketch.Label = 'Fret {} inlay (edit in Sketcher)'.format(fret)
            sketch.recompute()
            sketch.ViewObject.Visibility = False
            _group_sketch(doc, sketch)
            result.append(sketch)
            App.Console.PrintMessage('[Marz SVG] Inlay sketch ready: {} (fret {})\n'
                                     .format(name, fret))
        except Exception as exc:
            if 'SVGConversionValid' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyBool', 'SVGConversionValid', 'Marz SVG',
                                   'Whether this inlay sketch is usable')
            if 'SVGConversionError' not in sketch.PropertiesList:
                sketch.addProperty('App::PropertyString', 'SVGConversionError', 'Marz SVG',
                                   'Inlay sketch conversion error')
            sketch.SVGConversionValid = False
            sketch.SVGConversionError = str(exc)
            sketch.Label = 'Fret {} inlay (conversion incomplete)'.format(fret)
            sketch.ViewObject.Visibility = True
            _group_sketch(doc, sketch)
            result.append(sketch)
            App.Console.PrintWarning('[Marz SVG] Could not create inlay sketch for fret {}: {}\n'
                                     .format(fret, exc))
    return result


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
    import Part

    result = []
    for category, stored_file in (('body', File_Svg_Body),
                                  ('headstock', File_Svg_Headstock)):
        name = POCKET_SKETCH_NAMES[category]
        existing = doc.getObject(name)
        master = doc.getObject(BODY_MASTER_SKETCH_NAME) if category == 'body' else None
        master_has_neckpocket = any(
            item.get('id') == 'neckpocket'
            for item in _json_element_map(master).get('elements', []))
        need_body_neckpocket = (category == 'body' and not master_has_neckpocket)
        if existing is not None and not need_body_neckpocket:
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
            contour = midline = neckpocket = None
            pockets = []
            for obj in temp_doc.Objects:
                match = NAME_ID_PATTERN.match(obj.Name)
                source_id = match.group(1) if match else None
                if source_id == 'contour':
                    contour = obj
                elif source_id == 'midline':
                    midline = obj
                elif category == 'body' and source_id == 'neckpocket':
                    neckpocket = obj
                else:
                    extract_pocket(obj, pockets, primitive_types)

            if not pockets and not (category == 'body' and neckpocket is not None):
                App.Console.PrintWarning('[Marz SVG] No pocket IDs found in embedded {} SVG\n'
                                         .format(category))
                continue
            if contour is None or midline is None:
                raise ValueError('missing contour/midline required to align pocket geometry')
            distance, vertices, _edges = midline.Shape.distToShape(contour.Shape)
            if distance > 1e-7 or not vertices:
                raise ValueError('contour/midline do not intersect at the import anchor')
            anchor = vertices[0][0]

            neckpocket_wire = None
            if category == 'body' and neckpocket is not None:
                neckpocket_wire = Part.Wire(neckpocket.Shape.copy().Edges)
                neckpocket_wire.translate(-anchor)

            App.setActiveDocument(doc.Name)
            if existing is not None:
                result.append(existing)
            elif pockets:
                result.append(create_pocket_sketch(doc, pockets, category, anchor))
            if category == 'body' and neckpocket_wire is not None:
                create_body_master_sketch(
                    doc, special_profiles={'neckpocket': neckpocket_wire})
        except Exception as exc:
            App.Console.PrintWarning('[Marz SVG] Could not create {} pocket sketch '
                                     'from embedded SVG: {}\n'.format(category, exc))
        finally:
            App.setActiveDocument(doc.Name)
            App.closeDocument(temp_doc.Name)
    # Newly recovered pocket sketches need the same positioned body frame as
    # the existing contour and body features; a user need not regenerate the
    # body just to see the imported pockets at their correct location.
    _relink_body_contour(doc)
    return result


def create_all(doc, source_names=None):
    names = list(source_names) if source_names is not None else list(SKETCH_NAMES)
    sketches = [create_sketch(doc, name) for name in names
                if name in SKETCH_NAMES and doc.getObject(name) is not None]
    if any(name.startswith('Marz_Body_') for name in names):
        # On SVG reimport the bridge can be recreated *after* the contour.
        # Align all new editable sources only once the batch is complete.
        _relink_body_contour(doc)
    return sketches
