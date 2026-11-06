"""Offline contract tests for Marz editable SVG Sketcher references.

The real Draft-to-Sketch geometry equivalence remains a FreeCAD integration
check; these tests cover source selection, destructive reimport and failure
fallback without inventing FreeCAD's behavior.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / 'freecad/marz/feature/svg_sketch.py'


class FakeVector:
    def __init__(self, x=0):
        self.x = x

    def __sub__(self, other):
        return types.SimpleNamespace(Length=abs(self.x - other.x))


class FakeEdge:
    def discretize(self, Number):
        return [FakeVector(0), FakeVector(1)]


class FakeShape:
    def __init__(self, length=10, closed=True):
        self.Edges = [FakeEdge()]
        self.Length = length
        self.closed = closed
        self.BoundBox = types.SimpleNamespace(
            XMin=0, XMax=10, YMin=0, YMax=0, ZMin=0, ZMax=0)

    def isNull(self):
        return False

    def isClosed(self):
        return self.closed

    def copy(self):
        return self


class FakeObject:
    def __init__(self, name, shape):
        self.Name = name
        self.Label = name
        self.Shape = shape
        self.ViewObject = types.SimpleNamespace(Visibility=True)
        self.recomputes = 0

    def recompute(self):
        self.recomputes += 1


class FakeGroup(FakeObject):
    def __init__(self, name):
        super().__init__(name, FakeShape())
        self.children = []

    def addObject(self, obj):
        self.children.append(obj)


class FakeDoc:
    def __init__(self):
        self.Name = 'Guitar'
        self.objects = {}

    def getObject(self, name):
        return self.objects.get(name)

    def addObject(self, kind, name):
        obj = FakeGroup(name)
        self.objects[name] = obj
        return obj

    def removeObject(self, name):
        del self.objects[name]


class EditableSVGTests(unittest.TestCase):
    def setUp(self):
        self.doc = FakeDoc()
        self.source = FakeObject('Marz_Body_Contour', FakeShape())
        self.doc.objects[self.source.Name] = self.source
        self.app = types.SimpleNamespace(ActiveDocument=self.doc,
            setActiveDocument=lambda name: None,
            Console=types.SimpleNamespace(PrintWarning=lambda s: None,
                                           PrintMessage=lambda s: None))
        fc = types.ModuleType('freecad.marz.extension.fc')
        fc.App = self.app
        part = types.ModuleType('Part')
        part.Vertex = lambda p: types.SimpleNamespace(distToShape=lambda shape: (0, [], []))
        draft = types.ModuleType('Draft')

        def make_sketch(shape, *, name, **kwargs):
            obj = FakeObject(name, FakeShape(length=self.created_length))
            self.doc.objects[name] = obj
            return obj

        draft.make_sketch = make_sketch
        self.created_length = 10
        self.patchers = [patch.dict(sys.modules, {
            'freecad.marz.extension.fc': fc,
            'Part': part,
            'Draft': draft,
        })]
        for p in self.patchers:
            p.start()
        spec = importlib.util.spec_from_file_location('svg_sketch_test_target', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()

    def test_creates_native_sketch_source_without_overwriting_original(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.Name, 'Marz_Sketch_BodyContour')
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertIs(self.doc.getObject(self.source.Name), self.source)
        self.assertFalse(sketch.ViewObject.Visibility)
        self.assertEqual(sketch.recomputes, 1)
        self.assertEqual(len(self.doc.getObject(self.module.GROUP_NAME).children), 1)

    def test_second_conversion_does_not_replace_manual_edits(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        sketch.Shape = FakeShape(length=12)
        self.assertIs(self.module.create_sketch(self.doc, self.source.Name), sketch)
        self.assertEqual(sketch.Shape.Length, 12)

    def test_failed_conversion_keeps_original_wire(self):
        self.created_length = 11
        self.assertIsNone(self.module.create_sketch(self.doc, self.source.Name))
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)
        self.assertIsNone(self.doc.getObject('Marz_Sketch_BodyContour'))

    def test_reimport_removes_only_corresponding_sketch(self):
        self.module.create_sketch(self.doc, self.source.Name)
        unrelated = FakeObject('Marz_Sketch_HeadstockContour', FakeShape())
        self.doc.objects[unrelated.Name] = unrelated
        self.module.remove_sketches(self.doc, [self.source.Name])
        self.assertIsNone(self.doc.getObject('Marz_Sketch_BodyContour'))
        self.assertIs(self.doc.getObject(unrelated.Name), unrelated)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_closure_mismatch_rejected(self):
        self.assertFalse(self.module._matching_shape(FakeShape(closed=True),
                                                     FakeShape(closed=False)))

    def test_existing_document_without_sketch_uses_legacy_wire(self):
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)
        self.assertIsNone(self.module.source_object(self.doc, 'Marz_Headstock_Contour'))


if __name__ == '__main__':
    unittest.main()
