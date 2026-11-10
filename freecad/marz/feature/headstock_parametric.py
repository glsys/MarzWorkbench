# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Native PartDesign headstock plate and SVG-pocket history."""

import json
import math

from freecad.marz.extension.fc import App, Vector, Placement, Rotation
from freecad.marz.feature.logging import MarzLogger
from freecad.marz.feature.body_parametric import (
    _profile_binder, _semantic_edge_subnames, _set_native_direction,
    _add_operation_metadata, _valid_solid,
)

HEADSTOCK_BODY = 'Marz_Neck_Headstock'
HEADSTOCK_GROUP = 'Marz_Group_Headstock'
HEADSTOCK_MASTER = 'Marz_Sketch_HeadstockMaster'
PAD_PROFILE = HEADSTOCK_BODY + '_PadProfile'
PAD = HEADSTOCK_BODY + '_Extrusion'
POCKET_PROFILE_PREFIX = HEADSTOCK_BODY + '_PocketProfile_'
POCKET_PREFIX = HEADSTOCK_BODY + '_Pocket_'


def _master_map(master):
    try:
        return json.loads(master.SVGElementMap)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Headstock Master Sketch has no valid semantic map') from exc


def _semantic_item(master, role):
    for item in _master_map(master).get('elements', []):
        if item.get('role') == role and item.get('indices'):
            return item
    raise ValueError('Headstock Master Sketch has no {} region'.format(role))


def _operation_groups(master):
    groups = {}
    for item in _master_map(master).get('elements', []):
        if item.get('role') != 'pocket':
            continue
        start = float(item.get('start', 0))
        depth = float(item.get('depth', 0))
        if start < 0 or depth <= 0:
            raise ValueError('invalid headstock pocket {}'.format(item.get('id')))
        key = (start, start + depth)
        groups.setdefault(key, []).append(item['id'])
    return [(start, end, ids) for (start, end), ids in sorted(groups.items())]


def _group_edges(master, ids):
    by_id = {item.get('id'): item for item in _master_map(master).get('elements', [])}
    edges = []
    for semantic_id in ids:
        item = by_id.get(semantic_id)
        if item is None or item.get('role') != 'pocket':
            raise ValueError('missing Headstock Master pocket {}'.format(semantic_id))
        for edge in _semantic_edge_subnames(master, item):
            if edge not in edges:
                edges.append(edge)
    if not edges:
        raise ValueError('headstock pocket group has no master edges')
    return edges


def _geometry_endpoints(master, index):
    edge = master.Geometry[index].toShape()
    if len(edge.Vertexes) < 2:
        raise ValueError('Headstock Master geometry {} has no endpoints'.format(index))
    return edge.Vertexes[0].Point, edge.Vertexes[-1].Point


def _plate_profile_subnames(master):
    """Return contour path on the plate side plus the transition edge(s).

    Headstock contour conversion preserves its ordered SVG spans. The authored
    transition line must terminate on contour vertices; if it does not, keep the
    native failure visible instead of inventing derived profile geometry.
    """
    contour = _semantic_item(master, 'headstock-contour')
    transition = _semantic_item(master, 'headstock-transition')
    contour_indices = list(contour['indices'])
    transition_indices = list(transition['indices'])
    if not contour_indices or not transition_indices:
        raise ValueError('Headstock Master contour/transition is empty')

    # Transition may contain more than one connected straight segment. Determine
    # its two terminal points from endpoint incidence.
    endpoints = []
    for index in transition_indices:
        endpoints.extend(_geometry_endpoints(master, index))
    terminals = []
    tol = 0.001
    for point in endpoints:
        count = sum(1 for other in endpoints if (point - other).Length <= tol)
        if count == 1:
            terminals.append(point)
    if len(terminals) != 2:
        if len(transition_indices) == 1:
            terminals = list(_geometry_endpoints(master, transition_indices[0]))
        else:
            raise ValueError('Headstock transition does not have two terminals')

    # Ordered contour geometry gives one cyclic vertex at the start of every
    # span. Locate each transition terminal on that authored vertex sequence.
    starts = [_geometry_endpoints(master, index)[0] for index in contour_indices]
    vertex_slots = []
    for terminal in terminals:
        matches = [i for i, point in enumerate(starts)
                   if (point - terminal).Length <= tol]
        if len(matches) != 1:
            raise ValueError(
                'Headstock transition endpoint does not coincide with exactly one contour vertex')
        vertex_slots.append(matches[0])
    a, b = vertex_slots
    if a == b:
        raise ValueError('Headstock transition endpoints resolve to the same contour vertex')

    n = len(contour_indices)
    path_ab = []
    i = a
    while i != b:
        path_ab.append(contour_indices[i])
        i = (i + 1) % n
    path_ba = []
    i = b
    while i != a:
        path_ba.append(contour_indices[i])
        i = (i + 1) % n

    def mean_x(path):
        values = []
        for index in path:
            p0, p1 = _geometry_endpoints(master, index)
            values.extend((p0.x, p1.x))
        return sum(values) / len(values)

    # Marz headstocks extend in +X from the neck. Select the contour path on
    # that side, matching the old extrude_headstock_plate() face selection.
    selected = path_ab if mean_x(path_ab) > mean_x(path_ba) else path_ba
    item = {'indices': selected}
    subnames = _semantic_edge_subnames(master, item)
    for edge in _semantic_edge_subnames(master, transition):
        if edge not in subnames:
            subnames.append(edge)
    return subnames


