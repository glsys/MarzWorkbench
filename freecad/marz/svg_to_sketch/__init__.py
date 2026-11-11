# SPDX-License-Identifier: GPL-3.0-or-later
"""FreeCAD-independent SVG reader plus optional native Sketcher adapter.

No guitar-specific naming or placement logic lives in this package.
"""
from .reader import Affine, Element, Primitive, SVGReadError, read_svg, parse_path
