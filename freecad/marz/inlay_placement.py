# SPDX-License-Identifier: GPL-3.0-or-later
"""FreeCAD-independent 2D placement for logical fretboard inlays.

The input cell is the actual quadrilateral between fret N-1 and fret N,
ordered as previous-bass, previous-treble, next-treble, next-bass.  The
logical inlay is represented by its local axis-aligned bounding box.  The
cell is eroded by that box, producing the valid translation region for the
complete inlay.  Normalized X/Y semantics are then bilinearly mapped from
previous fret -> next fret and treble -> bass.
"""
from dataclasses import dataclass
from math import hypot


_EPS = 1e-9


@dataclass(frozen=True)
class Bounds2D:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    @property
    def corners(self):
        return (
            (self.min_x, self.min_y),
            (self.min_x, self.max_y),
            (self.max_x, self.min_y),
            (self.max_x, self.max_y),
        )


@dataclass(frozen=True)
class Placement2D:
    x: float
    y: float


@dataclass(frozen=True)
class _HalfPlane:
    nx: float
    ny: float
    c: float

    def value(self, point):
        return self.nx * point[0] + self.ny * point[1] - self.c


def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def _unit(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = hypot(dx, dy)
    if length <= _EPS:
        raise ValueError('degenerate inlay placement direction')
    return dx / length, dy / length


def _half_plane(a, b, inside, bounds):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if hypot(dx, dy) <= _EPS:
        raise ValueError('degenerate fret-space boundary')
    nx, ny = -dy, dx
    # Orient the normal into the fret-space cell.
    if nx * (inside[0] - a[0]) + ny * (inside[1] - a[1]) < 0:
        nx, ny = -nx, -ny
    # n.(t + q - a) >= 0 for every local bbox corner q.
    # Therefore n.t >= n.a - min_q(n.q).
    min_support = min(nx * q[0] + ny * q[1] for q in bounds.corners)
    c = nx * a[0] + ny * a[1] - min_support
    return _HalfPlane(nx, ny, c)


def _intersection(a, b):
    det = a.nx * b.ny - a.ny * b.nx
    if abs(det) <= _EPS:
        raise ValueError('parallel eroded fret-space boundaries')
    x = (a.c * b.ny - a.ny * b.c) / det
    y = (a.nx * b.c - a.c * b.nx) / det
    return x, y


def _bilerp(p00, p01, p10, p11, x, y):
    # X: previous fret -> next fret. Y: treble -> bass.
    a = ((1.0 - y) * p00[0] + y * p01[0],
         (1.0 - y) * p00[1] + y * p01[1])
    b = ((1.0 - y) * p10[0] + y * p11[0],
         (1.0 - y) * p10[1] + y * p11[1])
    return ((1.0 - x) * a[0] + x * b[0],
            (1.0 - x) * a[1] + x * b[1])


def place_inlay(cell, bounds: Bounds2D, align_x=0.5, align_y=0.5,
                 offset_x=0.0, offset_y=0.0, center_anchor=None):
    """Return the local-origin translation for one logical inlay.

    ``cell`` is ``(prev_bass, prev_treble, next_treble, next_bass)`` using
    ``(x, y)`` pairs.  With zero offsets the complete bounding box remains
    inside that quadrilateral for every normalized alignment in ``[0, 1]``.

    ``center_anchor`` optionally preserves the historical centered placement.
    The semantic displacement is measured relative to the eroded cell's
    0.5/0.5 point and added to that anchor, so the default semantic values are
    exactly backward compatible even if legacy and geometric cell centers
    differ by tiny construction tolerances.
    """
    if len(cell) != 4:
        raise ValueError('fret-space cell requires four corners')
    if not (0.0 <= align_x <= 1.0 and 0.0 <= align_y <= 1.0):
        raise ValueError('inlay alignment must be between 0 and 1')
    if bounds.max_x < bounds.min_x or bounds.max_y < bounds.min_y:
        raise ValueError('invalid inlay bounds')

    prev_bass, prev_treble, next_treble, next_bass = cell
    centroid = (
        sum(p[0] for p in cell) / 4.0,
        sum(p[1] for p in cell) / 4.0,
    )
    planes = {
        'prev': _half_plane(prev_bass, prev_treble, centroid, bounds),
        'next': _half_plane(next_treble, next_bass, centroid, bounds),
        'treble': _half_plane(prev_treble, next_treble, centroid, bounds),
        'bass': _half_plane(next_bass, prev_bass, centroid, bounds),
    }
    corners = {
        'p00': _intersection(planes['prev'], planes['treble']),
        'p01': _intersection(planes['prev'], planes['bass']),
        'p10': _intersection(planes['next'], planes['treble']),
        'p11': _intersection(planes['next'], planes['bass']),
    }
    # If the eroded cell is empty, at least one formal corner lies outside one
    # of the other two inward half-planes.
    for point in corners.values():
        if min(plane.value(point) for plane in planes.values()) < -1e-7:
            raise ValueError('inlay bounding box does not fit inside fret space')

    semantic = _bilerp(corners['p00'], corners['p01'],
                       corners['p10'], corners['p11'], align_x, align_y)
    center = _bilerp(corners['p00'], corners['p01'],
                     corners['p10'], corners['p11'], 0.5, 0.5)
    if center_anchor is not None:
        semantic = (center_anchor[0] + semantic[0] - center[0],
                    center_anchor[1] + semantic[1] - center[1])

    prev_mid = _mid(prev_bass, prev_treble)
    next_mid = _mid(next_bass, next_treble)
    treble_mid = _mid(prev_treble, next_treble)
    bass_mid = _mid(prev_bass, next_bass)
    ux, uy = _unit(prev_mid, next_mid)
    vx, vy = _unit(treble_mid, bass_mid)
    return Placement2D(
        semantic[0] + ux * float(offset_x) + vx * float(offset_y),
        semantic[1] + uy * float(offset_x) + vy * float(offset_y),
    )
