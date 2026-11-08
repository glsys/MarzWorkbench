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
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z

    def __sub__(self, other):
        return FakeVector(self.x - other.x, self.y - other.y, self.z - other.z)

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def __mul__(self, scalar):
        return FakeVector(self.x * scalar, self.y * scalar, self.z * scalar)

    def __neg__(self):
        return FakeVector(-self.x, -self.y, -self.z)

    def __truediv__(self, scalar):
        return self * (1.0 / scalar)

    def __add__(self, other):
        return FakeVector(self.x + other.x, self.y + other.y, self.z + other.z)

    @property
    def Length(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5


class FakeBoundBox:
    XMin, XMax, YMin, YMax, ZMin, ZMax = 0, 10, 0, 0, 0, 0

    def __init__(self):
        self.XMin = 0
        self.XMax = 10
        self.YMin = self.YMax = self.ZMin = self.ZMax = 0

    @property
    def Center(self):
        return FakeVector((self.XMin + self.XMax) / 2,
                          (self.YMin + self.YMax) / 2,
                          (self.ZMin + self.ZMax) / 2)


class FakeEdge:
    FirstParameter = 0
    LastParameter = 1

    def __init__(self, points=(0, 1)):
        self.points = points

    def valueAt(self, parameter):
        return FakeVector(self.points[0 if parameter == 0 else -1])

    def discretize(self, Number):
        return [FakeVector(x) for x in self.points]


class BezierCurve:
    Degree = 3

    def __init__(self, poles):
        self.poles = poles

    def getPoles(self):
        return list(self.poles)

    def isRational(self):
        return False


class BSplineCurve:
    Degree = 1

    def __init__(self, first, last):
        self.poles = [first, last]

    def getPoles(self):
        return list(self.poles)


class FakeBuiltSpline:
    def getPoles(self):
        return list(self.poles)

    def buildFromPolesMultsKnots(self, poles, mults, knots, periodic, degree):
        self.poles = list(poles)
        self.mults = list(mults)
        self.knots = list(knots)
        self.periodic = periodic
        self.degree = degree


class FakeShape:
    def __init__(self, length=10, closed=True, edges=None):
        self.Edges = edges if edges is not None else [FakeEdge()]
        self.Length = length
        self.closed = closed
        self.BoundBox = FakeBoundBox()

    def isNull(self):
        return False

    def isClosed(self):
        return self.closed

    def copy(self):
        result = FakeShape(self.Length, self.closed, list(self.Edges))
        result.BoundBox.XMin, result.BoundBox.XMax = self.BoundBox.XMin, self.BoundBox.XMax
        return result


class FakeCurve:
    def __init__(self, points):
        self.StartPoint = FakeVector(points[0])
        self.EndPoint = FakeVector(points[-1])


class FakePlacement:
    def __init__(self):
        self.Base = FakeVector(0)

    def multVec(self, point):
        return point + self.Base



class FakeObject:
    def __init__(self, name, shape):
        self.Name = name
        self.Label = name
        self.Shape = shape
        self.ViewObject = types.SimpleNamespace(Visibility=True,
            PropertiesList=['LineColor', 'LineWidth'], LineColor=None, LineWidth=None)
        self.GeometryCount = len(shape.Edges)
        self.Placement = FakePlacement()
        self._recompute_base_x = 0
        self.recomputes = 0
        self.PropertiesList = []
        self.Constraints = []
        self.Geometry = [FakeCurve(edge.points) for edge in shape.Edges]
        self.RedundantConstraints = []
        self.ConflictingConstraints = []
        self.initial_constraints = None
        self.exposed_splines = []

    def addGeometry(self, geometry, construction):
        items = geometry if isinstance(geometry, list) else [geometry]
        result = list(range(self.GeometryCount, self.GeometryCount + len(items)))
        self.Geometry.extend(items)
        self.GeometryCount += len(items)
        return result if isinstance(geometry, list) else result[0]

    def exposeInternalGeometry(self, index):
        self.exposed_splines.append(index)
        # FreeCAD inserts construction geometry for poles and knots. These
        # new indices must never be included in SVGElementMap.
        self.GeometryCount += 5
        self.Constraints.append(('InternalAlignment', index))
        return 5

    def addConstraint(self, constraints):
        self.Constraints.extend(constraints if isinstance(constraints, list) else [constraints])

    def addProperty(self, kind, name, group, description):
        self.PropertiesList.append(name)
        setattr(self, name, None)

    def recompute(self):
        self.recomputes += 1
        if self.initial_constraints is None:
            self.initial_constraints = list(self.Constraints)
        shift = self.Placement.Base.x - self._recompute_base_x
        self.Shape.BoundBox.XMin += shift
        self.Shape.BoundBox.XMax += shift
        self._recompute_base_x = self.Placement.Base.x


class FakeGroup(FakeObject):
    def __init__(self, name):
        super().__init__(name, FakeShape())
        self.children = []
        self.Group = self.children
        self.TypeId = 'App::DocumentObjectGroup'

    def addObject(self, obj):
        if obj not in self.children:
            self.children.append(obj)

    def removeObject(self, obj):
        self.children.remove(obj)


class FakeDoc:
    def __init__(self):
        self.Name = 'Guitar'
        self.objects = {}
        self.sketch_factory = None

    def getObject(self, name):
        return self.objects.get(name)

    def addObject(self, kind, name):
        obj = (self.sketch_factory(name) if kind == 'Sketcher::SketchObject'
               else FakeGroup(name))
        self.objects[name] = obj
        return obj

    def removeObject(self, name):
        del self.objects[name]

    @property
    def Objects(self):
        return list(self.objects.values())


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
        sketcher = types.ModuleType('Sketcher')
        sketcher.Constraint = lambda *args: tuple(args)
        self.draft_calls = []

        def make_sketch(shape, *, name, **kwargs):
            self.draft_calls.append(kwargs)
            output = FakeShape(length=self.created_length, closed=shape.closed,
                               edges=list(shape.Edges))
            output.BoundBox.XMin = self.created_xmin
            output.BoundBox.XMax = self.created_xmax
            obj = FakeObject(name, output)
            self.doc.objects[name] = obj
            return obj

        def sketch_factory(name):
            output = FakeShape(length=self.created_length,
                               closed=self.source.Shape.closed,
                               edges=list(self.source.Shape.Edges))
            output.BoundBox.XMin = self.created_xmin
            output.BoundBox.XMax = self.created_xmax
            obj = FakeObject(name, output)
            obj.Geometry = []
            obj.GeometryCount = 0
            return obj

        self.doc.sketch_factory = sketch_factory
        draft.make_sketch = make_sketch
        self.created_length = 10
        self.created_xmin = 0
        self.created_xmax = 10
        self.patchers = [patch.dict(sys.modules, {
            'freecad.marz.extension.fc': fc,
            'Part': part,
            'Draft': draft,
            'Sketcher': sketcher,
        })]
        for p in self.patchers:
            p.start()
        spec = importlib.util.spec_from_file_location('svg_sketch_test_target', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_comb_default_is_initialized_once_and_respects_user_override(self):
        class Preferences:
            def __init__(self):
                self.values = {}
            def GetBool(self, key, default):
                return self.values.get(key, default)
            def SetBool(self, key, value):
                self.values[key] = value
        groups = {}
        self.app.ParamGet = lambda key: groups.setdefault(key, Preferences())
        self.module._configure_sketcher_display_defaults()
        sketcher = groups['User parameter:BaseApp/Preferences/Mod/Sketcher/General']
        self.assertFalse(sketcher.values['BSplineCombVisible'])
        sketcher.SetBool('BSplineCombVisible', True)
        self.module._configure_sketcher_display_defaults()
        self.assertTrue(sketcher.values['BSplineCombVisible'])

    def test_pocket_sketch_retains_ids_depths_targets_and_indices(self):
        part = sys.modules['Part']
        class Wire:
            def __init__(self, edges):
                self.edges = edges
            def translate(self, vec):
                pass
        pockets = [types.SimpleNamespace(name='h12_0_4000', edges=[FakeEdge()],
                                         start=0.0, depth=40.0, target=''),
                   types.SimpleNamespace(name='ht9_25_1200', edges=[FakeEdge()],
                                         start=0.25, depth=12.0, target='t')]
        with patch.object(part, 'Wire', Wire, create=True), patch.object(
                self.module, '_pocket_geometry', return_value=[FakeCurve((0, 1))]):
            sketch = self.module.create_pocket_sketch(self.doc, pockets, 'body', FakeVector())
        self.assertIsNotNone(sketch)
        self.assertEqual(sketch.Name, 'Marz_Sketch_BodyPockets')
        self.assertEqual(sketch.SVGSourceDocument, 'body')
        data = __import__('json').loads(sketch.SVGElementMap)['elements']
        self.assertEqual(data, [
            {'id': 'h12_0_4000', 'indices': [0], 'start': 0.0, 'depth': 40.0, 'target': ''},
            {'id': 'ht9_25_1200', 'indices': [1], 'start': 0.25, 'depth': 12.0, 'target': 't'},
        ])
        self.assertFalse(sketch.ViewObject.Visibility)

    def test_pocket_refresh_rebuilds_cutters_using_stored_svg_metadata(self):
        doc = self.doc
        pocket_sketch = FakeObject('Marz_Sketch_BodyPockets', FakeShape())
        pocket_sketch.SVGConversionValid = True
        pocket_sketch.SVGElementMap = __import__('json').dumps({'elements': [
            {'id': 'ht10_50_200', 'indices': [0], 'start': 0.5,
             'depth': 2.0, 'target': 't'}]})
        class EdgeShape:
            pass
        class Curve:
            def toShape(self):
                return EdgeShape()
        pocket_sketch.Geometry = [Curve()]
        doc.objects[pocket_sketch.Name] = pocket_sketch
        applied = []
        class Target:
            def __init__(self, name):
                self.name = name
            def set(self, shape, *, visibility, doc):
                applied.append((self.name, shape, visibility))
        refs = types.ModuleType('freecad.marz.feature.document')
        for key in ('BodyPockets', 'BodyTopPockets', 'BodyBackPockets',
                    'HeadstockPockets'):
            setattr(refs, key, Target(key))
        part = sys.modules['Part']
        class Wire:
            def __init__(self, edges):
                self.edges = edges
            def isClosed(self):
                return True
        class Solid:
            Solids = [True]
            def isNull(self):
                return False
            def isValid(self):
                return True
            def translate(self, offset):
                self.offset = offset
        class Face:
            def __init__(self, wire):
                pass
            def extrude(self, vec):
                self.extrusion = vec
                return Solid()
        part.Wire = Wire
        part.Face = Face
        part.makeCompound = lambda solids: solids
        self.app.Vector = FakeVector
        with patch.dict(sys.modules, {'freecad.marz.feature.document': refs}):
            self.assertTrue(self.module.refresh_pocket_cutters(doc, 'body'))
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0][0], 'BodyTopPockets')
        self.assertFalse(applied[0][2])
        self.assertEqual(applied[0][1][0].offset.z, -0.5)

    def test_pocket_refresh_open_wire_never_overwrites_original_cutters(self):
        doc = self.doc
        pocket_sketch = FakeObject('Marz_Sketch_BodyPockets', FakeShape())
        pocket_sketch.SVGConversionValid = True
        pocket_sketch.SVGElementMap = __import__('json').dumps({'elements': [
            {'id': 'h1_0_100', 'indices': [0], 'start': 0,
             'depth': 1.0, 'target': ''}]})
        pocket_sketch.Geometry = [types.SimpleNamespace(toShape=lambda: object())]
        doc.objects[pocket_sketch.Name] = pocket_sketch
        refs = types.ModuleType('freecad.marz.feature.document')
        for key in ('BodyPockets', 'BodyTopPockets', 'BodyBackPockets',
                    'HeadstockPockets'):
            setattr(refs, key, types.SimpleNamespace(
                set=lambda *args, **kw: self.fail('Original cutter overwritten')))
        part = sys.modules['Part']
        part.Wire = lambda edges: types.SimpleNamespace(isClosed=lambda: False,
                                                        Placement=None)
        with patch.dict(sys.modules, {'freecad.marz.feature.document': refs}):
            self.assertFalse(self.module.refresh_pocket_cutters(doc, 'body'))

    def test_svg_primitive_types_preserve_pocket_source_id(self):
        from tempfile import NamedTemporaryFile
        from pathlib import Path
        xml = b'<svg xmlns="http://www.w3.org/2000/svg"><circle id="h1_0_5"/><ellipse id="ht2_0_5"/><path id="h3_0_5"/></svg>'
        with NamedTemporaryFile(suffix='.svg') as temp:
            temp.write(xml)
            temp.flush()
            self.assertEqual(self.module.svg_pocket_primitive_types(temp.name),
                             {'h1_0_5': 'circle', 'ht2_0_5': 'ellipse'})

    def test_sampling_avoids_bspline_pole_bbox_overshoot_for_circles(self):
        from math import cos, sin, tau
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.Circle = lambda center, normal, radius: types.SimpleNamespace(
            kind='Circle', center=center, radius=radius)
        class SampledEdge:
            def discretize(self, Number):
                return [FakeVector(8 + 2 * cos(tau * i / (Number - 1)),
                                   12 + 2 * sin(tau * i / (Number - 1)))
                        for i in range(Number)]
        # Simulate OCC bound calculated from off-curve control poles.
        box = types.SimpleNamespace(XMin=5, XMax=11, YMin=9, YMax=15,
                                    ZMin=0, ZMax=0, XLength=6, YLength=6,
                                    ZLength=0)
        wire = types.SimpleNamespace(Edges=[SampledEdge()], BoundBox=box)
        fitted = self.module._fitted_circle(wire, 0.01)
        self.assertEqual(fitted.kind, 'Circle')
        self.assertAlmostEqual(fitted.radius, 2, places=5)
        self.assertAlmostEqual(fitted.center.x, 8, places=5)

    def test_native_svg_ellipse_is_a_single_sketch_ellipse(self):
        from math import cos, sin, tau
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.Ellipse = lambda major, minor, center: types.SimpleNamespace(
            kind='Ellipse', major=major, minor=minor, center=center)
        class SampledEdge:
            def discretize(self, Number):
                return [FakeVector(3 + 5 * cos(tau * i / (Number - 1)),
                                   4 + 2 * sin(tau * i / (Number - 1)))
                        for i in range(Number)]
        wire = types.SimpleNamespace(Edges=[SampledEdge()])
        fitted = self.module._fitted_axis_ellipse(wire)
        self.assertEqual(fitted.kind, 'Ellipse')
        self.assertAlmostEqual(fitted.major.x, 8, places=5)
        self.assertAlmostEqual(fitted.minor.y, 6, places=5)

    def test_svg_ellipse_with_equal_radii_becomes_native_circle(self):
        from math import cos, sin, tau
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.Circle = lambda center, normal, radius: types.SimpleNamespace(
            kind='Circle', center=center, radius=radius)
        part.Ellipse = lambda major, minor, center: types.SimpleNamespace(
            kind='Ellipse', center=center)

        class SampledEdge:
            Curve = type('BSplineCurve', (), {})()
            def discretize(self, Number):
                return [FakeVector(7 + 4 * cos(tau * i / (Number - 1)),
                                   -3 + 4 * sin(tau * i / (Number - 1)))
                        for i in range(Number)]

        wire = types.SimpleNamespace(Edges=[SampledEdge()], isClosed=lambda: True)
        result = self.module._pocket_geometry(wire, 'ellipse')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, 'Circle')
        self.assertAlmostEqual(result[0].radius, 4, places=4)

    def test_svg_ellipse_with_unequal_radii_remains_ellipse(self):
        from math import cos, sin, tau
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.Circle = lambda center, normal, radius: types.SimpleNamespace(
            kind='Circle', center=center, radius=radius)
        part.Ellipse = lambda major, minor, center: types.SimpleNamespace(
            kind='Ellipse', major=major, minor=minor, center=center)

        class SampledEdge:
            Curve = type('BSplineCurve', (), {})()
            def discretize(self, Number):
                return [FakeVector(1 + 6 * cos(tau * i / (Number - 1)),
                                   2 + 3 * sin(tau * i / (Number - 1)))
                        for i in range(Number)]

        wire = types.SimpleNamespace(Edges=[SampledEdge()], isClosed=lambda: True)
        result = self.module._pocket_geometry(wire, 'ellipse')
        self.assertEqual(result[0].kind, 'Ellipse')

    def test_native_svg_ellipse_with_equal_radii_becomes_circle(self):
        from math import cos, sin, tau
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.Circle = lambda center, normal, radius: types.SimpleNamespace(
            kind='Circle', center=center, radius=radius)

        class Ellipse:
            pass

        class Edge:
            Curve = Ellipse()

            def discretize(self, Number):
                return [FakeVector(5 * cos(tau * i / (Number - 1)),
                                   5 * sin(tau * i / (Number - 1)))
                        for i in range(Number)]

        wire = types.SimpleNamespace(Edges=[Edge()], isClosed=lambda: True)
        result = self.module._pocket_geometry(wire, 'ellipse')
        self.assertEqual(result[0].kind, 'Circle')

    def test_straight_svg_reference_creates_native_line_not_draft_spline(self):
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.LineSegment = lambda a, b: types.SimpleNamespace(
            kind='LineSegment', StartPoint=a, EndPoint=b)
        class BSplineCurve:
            pass
        class StraightEdge:
            Curve = BSplineCurve()
            FirstParameter = 0
            LastParameter = 1

            def valueAt(self, t):
                return FakeVector(-252.7207 - 3.4716 * t,
                                  -32.4585 + 64.9906 * t)

            def discretize(self, Number):
                return [self.valueAt(i / (Number - 1)) for i in range(Number)]

        source_shape = types.SimpleNamespace(Edges=[StraightEdge()])
        with patch.object(self.module, '_create_constrained_sketch',
                          side_effect=AssertionError('Draft fallback called')):
            sketch = self.module._create_straight_reference_sketch(
                self.doc, source_shape, 'Marz_Sketch_BridgeRef')
        self.assertEqual(len(sketch.Geometry), 1)
        self.assertEqual(sketch.Geometry[0].kind, 'LineSegment')
        self.assertEqual(sketch.initial_constraints, [])
        self.assertEqual(sketch.Geometry[0].StartPoint.x, -252.7207)
        self.assertEqual(sketch.Geometry[0].EndPoint.y, 32.5321)

    def test_bridge_reference_import_uses_native_line_and_keeps_svg_id(self):
        self.doc.objects.pop(self.source.Name)
        self.source = FakeObject('Marz_Body_Bridge',
                                 FakeShape(closed=False))
        self.doc.objects[self.source.Name] = self.source
        self.app.Vector = FakeVector
        part = sys.modules['Part']
        part.LineSegment = lambda a, b: types.SimpleNamespace(
            kind='LineSegment', StartPoint=a, EndPoint=b)
        edge = self.source.Shape.Edges[0]
        edge.Curve = type('BSplineCurve', (), {})()
        edge.discretize = lambda Number: [
            FakeVector(i / (Number - 1)) for i in range(Number)]
        result = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNotNone(result)
        self.assertEqual(result.Geometry[0].kind, 'LineSegment')
        self.assertEqual(self.draft_calls, [])
        import json
        self.assertEqual(json.loads(result.SVGElementMap)['elements'],
                         [{'id': 'bridge', 'indices': [0]}])
        self.assertIs(self.module.source_object(self.doc, self.source.Name),
                      result)

    def test_straight_path_lines_receive_initial_coincidence_constraints(self):
        part = sys.modules['Part']
        self.app.Vector = FakeVector
        part.LineSegment = lambda a, b: types.SimpleNamespace(
            StartPoint=a, EndPoint=b)

        class Line:
            FirstParameter = 0
            LastParameter = 1
            Curve = types.SimpleNamespace()

            def __init__(self, start, end):
                self.start, self.end = start, end

            def valueAt(self, t):
                return self.start + (self.end - self.start) * t

        def make(a, b):
            edge = Line(FakeVector(*a), FakeVector(*b))
            edge.Curve = type('Line', (), {})()
            return edge

        # The endpoints match, but the input edge order is not path order.
        edges = [make((0, 0), (2, 0)), make((2, 2), (2, 0)),
                 make((8, 8), (9, 9))]
        sketch = self.module._create_straight_reference_sketch(
            self.doc, types.SimpleNamespace(Edges=edges), 'StraightPaths')
        self.assertEqual(sketch.GeometryCount, 3)
        self.assertEqual(sketch.Constraints, [('Coincident', 0, 2, 1, 2)])

    def test_curved_svg_reference_does_not_become_straight_line(self):
        class BSplineCurve:
            pass
        class CurvedEdge:
            Curve = BSplineCurve()
            FirstParameter = 0
            LastParameter = 1

            def valueAt(self, t):
                return FakeVector(t, 0)

            def discretize(self, Number):
                return [FakeVector(t := i / (Number - 1), t * (1 - t))
                        for i in range(Number)]

        self.assertIsNone(self.module._create_straight_reference_sketch(
            self.doc, types.SimpleNamespace(Edges=[CurvedEdge()]),
            'CurvedPath'))
        self.assertIsNone(self.doc.getObject('CurvedPath'))

    def test_rectangle_from_twelve_collinear_imported_edges_yields_four_lines(self):
        part = sys.modules['Part']
        part.LineSegment = lambda a, b: types.SimpleNamespace(StartPoint=a, EndPoint=b)
        class Line:
            def __init__(self, a, b):
                self.a, self.b = a, b
                self.Curve = types.SimpleNamespace()  # patched below for native line name
                self.FirstParameter = 0
                self.LastParameter = 1
            def valueAt(self, t):
                return self.a if t == 0 else self.b
            def discretize(self, Number):
                return [self.a + (self.b - self.a) * (i / (Number - 1))
                        for i in range(Number)]
        class BSplineCurve:
            pass
        points = [FakeVector(x,y) for x,y in (
            (0,0),(1,0),(2,0),(3,0),
            (3,1),(3,2),(3,3),
            (2,3),(1,3),(0,3),
            (0,2),(0,1),(0,0))]
        edges = [Line(a,b) for a,b in zip(points[:-1],points[1:])]
        for edge in edges:
            edge.Curve = BSplineCurve()
        wire = types.SimpleNamespace(Edges=edges)
        result = self.module._closed_straight_pocket(wire)
        self.assertEqual(len(result), 4)
        self.assertEqual([(o.StartPoint.x,o.StartPoint.y) for o in result],
                         [(0,0),(3,0),(3,3),(0,3)])

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()

    def test_creates_native_sketch_source_without_overwriting_original(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.Name, 'Marz_Sketch_BodyContour')
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertIs(self.doc.getObject(self.source.Name), self.source)
        self.assertFalse(sketch.ViewObject.Visibility)
        self.assertGreaterEqual(sketch.recomputes, 1)
        self.assertEqual(len(self.doc.getObject('Marz_Group_Body').children), 1)

    def test_body_sketch_reimport_rebinds_both_native_extrusion_links(self):
        top = FakeObject('Marz_Body_Top_Extrusion_ContourLink', FakeShape())
        back = FakeObject('Marz_Body_Back_Extrusion_ContourLink', FakeShape())
        top.LinkedObject = back.LinkedObject = self.source
        self.doc.objects[top.Name] = top
        self.doc.objects[back.Name] = back
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(top.LinkedObject, sketch)
        self.assertIs(back.LinkedObject, sketch)
        # A rejected sketch must not be an input to the native extrusions.
        self.doc.removeObject(sketch.Name)
        self.created_length = 11
        bad = self.module.create_sketch(self.doc, self.source.Name)
        self.assertFalse(bad.SVGConversionValid)
        self.assertIs(top.LinkedObject, self.source)
        self.assertIs(back.LinkedObject, self.source)

    def test_reimport_repositions_all_body_sketches_from_existing_result(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        result = FakeObject('Marz_Body_Top', FakeShape())
        result.PropertiesList.extend(('SourceDisplay', 'TopPlacement'))
        result.SourceDisplay = object()
        result.TopPlacement = object()
        self.doc.objects[result.Name] = result
        calls = []
        module = types.ModuleType('freecad.marz.feature.body_parametric')
        module._position_body_sources = lambda doc, frame: calls.append((doc, frame))
        with patch.dict(sys.modules, {'freecad.marz.feature.body_parametric': module}):
            self.module._relink_body_contour(self.doc)
        self.assertEqual(calls, [(self.doc, result.TopPlacement)])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_reimport_with_only_back_result_still_uses_shared_top_plane(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        result = FakeObject('Marz_Body_Back', FakeShape())
        result.PropertiesList.extend(('SourceDisplay', 'TopPlacement'))
        result.SourceDisplay = object()  # Back frame since 0.1.60.
        result.TopPlacement = object()
        self.doc.objects[result.Name] = result
        calls = []
        module = types.ModuleType('freecad.marz.feature.body_parametric')
        module._position_body_sources = lambda doc, frame: calls.append((doc, frame))
        with patch.dict(sys.modules, {'freecad.marz.feature.body_parametric': module}):
            self.module._relink_body_contour(self.doc)
        self.assertEqual(calls, [(self.doc, result.TopPlacement)])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_legacy_nested_sketches_are_rehomed_once(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        imports = self.doc.addObject('App::DocumentObjectGroup', 'Marz_Group_Imports')
        legacy = self.doc.addObject('App::DocumentObjectGroup', self.module.GROUP_NAME)
        imports.addObject(legacy)
        legacy.addObject(sketch)
        self.module.organize_sketch_tree(self.doc)
        self.assertIn(sketch, self.doc.getObject('Marz_Group_Body').Group)
        self.assertNotIn(sketch, legacy.Group)
        self.assertNotIn(self.module.GROUP_NAME, self.doc.objects)
        self.assertEqual(self.doc.getObject('Marz_Group_Body').Group.count(sketch), 1)

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
        self.assertEqual(self.doc.getObject('Marz_Group_Body').children, [sketch])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_failed_sketch_is_not_overwritten_on_second_conversion(self):
        self.created_length = 11
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        sketch.Shape = FakeShape(length=12)
        self.created_length = 10
        self.assertIs(self.module.create_sketch(self.doc, self.source.Name), sketch)
        self.assertEqual(sketch.Shape.Length, 12)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_actual_reported_contour_bounds_difference_is_accepted(self):
        self.created_xmin = 0.219829
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertNotIn('conversion mismatch', sketch.Label)
        self.assertAlmostEqual(sketch.Placement.Base.x, 0)

    def test_actual_reported_headstock_bounds_difference_is_accepted(self):
        self.created_xmax = 10.243284
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertNotIn('conversion mismatch', sketch.Label)
        self.assertAlmostEqual(sketch.Placement.Base.x, 0)

    def test_bounds_above_half_millimeter_rejected(self):
        self.created_xmin = 0.5001
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertFalse(sketch.SVGConversionValid)
        self.assertIn('world-space XMin changed', sketch.SVGConversionError)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_total_length_above_half_millimeter_rejected(self):
        self.created_length = 10.51
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertFalse(sketch.SVGConversionValid)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_stored_rejected_sketch_revalidated_without_replacement(self):
        self.created_length = 10.6
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertFalse(sketch.SVGConversionValid)
        # Represents previously saved rejected geometry that is now within
        # the user's new 0.5 mm threshold. No reimport or regeneration.
        sketch.Shape.Length = 10.3
        existing_visibility = sketch.ViewObject.Visibility
        self.assertIs(self.module.create_sketch(self.doc, self.source.Name), sketch)
        self.assertTrue(sketch.SVGConversionValid)
        self.assertEqual(sketch.SVGConversionError, '')
        self.assertNotIn('conversion mismatch', sketch.Label)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertEqual(sketch.Shape.Length, 10.3)
        self.assertEqual(sketch.ViewObject.Visibility, existing_visibility)

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

    def test_initial_conversion_includes_coincidences(self):
        self.source.Shape = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.Constraints, [('Coincident', 0, 2, 1, 1)])
        self.assertEqual(sketch.initial_constraints, sketch.Constraints)
        self.assertFalse(self.draft_calls[-1]['autoconstraints'])
        self.assertIsNone(self.doc.getObject(sketch.Name + '_Draft'))
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_real_reported_body_drift_does_not_cancel_initial_joins(self):
        self.source.Shape = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        self.created_xmin = 0.219829
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.Constraints, [('Coincident', 0, 2, 1, 1)])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_real_reported_headstock_drift_does_not_cancel_initial_joins(self):
        self.source.Shape = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        self.created_xmax = 10.243284
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.Constraints, [('Coincident', 0, 2, 1, 1)])
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)

    def test_existing_sketch_not_modified_or_post_constrained(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        sketch.Constraints.append(('UserConstraint',))
        self.assertIs(self.module.create_sketch(self.doc, self.source.Name), sketch)
        self.assertEqual(sketch.Constraints, [('UserConstraint',)])

    def test_initial_constraints_use_source_connections_despite_draft_endpoint_drift(self):
        source = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        draft = FakeObject('Draft', source)
        draft.Geometry = [FakeCurve((0, 1.22)), FakeCurve((0.78, 2))]
        self.assertEqual(self.module._initial_endpoint_constraints(source, draft),
                         [('Coincident', 0, 2, 1, 1)])

    def test_reversed_draft_curve_joins_correct_endpoint(self):
        source = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        draft = FakeObject('Draft', source)
        draft.Geometry = [FakeCurve((1, 0)), FakeCurve((2, 1))]
        self.assertEqual(self.module._initial_endpoint_constraints(source, draft),
                         [('Coincident', 0, 1, 1, 2)])

    def test_three_way_junction_creates_spanning_tree_not_redundant_pairs(self):
        source = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2)),
                                  FakeEdge((1, 3))])
        draft = FakeObject('Draft', source)
        self.assertEqual(len(self.module._initial_endpoint_constraints(source, draft)), 2)

    def test_saved_contour_topology_sizes_generate_all_loop_joins(self):
        # The supplied marztest(1).FCStd contains body=23 and headstock=21
        # connected contour edges; verify closed-loop counting explicitly.
        for edge_count in (23, 21):
            edges = [FakeEdge((i, (i + 1) % edge_count))
                     for i in range(edge_count)]
            source = FakeShape(edges=edges)
            draft = FakeObject('Draft', source)
            joins = self.module._initial_endpoint_constraints(source, draft)
            self.assertEqual(len(joins), edge_count)

    def test_unrelated_endpoints_are_not_constrained(self):
        source = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((2, 3))])
        draft = FakeObject('Draft', source)
        self.assertEqual(self.module._initial_endpoint_constraints(source, draft), [])

    def test_ambiguous_endpoint_mapping_is_rejected(self):
        source = FakeShape(edges=[FakeEdge((0, 1)), FakeEdge((1, 2))])
        draft = FakeObject('Draft', source)
        draft.Geometry[0] = FakeCurve((10, 11))
        with self.assertRaisesRegex(ValueError, 'cannot be mapped'):
            self.module._initial_endpoint_constraints(source, draft)

    def _closed_mixed_contour(self):
        # A single SVG path: cubic Beziers interspersed with straight spans.
        p0 = FakeVector(0, 0)
        p1 = FakeVector(10, 0)
        p2 = FakeVector(10, 10)
        e0 = FakeEdge()
        e0.Curve = BezierCurve([p0, FakeVector(3, 0),
                                    FakeVector(7, 0), p1])
        e0.valueAt = lambda u: p0 if u == 0 else p1
        e1 = FakeEdge()
        e1.Curve = BSplineCurve(p1, p2)
        e1.valueAt = lambda u: p1 if u == 0 else p2
        e2 = FakeEdge()
        e2.Curve = BezierCurve([p2, FakeVector(5, 12),
                                    FakeVector(0, 5), p0])
        e2.valueAt = lambda u: p2 if u == 0 else p0
        return FakeShape(edges=[e0, e1, e2])

    def test_svg_contour_is_one_cubic_spline_not_independent_segments(self):
        source = self._closed_mixed_contour()
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}):
            curves = self.module._contour_bspline_geometry(source)
        self.assertEqual(len(curves), 1)
        c = curves[0]
        self.assertEqual(c.degree, 3)
        self.assertFalse(c.periodic)
        self.assertEqual(c.knots, [0, 1, 2, 3])
        self.assertEqual(c.mults, [4, 3, 3, 4])
        self.assertEqual(len(c.poles), 10)  # 3 segments with shared junctions
        self.assertEqual(c.poles[0].x, c.poles[-1].x)
        self.assertEqual(c.poles[0].y, c.poles[-1].y)
        # Straight span is exactly cubic degree elevated, not approximated.
        self.assertAlmostEqual(c.poles[4].x, 10)
        self.assertAlmostEqual(c.poles[4].y, 10.0 / 3.0)
        self.assertAlmostEqual(c.poles[5].y, 20.0 / 3.0)

    def test_svg_contour_creation_bypasses_draft_and_has_no_segment_constraints(self):
        self.source.Shape = self._closed_mixed_contour()
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}), patch.object(
                self.module, '_shape_difference', return_value=None):
            sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNotNone(sketch)
        self.assertGreater(sketch.GeometryCount, 1)
        self.assertEqual(sketch.exposed_splines, [0])
        self.assertEqual(sketch.Constraints[0], ('Coincident', 0, 1, 0, 2))
        self.assertIn(('InternalAlignment', 0), sketch.Constraints)
        self.assertEqual(len(self.draft_calls), 0)
        self.assertEqual(sketch.initial_constraints, sketch.Constraints)
        self.assertEqual(sketch.SVGElementMap,
                         '{"elements":[{"id":"contour","indices":[0]}],"version":1}')

    def test_contour_seam_is_constrained_at_initial_creation(self):
        self.source.Shape = self._closed_mixed_contour()
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}), patch.object(
                self.module, '_shape_difference', return_value=None):
            sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertEqual(sketch.initial_constraints[0],
                         ('Coincident', 0, 1, 0, 2))
        self.assertEqual(sketch.exposed_splines, [0])

    def test_expose_failure_does_not_publish_uneditable_contour(self):
        self.source.Shape = self._closed_mixed_contour()
        self.doc.sketch_factory = lambda name: FakeObject(name, FakeShape())
        def fail_expose(index):
            return -1
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}), patch.object(
                self.module, '_shape_difference', return_value=None):
            obj = FakeObject('Marz_Sketch_BodyContour', FakeShape())
            obj.Geometry = []
            obj.GeometryCount = 0
            obj.exposeInternalGeometry = fail_expose
            self.doc.sketch_factory = lambda name: obj
            result = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIsNone(result)
        self.assertIsNone(self.doc.getObject('Marz_Sketch_BodyContour'))
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)

    def test_svg_contour_reorders_reversed_source_edges(self):
        source = self._closed_mixed_contour()
        source.Edges[1].Curve.poles.reverse()
        original_value = source.Edges[1].valueAt
        source.Edges[1].valueAt = lambda u: original_value(1-u)
        source.Edges = [source.Edges[1], source.Edges[2], source.Edges[0]]
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}):
            curves = self.module._contour_bspline_geometry(source)
        self.assertEqual(len(curves), 1)
        self.assertEqual(len(curves[0].poles), 10)

    def test_svg_contour_rejects_disconnected_path_without_approximation(self):
        source = self._closed_mixed_contour()
        source.Edges[1].Curve.poles[1] = FakeVector(100, 100)
        with patch.dict(sys.modules, {'Part': types.SimpleNamespace(
                BSplineCurve=FakeBuiltSpline)}):
            self.assertIsNone(self.module._contour_bspline_geometry(source))

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

    def test_small_local_curve_change_is_accepted(self):
        original = FakeShape(edges=[FakeEdge((0, 1, 2))])
        sketch = FakeShape(edges=[FakeEdge((0, 1.49, 2))])
        self.assertTrue(self.module._matching_shape(original, sketch))

    def test_large_local_curve_change_is_rejected_even_with_same_bounds_and_length(self):
        original = FakeShape(edges=[FakeEdge((0, 1, 2))])
        sketch = FakeShape(edges=[FakeEdge((0, 1.51, 2))])
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

    def test_pilot_saves_svg_id_and_sketch_geometry_mapping(self):
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        import json
        metadata = json.loads(sketch.SVGElementMap)
        self.assertEqual(metadata['elements'], [{'id': 'contour', 'indices': [0]}])
        self.assertEqual(sketch.SVGSourceDocument, 'body')
        self.assertEqual(sketch.SVGSourceName, 'Marz_Body_Contour')

    def test_rejected_contours_are_overlaid_in_distinct_colors(self):
        self.created_xmin = 0.519829
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertTrue(self.source.ViewObject.Visibility)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertEqual(self.source.ViewObject.LineColor, (1.0, 0.0, 0.0))
        self.assertEqual(sketch.ViewObject.LineColor, (0.0, 1.0, 0.0))
        self.assertFalse(sketch.SVGConversionValid)

    def test_rejected_existing_sketch_activates_overlay_without_editing(self):
        self.created_xmin = 0.519829
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.source.ViewObject.Visibility = False
        sketch.ViewObject.Visibility = False
        sketch.Shape.Length = 123
        again = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(again, sketch)
        self.assertTrue(self.source.ViewObject.Visibility)
        self.assertTrue(sketch.ViewObject.Visibility)
        self.assertEqual(sketch.Shape.Length, 123)

    def test_exact_rigid_draft_offset_is_corrected_and_accepted(self):
        self.created_xmin = 0.25
        self.created_xmax = 10.25
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertAlmostEqual(sketch.Placement.Base.x, -0.25)
        self.assertFalse(self.source.ViewObject.Visibility is False and
                         sketch.ViewObject.Visibility is True)

    def test_accepted_small_non_rigid_drift_is_not_masked_by_recentering(self):
        self.created_xmin = 0.219829
        self.created_xmax = 10.0
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertIs(self.module.source_object(self.doc, self.source.Name), sketch)
        self.assertAlmostEqual(sketch.Placement.Base.x, 0.0)

    def test_non_rigid_drift_is_not_masked_by_recentering(self):
        self.created_xmin = 0.519829
        self.created_xmax = 10.0
        sketch = self.module.create_sketch(self.doc, self.source.Name)
        self.assertFalse(sketch.SVGConversionValid)
        self.assertAlmostEqual(sketch.Placement.Base.x, 0.0)

    def test_existing_document_without_sketch_uses_legacy_wire(self):
        self.assertIs(self.module.source_object(self.doc, self.source.Name), self.source)
        self.assertIsNone(self.module.source_object(self.doc, 'Marz_Headstock_Contour'))


if __name__ == '__main__':
    unittest.main()
