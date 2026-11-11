# SPDX-License-Identifier: GPL-3.0-or-later
"""FreeCAD-independent logical fret-inlay grouping for authored SVG files.

This is a Marz semantic consumer of the generic SVG reader.  It resolves the
shared inlay naming grammar on individual SVG elements and on ancestor groups,
then groups individually tagged elements by placement semantics while keeping
explicitly tagged SVG groups distinct.
"""
from dataclasses import dataclass
from xml.etree import ElementTree

from freecad.marz.svg_semantics import SemanticSyntaxError, resolve_inlay
from freecad.marz.svg_to_sketch.reader import read_svg

INKSCAPE_LABEL = '{http://www.inkscape.org/namespaces/inkscape}label'


@dataclass(frozen=True)
class InlayAssignment:
    """One rendered SVG element assigned to one logical Marz inlay."""
    element_id: str
    element_label: str
    key: tuple
    reference: str
    semantic: object
    owner_kind: str  # ``group`` or ``standalone``
    owner_id: str = ''
    owner_label: str = ''
    element: object = None


@dataclass(frozen=True)
class InlaySemanticError:
    reference: str
    reason: str


def _group_labels(filename):
    labels = {}
    for node in ElementTree.parse(filename).iter():
        if node.tag.rsplit('}', 1)[-1] != 'g':
            continue
        group_id = node.get('id', '')
        if group_id:
            labels[group_id] = node.get(INKSCAPE_LABEL, '')
    return labels


def collect_inlay_assignments(filename):
    """Return ``(assignments, errors)`` for rendered vector SVG elements.

    A valid semantic designation on the nearest ancestor ``<g>`` owns all of
    that group's supported descendants.  Otherwise the element's own ID/label
    is resolved.  Standalone elements with equal fret/X/Y placement semantics
    share a logical key regardless of descriptive suffixes.  Explicit groups
    remain distinct even when their placement semantics are identical.
    """
    labels = _group_labels(filename)
    assignments = []
    errors = []
    seen_errors = set()

    def remember_error(exc):
        item = (exc.text, exc.reason)
        if item not in seen_errors:
            seen_errors.add(item)
            errors.append(InlaySemanticError(*item))

    for element in read_svg(filename):
        resolved = None
        owner_kind = 'standalone'
        owner_id = ''
        owner_label = ''

        # Nearest semantic group wins.  A malformed semantic-looking group is
        # reported but does not hide a valid child designation.
        for group_id in reversed(element.group_ids):
            if not group_id:
                continue
            group_label = labels.get(group_id, '')
            try:
                candidate = resolve_inlay(group_id, group_label)
            except SemanticSyntaxError as exc:
                remember_error(exc)
                continue
            if candidate is not None:
                resolved = candidate
                owner_kind = 'group'
                owner_id = group_id
                owner_label = group_label
                break

        if resolved is None:
            try:
                resolved = resolve_inlay(element.id, element.label)
            except SemanticSyntaxError as exc:
                remember_error(exc)
                continue

        if resolved is None:
            continue

        semantic = resolved.value
        if owner_kind == 'group':
            # SVG IDs are required to be unique, so the owning group ID is a
            # stable logical identity while preserving same-position groups.
            key = ('group', owner_id)
        else:
            key = ('standalone',) + tuple(semantic.placement_key)

        assignments.append(InlayAssignment(
            element.id, element.label, key, resolved.text, semantic,
            owner_kind, owner_id, owner_label, element))

    return tuple(assignments), tuple(errors)
