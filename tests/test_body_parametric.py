"""Offline checks for native linked body features; actual FreeCAD GUI remains separate."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'freecad/marz/feature/body_parametric.py'


class Vector:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    def __add__(self, rhs):
        return Vector(self.x + rhs.x, self.y + rhs.y, self.z + rhs.z)

    @property
    def Length(self):
        return (self.x*self.x + self.y*self.y + self.z*self.z)**0.5


class Placement:
    def __init__(self, base=None, rotation=None):
        self.Base = base or Vector()
        self.Rotation = rotation or object()

    def multiply(self, other):
        # Translation-only fake. The production FreeCAD Placement also
        # composes rotations; this regression focuses on SVG source offsets.
        return Placement(self.Base + other.Base, self.Rotation)


class Quantity:
    def __init__(self, value):
        self.Value = value


class Shape:
    def __init__(self, volume=0, *, null=False, solids=None):
        self.Volume = volume
        self._null = null
        self.Solids = [self] if solids is None and not null else (solids or [])
        self.Placement = Placement()
        self.cut_calls = []

    def isNull(self):
        return self._null

    def isValid(self):
        return not self._null

    def copy(self):
        cloned = Shape(self.Volume, null=self._null, solids=[self] if self.Solids else [])
        cloned.Placement = self.Placement
        return cloned

    def cut(self, other):
        result = Shape(self.Volume - other.Volume)
        self.cut_calls.append(other)
        return result

    def removeSplitter(self):
        return self

    def translate(self, offset):
        return None


class View:
    def __init__(self):
        self.Visibility = True


class Obj:
    def __init__(self, doc, kind, name):
        self._doc = doc
        self.Name = self.Label = name
        self.TypeId = kind
        self.ViewObject = View()
        self.Placement = Placement()
        self.PropertiesList = []
        self.Shape = Shape(null=True)
        self.Group = [] if kind == 'App::DocumentObjectGroup' else None
        self.Proxy = None
        self.Dir = Vector(0, 0, 1)
        self.LengthFwd = Quantity(0)
        self.LengthRev = Quantity(0)

    def __setattr__(self, name, value):
        if name in ('LengthFwd', 'LengthRev') and isinstance(value, (int, float)):
            value = Quantity(value)
        object.__setattr__(self, name, value)

    def addObject(self, obj):
        if obj not in self.Group:
            self.Group.append(obj)

    def removeObject(self, obj):
        self.Group.remove(obj)

    def addProperty(self, kind, name, *args):
        self.PropertiesList.append(name)
        setattr(self, name, None)

    def recompute(self):
        if self.TypeId == 'Part::Extrusion':
            self.Shape = Shape(self.Base.LinkedObject.Shape.Volume * self.LengthFwd.Value)
            # A native extrusion inherits the source shape's TopLoc_Location.
            self.Shape.Placement = self.Base.LinkedObject.Shape.Placement
        elif self.TypeId == 'Part::FeaturePython' and self.Proxy:
            self.Proxy.execute(self)


class Doc:
    def __init__(self):
        self.objects = {}

    def addObject(self, kind, name):
        obj = Obj(self, kind, name)
        self.objects[name] = obj
        return obj

    def getObject(self, name):
        return self.objects.get(name)

    def removeObject(self, name):
        del self.objects[name]

    @property
    def Objects(self):
        return list(self.objects.values())

    def recompute(self):
        for obj in self.Objects:
            if obj.TypeId == 'Part::Extrusion':
                obj.recompute()
        for obj in self.Objects:
            if obj.TypeId == 'Part::FeaturePython':
                obj.recompute()


class Definition:
    def __init__(self, name):
        self.name = name
        self.label = name
        self.style = types.SimpleNamespace(apply=lambda obj: None)

    def get(self, *, doc):
        return doc.getObject(self.name)

    def remove(self, *, doc):
        if doc.getObject(self.name):
            doc.removeObject(self.name)


class BodyParametricTests(unittest.TestCase):
    def setUp(self):
        self.doc = Doc()
        contour = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyContour')
        contour.Shape = Shape(100)  # test extrusion source area surrogate
        contour.SVGConversionValid = True
        imports = self.doc.addObject('App::DocumentObjectGroup', 'Marz_Group_Imports')
        imports.addObject(contour)
        self.contour = contour
        self.log = []
        p = types.ModuleType('Part')
        p.makeCompound = lambda shapes: Shape(sum(x.Volume for x in shapes), solids=shapes)
        p.Shape = lambda: Shape(null=True)
        self.part = p
        fc = types.ModuleType('freecad.marz.extension.fc')
        fc.App = types.SimpleNamespace(ActiveDocument=self.doc)
        fc.Vector = Vector
        fc.Placement = Placement
        document = types.ModuleType('freecad.marz.feature.document')
        for name in ('BodyContour', 'BodyPockets', 'BodyTopPockets', 'BodyBackPockets',
                     'BodyErgoCutsTop', 'BodyErgoCutsBack', 'BodyTopPart', 'BodyBackPart'):
            setattr(document, name, Definition('Marz_' + name))
        document.BodyTopPart = Definition('Marz_Body_Top')
        document.BodyBackPart = Definition('Marz_Body_Back')
        log = types.ModuleType('freecad.marz.feature.logging')
        log.MarzLogger = types.SimpleNamespace(warn=self.log.append)
        svg = types.ModuleType('freecad.marz.feature.svg_sketch')
        svg.source_object = lambda doc, name: doc.getObject('Marz_Sketch_BridgeRef')
        neck = types.ModuleType('freecad.marz.feature.neck')
        neck.make_neck_pocket = lambda *args: Shape(2)
        modules = {
            'Part': p,
            'freecad': types.ModuleType('freecad'),
            'freecad.marz': types.ModuleType('freecad.marz'),
            'freecad.marz.extension': types.ModuleType('freecad.marz.extension'),
            'freecad.marz.extension.fc': fc,
            'freecad.marz.feature': types.ModuleType('freecad.marz.feature'),
            'freecad.marz.feature.document': document,
            'freecad.marz.feature.logging': log,
            'freecad.marz.feature.svg_sketch': svg,
            'freecad.marz.feature.neck': neck,
        }
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        spec = importlib.util.spec_from_file_location('body_parametric_test_target', MODULE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.bodyd = types.SimpleNamespace(topThickness=4., backThickness=10.,
               neckPocketCarve=False, neckd=types.SimpleNamespace(fbd=object()),
               placements=lambda bridge: (Placement(Vector(5, 0, 5)),
                                          Placement(Vector(5, 0, -5))))

    def tearDown(self):
        self.patcher.stop()

    def test_one_shared_sketch_two_native_extrusions_and_linked_results(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top_Extrusion')
        back = self.doc.getObject('Marz_Body_Back_Extrusion')
        self.assertEqual(top.TypeId, 'Part::Extrusion')
        self.assertEqual(back.TypeId, 'Part::Extrusion')
        self.assertIs(top.Base.LinkedObject, self.contour)
        self.assertIs(back.Base.LinkedObject, self.contour)
        self.assertEqual(top.LengthFwd.Value, 4)
        self.assertEqual(back.LengthFwd.Value, 10)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 400)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 1000)
        body_group = self.doc.getObject('Marz_Group_Body')
        self.assertIn(self.contour, body_group.Group)
        self.assertNotIn(self.contour, self.doc.getObject('Marz_Group_Imports').Group)

    def test_body_world_placement_composes_imported_svg_location(self):
        # Real user FCStd: Body Contour BREP carries (-289.833, +106.255)
        # in its shape Location. The guitar placement adds about -403 mm X.
        # Replacing Shape.Placement instead of composing it put the new
        # generated body roughly 290 mm too close to the headstock.
        self.contour.Shape.Placement = Placement(Vector(-289.8327438, 106.2546525, 0))
        self.bodyd.placements = lambda bridge: (
            Placement(Vector(-403.0859391, 0, -2)),
            Placement(Vector(-403.0859391, 0, -7)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        back = self.doc.getObject('Marz_Body_Back')
        self.assertAlmostEqual(top.Shape.Placement.Base.x, -692.9186829, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.x, -692.9186829, places=5)
        self.assertAlmostEqual(top.Shape.Placement.Base.y, 106.2546525, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.z, -7, places=5)
        # Source and native extrusions stay at local/import coordinates.
        self.assertAlmostEqual(self.contour.Shape.Placement.Base.x, -289.8327438)
        self.assertAlmostEqual(
            self.doc.getObject('Marz_Body_Top_Extrusion').Shape.Placement.Base.x,
            -289.8327438)
        self.doc.recompute()
        self.assertAlmostEqual(top.Shape.Placement.Base.x, -692.9186829, places=5)
        # A recompute must not incrementally apply the guitar offset again.
        self.assertAlmostEqual(back.Shape.Placement.Base.x, -692.9186829, places=5)

    def test_identity_source_still_uses_only_guitar_placement(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        self.assertEqual(top.Shape.Placement.Base.x, 5)
        self.assertEqual(top.Shape.Placement.Base.z, 5)

    def test_normal_recompute_updates_both_halves_without_regeneration(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.contour.Shape = Shape(200)
        self.doc.recompute()
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 800)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 2000)

    def test_regenerating_top_retains_manually_edited_back_extrusion(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        back = self.doc.getObject('Marz_Body_Back_Extrusion')
        back.LengthFwd = 15
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='top')
        self.assertIs(back, self.doc.getObject('Marz_Body_Back_Extrusion'))
        self.assertEqual(back.LengthFwd.Value, 15)
        self.assertIs(self.contour, self.doc.getObject('Marz_Sketch_BodyContour'))

    def test_existing_static_output_is_migrated_only_on_regeneration(self):
        old = self.doc.addObject('Part::FeatureExt', 'Marz_Body_Top')
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='back')
        self.assertIs(old, self.doc.getObject('Marz_Body_Top'))
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='top')
        self.assertNotEqual(self.doc.getObject('Marz_Body_Top').TypeId, old.TypeId)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').TypeId, 'Part::FeaturePython')

    def test_editing_pocket_metadata_recomputes_only_matching_half(self):
        import json
        sketch = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyPockets')
        sketch.SVGConversionValid = True
        sketch.SVGElementMap = json.dumps({'elements': [
            {'id': 'ht1_0_200', 'indices': [0], 'start': 0,
             'depth': 2, 'target': 't'}]})
        sketch.Geometry = [types.SimpleNamespace(toShape=lambda: object())]
        self.part.Wire = lambda edges: types.SimpleNamespace(
            Placement=Placement(), isClosed=lambda: True)
        self.part.Face = lambda wire: types.SimpleNamespace(
            extrude=lambda direction: Shape(abs(direction.z)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 398)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 1000)
        sketch.SVGElementMap = json.dumps({'elements': [
            {'id': 'ht1_0_200', 'indices': [0], 'start': 0,
             'depth': 6, 'target': 't'}]})
        self.doc.recompute()
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 394)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 1000)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').BuildStatus, 'OK')

    def test_unsupported_pocket_keeps_prior_cutters_and_reports_error(self):
        import json
        sketch = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyPockets')
        sketch.SVGConversionValid = True
        sketch.SVGElementMap = json.dumps({'elements': [
            {'id': 'h1_0_200', 'indices': [0], 'start': 0,
             'depth': 2, 'target': ''}]})
        sketch.Geometry = [types.SimpleNamespace(toShape=lambda: object())]
        self.part.Wire = lambda edges: types.SimpleNamespace(
            Placement=Placement(), isClosed=lambda: True)
        self.part.Face = lambda wire: types.SimpleNamespace(
            extrude=lambda direction: Shape(abs(direction.z)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        both = self.doc.getObject('Marz_Body_SketchCutters_Both')
        self.assertEqual(both.Shape.Volume, 2)
        sketch.SVGElementMap = json.dumps({'elements': [
            {'id': 'h1_0_200', 'indices': [0], 'start': 0,
             'depth': -3, 'target': ''}]})
        self.doc.recompute()
        self.assertEqual(both.Shape.Volume, 2)
        self.assertIn('ERROR', both.BuildStatus)
        self.assertIn('INCOMPLETE', self.doc.getObject('Marz_Body_Top').BuildStatus)

    def test_failed_boolean_is_reported_as_incomplete(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        result = self.doc.getObject('Marz_Body_Top')
        result.CarveNeckPocket = True
        result.recompute()
        self.assertEqual(result.BuildStatus[:10], 'INCOMPLETE')
        self.assertEqual(result.Shape.Volume, 400)


if __name__ == '__main__':
    unittest.main()
