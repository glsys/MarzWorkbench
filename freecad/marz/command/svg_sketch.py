# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Convert existing Marz SVG imports into editable native Sketcher sources."""

from freecad.marz.extension.fc import App
from freecad.marz.extension.lang import tr
from freecad.marz.extension.paths import iconPath
from freecad.marz.feature.svg_sketch import (SKETCH_NAMES, create_all,
                                            create_pocket_sketches_from_embedded_svg,
                                            create_fret_inlay_sketches,
                                            create_body_master_sketch)


class CmdConvertSvgSketch:
    def GetResources(self):
        return {
            'MenuText': tr('Create editable SVG sketches'),
            'ToolTip': tr('Convert body/headstock/inlay SVG references to native Sketcher objects'),
            'Pixmap': iconPath('import_svg.svg'),
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return bool(doc and any(doc.getObject(name) for name in SKETCH_NAMES))

    def Activated(self):
        doc = App.ActiveDocument
        if doc is None:
            return
        App.Console.PrintMessage('[Marz SVG] Create editable sketches command started (embedded SVG import may follow)\n')
        # Idempotent: never overwrite an existing edited sketch.
        create_all(doc)
        create_pocket_sketches_from_embedded_svg(doc)
        create_body_master_sketch(doc)
        create_fret_inlay_sketches(doc)
        doc.recompute()


class CmdPocketProperties:
    def GetResources(self):
        return {
            'MenuText': tr('Edit pocket properties'),
            'ToolTip': tr('Edit SVG pocket start/end depths and target while using Sketcher'),
            'Pixmap': iconPath('import_svg.svg'),
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return bool(doc and any(doc.getObject(name) for name in
                                ('Marz_Sketch_BodyPockets', 'Marz_Sketch_HeadstockPockets')))

    def Activated(self):
        from freecad.marz.feature.pocket_properties_panel import show_pocket_properties
        show_pocket_properties()
