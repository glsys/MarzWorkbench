"""Regressions for the heel cut using the actual generator function.

The FreeCAD call is emulated here, while an optional OpenCascade test can
exercise the real BREP solids saved in a provided FCStd document.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'freecad/marz/model/gordon_neck.py'


class ModelException(Exception):
    pass


class FakeSolid:
    def __init__(self, volume, center_z=0):
        self.Volume = volume
        self.CenterOfMass = SimpleNamespace(z=center_z)
        self.reversed = False

    def reverse(self):
        self.Volume = -self.Volume
        self.reversed = True


class HeelSliceTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.raw_volume = -100
        self.split_count = None
        edges = [
            SimpleNamespace(BoundBox=SimpleNamespace(ZLength=20), CenterOfGravity=SimpleNamespace(x=-500)),
            SimpleNamespace(BoundBox=SimpleNamespace(ZLength=15), CenterOfGravity=SimpleNamespace(x=10)),
            SimpleNamespace(BoundBox=SimpleNamespace(ZLength=0), CenterOfGravity=SimpleNamespace(x=-200)),
            SimpleNamespace(BoundBox=SimpleNamespace(ZLength=0), CenterOfGravity=SimpleNamespace(x=-300)),
        ]
        face = SimpleNamespace(Edges=edges)

        def query(items, where, order_by=None, limit=None):
            result = [item for item in items if where(item)]
            if order_by:
                result.sort(key=order_by)
            return result[:limit] if limit is not None else result

        def slice_shape(solid, tools, mode):
            self.assertEqual(mode, 'CompSolid')
            self.assertEqual(len(tools), 1)
            self.split_count = len(tools)
            return SimpleNamespace(Solids=(
                [FakeSolid(80, center_z=-5), FakeSolid(20, center_z=-40)]
                if solid.Volume > 0 else [FakeSolid(100, center_z=-20)]
            ))

        source = ast.parse(SOURCE.read_text(encoding='utf-8'), filename=str(SOURCE))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'blank_from_gordon')
        namespace = dict(
            geom=SimpleNamespace(query=query, query_one=lambda items, order_by: min(items, key=order_by, default=None)),
            edge_to_closed_face=lambda edge: edge,
            borders_to_closed_face=lambda a, b: (a, b),
            Shell=lambda faces: faces,
            Solid=lambda shell: FakeSolid(self.raw_volume),
            Face=object,
            split_api=SimpleNamespace(slice=slice_shape),
            App=SimpleNamespace(Console=SimpleNamespace(PrintMessage=self.messages.append)),
            ModelException=ModelException,
        )
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.build = lambda: namespace['blank_from_gordon'](face, object())

    def test_inverted_neck_shell_is_reoriented_and_cut(self):
        selected = self.build()
        self.assertEqual(selected.Volume, 80)
        self.assertTrue(self.messages)
        self.assertEqual(self.split_count, 1)

    def test_correctly_oriented_neck_shell_is_not_reversed(self):
        self.raw_volume = 100
        self.assertEqual(self.build().Volume, 80)
        self.assertFalse(self.messages)

    def test_nonintersecting_plane_is_reported_instead_of_accepting_blank(self):
        self.raw_volume = 0
        with self.assertRaisesRegex(ModelException, 'did not divide'):
            self.build()


if __name__ == '__main__':
    unittest.main()