def _remove_owned_features(doc, body):
    for child in reversed(list(getattr(body, 'Group', []))):
        if doc.getObject(child.Name) is not None:
            doc.removeObject(child.Name)


def _move_to_group(doc, obj, group):
    for owner in list(getattr(obj, 'InList', [])):
        if owner is not group and getattr(owner, 'TypeId', '') == 'App::DocumentObjectGroup':
            try:
                owner.removeObject(obj)
            except Exception:
                pass
    if obj not in group.Group:
        group.addObject(obj)


def _group(doc):
    parts = doc.getObject('Marz_Group_Parts')
    if parts is None:
        parts = doc.addObject('App::DocumentObjectGroup', 'Marz_Group_Parts')
        parts.Label = 'Generated parts'
    group = doc.getObject(HEADSTOCK_GROUP)
    if group is None:
        group = doc.addObject('App::DocumentObjectGroup', HEADSTOCK_GROUP)
    group.Label = 'Headstock'
    if group not in parts.Group:
        parts.addObject(group)
    return group


def _prepare_body(doc, group):
    existing = doc.getObject(HEADSTOCK_BODY)
    if existing is not None and existing.TypeId == 'PartDesign::Body':
        _remove_owned_features(doc, existing)
        existing.Label = 'Headstock Plate'
        _move_to_group(doc, existing, group)
        return existing
    if existing is not None:
        doc.removeObject(existing.Name)
        doc.recompute()
    body = doc.addObject('PartDesign::Body', HEADSTOCK_BODY)
    if body.Name != HEADSTOCK_BODY:
        raise ValueError('FreeCAD created {} instead of {}'.format(body.Name, HEADSTOCK_BODY))
    body.Label = 'Headstock Plate'
    _move_to_group(doc, body, group)
    return body


def _place_master(master, inst, fbd):
    line = fbd.neckFrame.midLine
    pos = Vector(line.start.x, line.start.y, 0)
    angle_deg = float(inst.headStock.angle)
    rotation = Rotation(Vector(0, 1, 0), angle_deg)
    # headstock_builder.place() translates first and rotates about global zero.
    # Placement therefore needs R*pos as its translation component.
    base = rotation.multVec(pos)
    master.Placement = Placement(base, rotation)
    return angle_deg


