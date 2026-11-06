"""Isolated tests for the FreeCAD heel-plane migration without FreeCAD installed.

Extract the real _heel_plane function from its source so the regression tests
exercise the production logic, not a reimplementation of it.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'freecad/marz/feature/neck_parametric.py'


class Quantity:
    """A FreeCAD-style length quantity, disallowing subtraction of bare floats."""

    def __init__(self, value):
        self.Value = float(value)

    def __sub__(self, other):
        if not isinstance(other, Quantity):
            raise ArithmeticError('Quantity::operator -(): Unit mismatch in minus operation')
        return Quantity(self.Value - other.Value)


class Vector:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    @property
    def Length(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5


class Placement:
    def __init__(self, base, rotation=None):
        self.Base = base


class Rotation:
    pass


class FakePlane:
    def __init__(self, length, width, base=Vector()):
        self._length, self._width = Quantity(length), Quantity(width)
        self.Placement = Placement(base)
        self.PropertiesList = []
        self.ViewObject = SimpleNamespace(Visibility=True)

    @property
    def Length(self):
        return self._length

    @Length.setter
    def Length(self, value):
        self._length = Quantity(value)

    @property
    def Width(self):
        return self._width

    @Width.setter
    def Width(self, value):
        self._width = Quantity(value)


class FakeDocument:
    def __init__(self, plane=None, default_length=10, default_width=10):
        self.plane = plane
        self.default_length = default_length
        self.default_width = default_width

    def getObject(self, name):
        return self.plane

    def addObject(self, type_id, name):
        assert type_id == 'Part::Plane'
        self.plane = FakePlane(self.default_length, self.default_width)
        return self.plane


class FakeGroup:
    def __init__(self):
        self.Group = []

    def addObject(self, obj):
        self.Group.append(obj)


def _property(obj, kind, name, group, description):
    if name not in obj.PropertiesList:
        obj.PropertiesList.append(name)
        setattr(obj, name, False)


class HeelPlaneTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse(SOURCE.read_text(encoding='utf-8'), filename=str(SOURCE))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_heel_plane')
        bounds = SimpleNamespace(XMin=-520.65, YMin=-225.29, ZMin=-22.0,
                                 XLength=450.58, YLength=450.58)
        geometry = SimpleNamespace(heel_cutting_plane=lambda edge, inst: SimpleNamespace(BoundBox=bounds))
        app = SimpleNamespace(Console=SimpleNamespace(PrintMessage=lambda value: None))
        namespace = dict(PREFIX='Marz_Neck_', Vector=Vector, Placement=Placement,
                         Rotation=Rotation, geometry=geometry, _property=_property, App=app)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.make_plane = namespace['_heel_plane']
        self.bounds = bounds

    def test_new_plane_uses_original_world_coordinates(self):
        document = FakeDocument()
        group = FakeGroup()
        obj = self.make_plane(document, None, None, group)
        self.assertEqual((obj.Placement.Base.x, obj.Placement.Base.y, obj.Placement.Base.z),
                         (-520.65, -225.29, -22.0))
        self.assertEqual((obj.Length.Value, obj.Width.Value), (450.58, 450.58))
        self.assertTrue(obj.MarzPlacementInitialized)
        self.assertFalse(obj.ViewObject.Visibility)
        self.assertEqual(group.Group, [obj])

    def test_old_origin_plane_with_length_quantities_migrates(self):
        plane = FakePlane(self.bounds.XLength, self.bounds.YLength)
        document = FakeDocument(plane)
        self.make_plane(document, None, None, FakeGroup())
        self.assertEqual(plane.Placement.Base.z, -22.0)
        self.assertTrue(plane.MarzPlacementInitialized)

    def test_user_moved_plane_is_not_reset(self):
        plane = FakePlane(self.bounds.XLength, self.bounds.YLength, Vector(10, 20, 30))
        self.make_plane(FakeDocument(plane), None, None, FakeGroup())
        self.assertEqual((plane.Placement.Base.x, plane.Placement.Base.y, plane.Placement.Base.z),
                         (10, 20, 30))
        self.assertTrue(plane.MarzPlacementInitialized)

    def test_user_resized_plane_at_origin_is_not_reset(self):
        plane = FakePlane(200, 220)
        self.make_plane(FakeDocument(plane), None, None, FakeGroup())
        self.assertEqual((plane.Length.Value, plane.Width.Value), (200, 220))
        self.assertEqual(plane.Placement.Base.Length, 0)
        self.assertTrue(plane.MarzPlacementInitialized)

    def test_explicit_reset_overwrites_user_adjustments(self):
        plane = FakePlane(200, 220, Vector(10, 20, 30))
        self.make_plane(FakeDocument(plane), None, None, FakeGroup(), reset=True)
        self.assertEqual((plane.Length.Value, plane.Width.Value), (450.58, 450.58))
        self.assertEqual(plane.Placement.Base.z, -22.0)

    def test_normal_recompute_preserves_initialized_plane(self):
        plane = FakePlane(200, 220, Vector(10, 20, 30))
        plane.MarzPlacementInitialized = True
        plane.PropertiesList.append('MarzPlacementInitialized')
        self.make_plane(FakeDocument(plane), None, None, FakeGroup())
        self.assertEqual((plane.Length.Value, plane.Width.Value), (200, 220))
        self.assertEqual(plane.Placement.Base.z, 30)


if __name__ == '__main__':
    unittest.main()
