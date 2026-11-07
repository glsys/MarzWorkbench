# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Editable per-element pocket metadata for Marz SVG Sketcher sources.

SVG IDs are immutable provenance, not storage for modified cutting parameters.
The sketch's SVGElementMap is the persistent source of start/depth/target.
"""

import json
import math

from freecad.marz.feature.svg_sketch import POCKET_SKETCH_NAMES, refresh_pocket_cutters


def pocket_elements(sketch):
    """Read and validate the saved SVG-ID -> geometry/operation mapping."""
    if sketch is None or not getattr(sketch, 'SVGConversionValid', False):
        raise ValueError('Missing or invalid editable SVG pocket sketch')
    data = json.loads(sketch.SVGElementMap)
    if not isinstance(data, dict) or not isinstance(data.get('elements'), list):
        raise ValueError('Invalid SVGElementMap')
    elements = data['elements']
    names = set()
    for entry in elements:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str):
            raise ValueError('Pocket element has no SVG ID')
        if entry['id'] in names:
            raise ValueError('Duplicate SVG ID: ' + entry['id'])
        names.add(entry['id'])
        if not isinstance(entry.get('indices'), list) or not entry['indices']:
            raise ValueError('Missing geometry indices: ' + entry['id'])
        try:
            start, depth = float(entry['start']), float(entry['depth'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Invalid depth metadata: ' + entry['id']) from exc
        if not math.isfinite(start) or not math.isfinite(depth) or start < 0 or depth <= 0:
            raise ValueError('Invalid depth metadata: ' + entry['id'])
        if entry.get('target') not in ('', 't', 'b'):
            raise ValueError('Invalid cutting target: ' + entry['id'])
    return elements


def set_pocket_properties(sketch, element_id, start, end, target):
    """Save one pocket's dimensions, then regenerate its cutters atomically.

    Return True on success, False when cutter generation fails. Errors for
    invalid user input are raised before changing the document.
    """
    category = sketch.SVGSourceDocument
    if category not in POCKET_SKETCH_NAMES or sketch.Name != POCKET_SKETCH_NAMES[category]:
        raise ValueError('Not a Marz pocket sketch')
    if not all(math.isfinite(float(v)) for v in (start, end)):
        raise ValueError('Pocket depths must be finite')
    start, end = float(start), float(end)
    if start < 0 or end <= start:
        raise ValueError('Require 0 ≤ start < end')
    allowed_targets = ('', 't', 'b') if category == 'body' else ('',)
    if target not in allowed_targets:
        raise ValueError('Unsupported target for ' + category)
    entries = pocket_elements(sketch)
    selected = next((entry for entry in entries if entry['id'] == element_id), None)
    if selected is None:
        raise ValueError('Unknown pocket SVG ID: ' + element_id)

    original = sketch.SVGElementMap
    data = json.loads(original)
    for entry in data['elements']:
        if entry['id'] == element_id:
            entry['start'] = start
            entry['depth'] = end - start
            entry['target'] = target
            break
    sketch.SVGElementMap = json.dumps(data, sort_keys=True, separators=(',', ':'))
    try:
        if not refresh_pocket_cutters(sketch.Document, category, clear_empty=True):
            sketch.SVGElementMap = original
            return False
    except Exception:
        sketch.SVGElementMap = original
        raise
    return True