def regenerate_headstock(inst, fbd, doc):
    """Rebuild the native Headstock Pad + grouped SVG Pocket history."""
    from freecad.marz.feature.svg_sketch import create_headstock_master_sketch

    group = _group(doc)
    master = create_headstock_master_sketch(doc)
    if master is None or not getattr(master, 'SVGConversionValid', False):
        raise ValueError('Headstock Master Sketch is required for native Headstock construction')
    angle_deg = _place_master(master, inst, fbd)
    _move_to_group(doc, master, group)

    body = _prepare_body(doc, group)
    if 'BuildStatus' not in body.PropertiesList:
        body.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')

    profile = _profile_binder(
        body, PAD_PROFILE, 'Headstock Plate Profile', master,
        _plate_profile_subnames(master))
    if profile.ViewObject is not None:
        profile.ViewObject.Visibility = True

    pad = body.newObject('PartDesign::Pad', PAD)
    pad.Label = 'Headstock Plate Pad'
    if 'BuildStatus' not in pad.PropertiesList:
        pad.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')
    pad.Profile = profile
    thickness = float(inst.headStock.thickness) + (0 if angle_deg > 0 else float(inst.headStock.depth))
    pad.Length = thickness
    up = master.Placement.Rotation.multVec(Vector(0, 0, 1))
    down = Vector(-up.x, -up.y, -up.z)
    _set_native_direction(pad, down, reversed_fallback=True)
    if hasattr(pad, 'Refine'):
        pad.Refine = True

    try:
        doc.recompute()
        if not _valid_solid(pad.Shape):
            raise ValueError('Headstock PartDesign Pad produced no valid solid')
        pad.BuildStatus = 'OK'
        if profile.ViewObject is not None:
            profile.ViewObject.Visibility = False

        tip = pad
        index = 0
        top_offset = 0.0 if angle_deg > 0 else float(inst.headStock.depth)
        for start, end, ids in _operation_groups(master):
            lo = max(start + top_offset, 0.0)
            hi = min(end + top_offset, thickness)
            if hi <= lo:
                continue
            index += 1
            profile_label = 'Neck Pocket Profile {}..{} mm'.format(start, end)
            pocket_label = 'Neck Pocket {}..{} mm'.format(start, end)
            pocket_profile = _profile_binder(
                body, POCKET_PROFILE_PREFIX + '{:03d}'.format(index),
                profile_label, master, _group_edges(master, ids), -lo)
            if pocket_profile.ViewObject is not None:
                pocket_profile.ViewObject.Visibility = True

            body.Tip = tip
            pocket = body.newObject('PartDesign::Pocket', POCKET_PREFIX + '{:03d}'.format(index))
            pocket.Label = pocket_label
            if 'BuildStatus' not in pocket.PropertiesList:
                pocket.addProperty('App::PropertyString', 'BuildStatus', 'Diagnostics')
            pocket.Profile = pocket_profile
            if hasattr(pocket, 'AllowMultiFace'):
                pocket.AllowMultiFace = True
            pocket.Length = hi - lo
            _set_native_direction(pocket, down, reversed_fallback=False)
            if hasattr(pocket, 'Refine'):
                pocket.Refine = True
            _add_operation_metadata(pocket, '', start, end, ids)
            doc.recompute()
            if not _valid_solid(pocket.Shape):
                raise ValueError('{} produced no valid solid'.format(pocket.Label))
            pocket.BuildStatus = 'OK'
            if pocket_profile.ViewObject is not None:
                pocket_profile.ViewObject.Visibility = False
            tip = pocket

        body.Tip = tip
        body.BuildStatus = 'OK'
        if body.ViewObject is not None:
            body.ViewObject.Visibility = True
        for child in list(getattr(body, 'Group', [])):
            if child.ViewObject is None:
                continue
            if child.TypeId in ('PartDesign::Pad', 'PartDesign::Pocket'):
                child.ViewObject.Visibility = (child is tip)
            elif child.TypeId == 'PartDesign::SubShapeBinder':
                child.ViewObject.Visibility = False
        master.ViewObject.Visibility = False
        return body
    except Exception as exc:
        body.BuildStatus = 'ERROR: ' + str(exc)
        body.Label = 'Headstock Plate [FAILED]'
        if body.ViewObject is not None:
            body.ViewObject.Visibility = True
        try:
            if profile.ViewObject is not None:
                profile.ViewObject.Visibility = True
            if pad.ViewObject is not None:
                pad.ViewObject.Visibility = True
            if pocket_profile.ViewObject is not None:
                pocket_profile.ViewObject.Visibility = True
            if pocket.ViewObject is not None:
                pocket.ViewObject.Visibility = True
        except UnboundLocalError:
            pass
        MarzLogger.warn('[Marz Headstock] native history failed: {}; inspect visible features'.format(exc))
        raise
