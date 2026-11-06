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
    def __init__(self, points=(0, 1)):
        self.points = points

    def discretize(self, Number):
        return [FakeVector(x) for x in self.points]


class FakeShape:
    def __init__(self, length=10, closed=True, edges=None):
        self.Edges = edges if edges is not None else [FakeEdge()]
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
        self.PropertiesList = []

    def addProperty(self, kind, name, group, description):
        self.PropertiesList.append(name)
        setattr(self, name, None)

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
            shape = FakeShape(length=self.created_length)
            shape.BoundBox.XMin = self.created_xmin
            shape.BoundBox.XMax = self.created_xmax
            obj = FakeObject(name, shape)
            self.doc.objects[name] = obj
            return obj

        draft.make_sketch = make_sketch
        self.created_length = 10
        self.created_xmin = 0
        self.created_xmax = 10
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

    def test_failed_conversion_leaves_sketch_visible_for_inspection(self):
        self.created_length = 11
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(sketch, self.doc.getObject('Marz_Sketch_BodyContour'))
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertIn('conversion mismatch', sketch.Label)
        self.assertFalse(sketch.SVGConversionValid)
        self.assertIn('total curve length changed', sketch.SVGConversionError)
        self.assertEqual(self.doc.getObject(self.module.GROUP_NAME).children, [sketch])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_failed_sketch_is_not_overwritten_on_second_conversion(self):
        self.created_length = 11
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        sketch.Shape = FakeShape(length=12)
        self.created_length = 10
        self.assertIs(self.module.create_sketch(self.doc, self.source.Name), sketch)
        self.assertEqual(sketch.Shape.Length, 12)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_actual_reported_contour_bounds_mismatch_is_inspectable(self):
        self.created_xmin = 0.219829
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNotNone(sketch)
        self.assertIn('world-space XMin changed by 0.219829 mm', sketch.SVGConversionError)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_actual_reported_headstock_bounds_mismatch_is_inspectable(self):
        self.created_xmax = 10.243284
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNotNone(sketch)
        self.assertIn('world-space XMax changed by 0.243284 mm', sketch.SVGConversionError)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_rejected_sketch_stays_in_document_and_falls_back_to_svg(self):
        self.created_length = 11
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        # The native properties travel with the saved Sketcher object.
        self.assertFalse(sketch.SVGConversionValid)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)
        self.assertIs(self.doc.getObject(sketch.Name), sketch)

    def test_legacy_accepted_sketch_without_status_still_used(self):
        sketch = FakeObject('Marz_Sketch_BodyContour', FakeShape())
        self.doc.objects[sketch.Name] = sketch
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

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

    def test_reversed_edge_parameterization_is_exact_geometry(self):
        original = FakeShape(edges=[FakeEdge((0, 2, 4)), FakeEdge((4, 6, 8))])
        sketch = FakeShape(edges=[FakeEdge((8, 6, 4)), FakeEdge((4, 2, 0))])
        self.assertTrue(self.module._matching_shape(original, sketch))

    def test_edge_order_does_not_change_the_contour(self):
        original = FakeShape(edges=[FakeEdge((0, 2, 4)), FakeEdge((4, 6, 8))])
        sketch = FakeShape(edges=[FakeEdge((4, 6, 8)), FakeEdge((0, 2, 4))])
        self.assertTrue(self.module._matching_shape(original, sketch))

    def test_sketch_compound_of_edges_can_still_be_closed(self):
        original = FakeShape(closed=True)
        converted = FakeShape(closed=False)
        class ReassembledWire:
            def __init__(self, edges):
                self.Edges = edges
            def isClosed(self):
                return True
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(Wire=ReassembledWire)}):
            self.assertTrue(self.module._matching_shape(original, converted))

    def test_local_curve_change_is_rejected_even_with_identical_bounds_and_length(self):
        original = FakeShape(edges=[FakeEdge((0, 1, 2))])
        sketch = FakeShape(edges=[FakeEdge((0, 1.01, 2))])
        self.assertFalse(self.module._matching_shape(original, sketch))
        self.assertIn('curve deviation', self.module._shape_difference(original, sketch))

    def test_missing_edge_rejected_even_with_same_total_length_and_bounds(self):
        original = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        sketch = FakeShape(edges=[FakeEdge((0, 2))])
        self.assertIn('edge count', self.module._shape_difference(original, sketch))

    def test_real_contour_after_draft_reorientation_creates_editable_sketch(self):
        original = FakeShape(edges=[FakeEdge((0, 2, 4)), FakeEdge((4, 6, 8))])
        self.source.Shape = original
        import Draft
        def reoriented_sketch(shape, *, name, **kwargs):
            result = FakeObject(name, FakeShape(edges=[FakeEdge((8, 6, 4)), FakeEdge((4, 2, 0))]))
            self.doc.objects[name] = result
            return result
        with patch.object(Draft, 'make_sketch', reoriented_sketch):
            sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNotNone(sketch)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_existing_document_without_sketch_uses_legacy_wire(self):
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)
        self.assertIsNone(self.module.source_object(self.doc, 'Marz_Headstock_Contour'))


if __name__ == '__main__':
    unittest.main()
