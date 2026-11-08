"""Offline contracts for the persisted fretboard construction pipeline."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / 'freecad/marz/feature/fretboard_parametric.py'


class FakeVector:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


class FakeShape:
    def __init__(self, name='shape', valid=True):
        self.name = name
        self.valid = valid
        self.Solids = [self] if valid else []
        self.cuts = []
        self.translations = []

    def isNull(self):
        return not self.valid

    def isValid(self):
        return self.valid

    def copy(self):
        return FakeShape(self.name, self.valid)

    def cut(self, tools):
        if not isinstance(tools, tuple):
            tools = (tools,)
        result = FakeShape(self.name + '-cut')
        result.cuts = self.cuts + [tuple(getattr(t, 'name', repr(t)) for t in tools)]
        return result

    def removeSplitter(self):
        return self

    def translate(self, vector):
        self.translations.append((vector.x, vector.y, vector.z))

    def extrude(self, vector):
        result = FakeShape(self.name + '-extrude')
        result.extrusion = (vector.x, vector.y, vector.z)
        return result


class FakeFeature:
    def __init__(self, name, shape=None):
        self.Name = name
        self.Label = name
        self.Shape = shape or FakeShape(name)
        self.BuildStatus = 'OK'


class FakeObject(FakeFeature):
    def __init__(self, name):
        super().__init__(name, FakeShape(name))
        self.PropertiesList = []
        self.TypeId = 'Part::FeaturePython'
        self.ViewObject = types.SimpleNamespace(Proxy=None, Visibility=True)
        self.Proxy = None

    def addProperty(self, kind, name, group):
        self.PropertiesList.append(name)
        if kind == 'App::PropertyLength':
            setattr(self, name, types.SimpleNamespace(Value=0.0))
        else:
            setattr(self, name, None)


class FakeGroup(FakeObject):
    def __init__(self, name):
        super().__init__(name)
        self.TypeId = 'App::DocumentObjectGroup'
        self.Group = []
    def addObject(self, obj):
        if obj not in self.Group:
            self.Group.append(obj)
    def removeObject(self, obj):
        if obj in self.Group:
            self.Group.remove(obj)


class FakeDoc:
    def __init__(self):
        self.objects = {}
    @property
    def Objects(self):
        return list(self.objects.values())
    def getObject(self, name):
        return self.objects.get(name)
    def addObject(self, kind, name):
        if kind == 'App::DocumentObjectGroup':
            obj = FakeGroup(name)
        else:
            obj = FakeObject(name)
            obj.TypeId = kind
        def recompute():
            if obj.Proxy is not None and hasattr(obj.Proxy, 'execute'):
                obj.Proxy.execute(obj)
        obj.recompute = recompute
        self.objects[name] = obj
        return obj
    def removeObject(self, name):
        obj = self.objects.pop(name, None)
        if obj is not None:
            for owner in self.Objects:
                if getattr(owner, 'TypeId', '') == 'App::DocumentObjectGroup' and obj in owner.Group:
                    owner.removeObject(obj)


class FakeWire:
    def __init__(self, edges):
        self.edges = edges
        self.Placement = None
    def isClosed(self):
        return True


class FakeFace:
    def __init__(self, wire):
        self.wire = wire
    def extrude(self, vector):
        return FakeShape('inlay').extrude(vector)


class FretboardParametricTests(unittest.TestCase):
    def setUp(self):
        fc = types.ModuleType('freecad.marz.extension.fc')
        fc.App = types.SimpleNamespace()
        fc.Vector = FakeVector
        paths = types.ModuleType('freecad.marz.extension.paths')
        paths.iconPath = lambda name: name
        docmod = types.ModuleType('freecad.marz.feature.document')
        docmod.FretboardPart = types.SimpleNamespace(
            name='Marz_Fretboard', label='Fretboard', style=None)
        logging = types.ModuleType('freecad.marz.feature.logging')
        logging.MarzLogger = types.SimpleNamespace(warn=lambda *args, **kwargs: None)
        part = types.ModuleType('Part')
        part.Wire = FakeWire
        part.Face = FakeFace
        part.Shape = lambda: FakeShape('empty', valid=False)
        part.makeCompound = lambda shapes: FakeShape('compound')
        self.patchers = [patch.dict(sys.modules, {
            'freecad.marz.extension.fc': fc,
            'freecad.marz.extension.paths': paths,
            'freecad.marz.feature.document': docmod,
            'freecad.marz.feature.logging': logging,
            'Part': part,
        })]
        for p in self.patchers:
            p.start()
        spec = importlib.util.spec_from_file_location('fretboard_parametric_test_target', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()

    def test_finished_result_cuts_slots_nut_then_inlays(self):
        obj = FakeObject('Marz_Fretboard')
        proxy = self.module.FretboardResult(obj)
        obj.Blank = FakeFeature('blank', FakeShape('blank'))
        obj.NutSlot = FakeFeature('nut', FakeShape('nut'))
        obj.FretSlots = [FakeFeature('slot3', FakeShape('slot3')),
                         FakeFeature('slot4', FakeShape('slot4'))]
        obj.InlayCutters = [FakeFeature('inlay3', FakeShape('inlay3'))]
        proxy.execute(obj)
        self.assertEqual(obj.BuildStatus, 'OK')
        self.assertTrue(obj.Shape.isValid())
        # First operation contains both fret slots and the nut cutter.
        self.assertEqual(obj.Shape.cuts[0], ('slot3', 'slot4', 'nut'))
        # Second operation is the compound of inlay cutters.
        self.assertEqual(obj.Shape.cuts[1], ('compound',))

    def test_inlay_cutter_rebuilds_from_editable_sketch_metadata(self):
        class Curve:
            def toShape(self):
                return object()
        sketch = types.SimpleNamespace(
            SVGConversionValid=True,
            SVGElementMap=json.dumps({'profiles': [{'wires': [[0, 1, 2]]}]}),
            Geometry=[Curve(), Curve(), Curve()],
            Placement=object())
        obj = FakeObject('Marz_Fretboard_InlayCutter_12')
        proxy = self.module.InlayCutter(obj)
        obj.Source = sketch
        obj.Position = FakeVector(10, 20, 8)
        obj.CutLength.Value = 2.0
        obj.Fret = 12
        proxy.execute(obj)
        self.assertEqual(obj.BuildStatus, 'OK')
        self.assertTrue(obj.Shape.isValid())

    def test_regenerate_exposes_blank_nut_individual_slots_and_linked_result(self):
        doc = FakeDoc()
        legacy = types.ModuleType('freecad.marz.feature.fretboard')
        legacy.base = lambda inst, fbd: FakeShape('blank')
        legacy.nutSlot = lambda inst, fbd: FakeShape('nut')
        legacy.fretsCut = lambda inst, fbd: [FakeShape('slot1'), FakeShape('slot2')]
        legacy.fretPos = lambda fret, line, height: FakeVector(fret, 0, height + 1)
        svg = types.ModuleType('freecad.marz.feature.svg_sketch')
        svg.FRET_INLAY_SKETCH_PREFIX = 'Marz_Sketch_FretInlay_'
        svg.create_fret_inlay_sketches = lambda doc: []
        inst = types.SimpleNamespace(fretboard=types.SimpleNamespace(
            isZeroFret=False, thickness=7.0, inlayDepth=1.0))
        fbd = types.SimpleNamespace(frets=[object(), object(), object()],
                                    scaleFrame=types.SimpleNamespace(midLine=object()))
        with patch.dict(sys.modules, {
                'freecad.marz.feature.fretboard': legacy,
                'freecad.marz.feature.svg_sketch': svg}):
            result = self.module.regenerate(inst, fbd, doc)
        self.assertIsNotNone(doc.getObject('Marz_Fretboard_Blank'))
        self.assertIsNotNone(doc.getObject('Marz_Fretboard_NutSlot'))
        self.assertIsNotNone(doc.getObject('Marz_Fretboard_FretSlot_1'))
        self.assertIsNotNone(doc.getObject('Marz_Fretboard_FretSlot_2'))
        self.assertIsNone(doc.getObject('Marz_Fretboard_FretSlot_0'))
        self.assertEqual([obj.Name for obj in result.FretSlots],
                         ['Marz_Fretboard_FretSlot_1', 'Marz_Fretboard_FretSlot_2'])
        self.assertEqual(result.BuildStatus, 'OK')
        self.assertIn(result, doc.getObject('Marz_Group_Fretboard').Group)


    def test_existing_construction_visibility_survives_regeneration(self):
        doc = FakeDoc()
        group = doc.addObject('App::DocumentObjectGroup', 'Construction')
        existing = doc.addObject('Part::Feature', 'Marz_Fretboard_Blank')
        existing.ViewObject.Visibility = True
        self.module._feature(doc, existing.Name, 'Fretboard blank',
                             FakeShape('replacement'), group, False)
        self.assertTrue(existing.ViewObject.Visibility)

    def test_result_migration_keeps_previous_shape_until_linked_recompute_succeeds(self):
        doc = FakeDoc()
        root = doc.addObject('App::DocumentObjectGroup', 'Marz_Group_Fretboard')
        old = doc.addObject('Part::FeatureExt', 'Marz_Fretboard')
        old.Shape = FakeShape('legacy-fretboard')
        result = self.module._result(doc, root)
        self.assertEqual(result.TypeId, 'Part::FeaturePython')
        self.assertEqual(result.Shape.name, 'legacy-fretboard')
        self.assertIsInstance(result.Proxy, self.module.FretboardResult)

    def test_invalid_inlay_edit_retains_previous_cutter_shape(self):
        class OpenWire(FakeWire):
            def isClosed(self):
                return False
        part = sys.modules['Part']
        previous = FakeShape('previous')
        obj = FakeObject('Marz_Fretboard_InlayCutter_5')
        obj.Shape = previous
        proxy = self.module.InlayCutter(obj)
        sketch = types.SimpleNamespace(
            SVGConversionValid=True,
            SVGElementMap=json.dumps({'profiles': [{'wires': [[0]]}]}),
            Geometry=[types.SimpleNamespace(toShape=lambda: object())],
            Placement=object())
        obj.Source = sketch
        obj.Position = FakeVector()
        obj.CutLength.Value = 2.0
        with patch.object(part, 'Wire', OpenWire):
            proxy.execute(obj)
        self.assertTrue(obj.BuildStatus.startswith('ERROR:'))
        self.assertIs(obj.Shape, previous)


if __name__ == '__main__':
    unittest.main()
