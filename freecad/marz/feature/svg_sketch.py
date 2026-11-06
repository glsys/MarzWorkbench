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
        if sketch is not None:
            return sketch
    return doc.getObject(source_name)


def remove_sketches(doc, source_names):
    """Only explicit SVG reimport resets the corresponding editable sketches."""
    for source_name in source_names:
        sketch_name = SKETCH_NAMES.get(source_name)
        if sketch_name and doc.getObject(sketch_name) is not None:
            doc.removeObject(sketch_name)


def _matching_shape(original, converted, tolerance=1e-4):
    """Reject changed/missing path geometry, including loss of closed wires."""
    if converted.isNull() or len(original.Edges) != len(converted.Edges):
        return False
    if original.isClosed() != converted.isClosed():
        return False
    if abs(original.Length - converted.Length) > tolerance:
        return False
    a, b = original.BoundBox, converted.BoundBox
    for field in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax'):
        if abs(getattr(a, field) - getattr(b, field)) > tolerance:
            return False
    # Downstream algorithms also inspect individual edge indices/tangents.
    # Reject curve reordering and reversal, not merely a different outer wire.
    for src_edge, dst_edge in zip(original.Edges, converted.Edges):
        src_points = src_edge.discretize(Number=11)
        dst_points = dst_edge.discretize(Number=11)
        if len(src_points) != len(dst_points):
            return False
        for src, dst in zip(src_points, dst_points):
            if (src - dst).Length > tolerance:
                return False
    return True


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
        if not _matching_shape(source_shape, temp.Shape):
            raise ValueError('Sketch geometry differs from SVG reference (closure, curve, or position)')
        temp.Label = original.Label + ' (edit in Sketcher)'
        temp.ViewObject.Visibility = False
        group = doc.getObject(GROUP_NAME)
        if group is None:
            group = doc.addObject('App::DocumentObjectGroup', GROUP_NAME)
            group.Label = 'Editable SVG sketches'
            imports = doc.getObject('Marz_Group_Imports')
            if imports is not None:
                imports.addObject(group)
        group.addObject(temp)
        App.Console.PrintMessage('[Marz SVG] Sketch ready: ' + source_name + '\n')
        return temp
    except Exception as exc:
        if temp is not None and doc.getObject(temp.Name) is not None:
            doc.removeObject(temp.Name)
        App.Console.PrintWarning('[Marz SVG] ' + source_name + ': ' + str(exc)
                                 + '; retained original imported geometry\n')
        return existing


def create_all(doc, source_names=None):
    names = list(source_names) if source_names is not None else list(SKETCH_NAMES)
    return [create_sketch(doc, name) for name in names
            if name in SKETCH_NAMES and doc.getObject(name) is not None]
