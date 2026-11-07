# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Convert existing Marz SVG imports into editable native Sketcher sources."""

from freecad.marz.extension.fc import App
from freecad.marz.extension.lang import tr
from freecad.marz.extension.paths import iconPath
from freecad.marz.feature.svg_sketch import (SKETCH_NAMES, create_all,
                                            create_pocket_sketches_from_embedded_svg)


class CmdConvertSvgSketch:
    def GetResources(self):
        return {
            'MenuText': tr('Create editable SVG sketches'),
            'ToolTip': tr('Convert body/headstock SVG references to native Sketcher objects'),
            'Pixmap': iconPath('import_svg.svg'),
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return bool(doc and any(doc.getObject(name) for name in SKETCH_NAMES))

    def Activated(self):
        doc = App.ActiveDocument
        if doc is None:
            return
        # Idempotent: never overwrite an existing edited sketch.
        create_all(doc)
        create_pocket_sketches_from_embedded_svg(doc)
        doc.recompute()
