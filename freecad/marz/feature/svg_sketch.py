# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Editable Sketcher sources for SVG reference paths.

Keep Marz's original imported wires alongside the sketches. The sketches are
created only from a valid, already transformed and anchored import shape;
none of the SVG coordinate conversion is repeated here.
"""

from freecad.marz.extension.fc import App

# Source IDs remain unchanged for legacy documents and SVG import metadata.
SKETCH_NAMES = {
    'Marz_Body_Contour': 'Marz_Sketch_BodyContour',
    'Marz_Body_Bridge': 'Marz_Sketch_BridgeRef',
    'Marz_Headstock_Contour': 'Marz_Sketch_HeadstockContour',
    'Marz_Headstock_Transition': 'Marz_Sketch_HeadstockTransition',
}
GROUP_NAME = 'Marz_Group_SVG_Sketches'


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


def _shape_difference(original, converted, tolerance=1e-4):
    """Return a real geometric discrepancy, or None for equivalent geometry.

    Draft.make_sketch converts Bezier segments to equivalent B-splines and
    orients the segments to the sketch plane. Sketcher may also enumerate
    segments differently. None of those operations changes the actual curve;
    matching edge *indices* and directions would reject valid SVG contours.

    Still require the same number of edges, their complete sampled paths,
    total length, world bounds and closed/open status. Do not accept an
    approximation or an accidentally displaced outline.
    """
    if converted.isNull():
        return 'empty Sketcher shape'
    source_edges, sketch_edges = original.Edges, converted.Edges
    if len(source_edges) != len(sketch_edges):
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


def _matching_shape(original, converted, tolerance=1e-4):
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
    import Draft

    sketch_name = SKETCH_NAMES[source_name]
    existing = doc.getObject(sketch_name)
    if existing is not None:
        # Never replace manually edited sketches through a normal command.
        # Explicit SVG reimport removes this sketch before calling here.
        return existing
    original = doc.getObject(source_name)
    if original is None or original.Shape.isNull() or not original.Shape.Edges:
        return None

    # Draft.make_sketch accepts a Part.Shape, preserving arcs and B-splines.
    # It uses the active document, which must be our source document.
    if App.ActiveDocument is not doc:
        App.setActiveDocument(doc.Name)
    source_shape = original.Shape.copy()
    temp = None
    try:
        temp = Draft.make_sketch(source_shape, autoconstraints=False,
                                 delete=False, name=sketch_name,
                                 tol=1e-5)
        if temp is None:
            raise ValueError('Draft.make_sketch returned no sketch')
        temp.recompute()
        difference = _shape_difference(source_shape, temp.Shape)
        if difference is not None:
            raise ValueError('Sketch geometry differs from SVG reference: ' + difference)
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
            App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                     + '; left rejected sketch visible for inspection; '
                                     'original SVG remains model source\n')
            return temp
        App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                 + '; no sketch was created; original SVG remains model source\n')
        return existing


def create_all(doc, source_names=None):
    names = list(source_names) if source_names is not None else list(SKETCH_NAMES)
    return [create_sketch(doc, name) for name in names
            if name in SKETCH_NAMES and doc.getObject(name) is not None]
