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


class Rotation:
    def __init__(self, normal=None):
        self.normal = normal or Vector(0, 0, 1)

    def multVec(self, vector):
        # Enough to exercise the rotated-local-Z direction contract.
        return self.normal


class Placement:
    def __init__(self, base=None, rotation=None):
        self.Base = base or Vector()
        self.Rotation = rotation or Rotation()

    def multiply(self, other):
        # Translation-only fake. Production FreeCAD also composes rotations.
        return Placement(self.Base + other.Base, self.Rotation)

    def inverse(self):
        return Placement(Vector(-self.Base.x, -self.Base.y, -self.Base.z))


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
        # OCCT booleans operate on located shapes; keep the source location in
        # this lightweight model so placement regressions remain observable.
        result.Placement = self.Placement
        self.cut_calls.append(other)
        return result

    def removeSplitter(self):
        return self

    def translate(self, offset):
        return None


class View:
    def __init__(self):
        self.Visibility = True
        self.Proxy = None


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
        if kind == 'App::Link':
            # FreeCAD App::Link defaults to an independent Placement. The
            # linked object's Placement is included only with LinkTransform.
            self.LinkTransform = False

    def __setattr__(self, name, value):
        if name in ('LengthFwd', 'LengthRev') and isinstance(value, (int, float)):
            value = Quantity(value)
        object.__setattr__(self, name, value)
        if name == 'Placement' and getattr(self, 'TypeId', None) == 'Sketcher::SketchObject':
            shape = getattr(self, 'Shape', None)
            if shape is not None:
                shape.Placement = value

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
            source = self.Base.LinkedObject.Shape
            self.Shape = Shape(source.Volume * self.LengthFwd.Value)
            # Match App::Link placement semantics closely enough to catch the
            # real regression: without LinkTransform, the link's identity
            # placement drops the positioned Sketcher's location.
            self.Shape.Placement = (source.Placement if self.Base.LinkTransform
                                    else self.Base.Placement)
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
        paths = types.ModuleType('freecad.marz.extension.paths')
        paths.iconPath = lambda name: name
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
            'freecad.marz.extension.paths': paths,
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
        self.assertFalse(top.Base.LinkTransform)
        self.assertFalse(back.Base.LinkTransform)
        self.assertEqual(top.Base.Placement.Base.z, 5)
        self.assertEqual(back.Base.Placement.Base.z, -5)
        self.assertEqual(top.LengthFwd.Value, 4)
        self.assertEqual(back.LengthFwd.Value, 10)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 400)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 1000)
        body_group = self.doc.getObject('Marz_Group_Body')
        self.assertIn(self.contour, body_group.Group)
        self.assertNotIn(self.contour, self.doc.getObject('Marz_Group_Imports').Group)

    def test_body_world_placement_composes_imported_svg_location(self):
        # Supplied marztest.FCStd: the imported Body Contour carries
        # (-289.832744, +106.254652), while the legacy finished Top and Back
        # add outer placements (-403.085610, 0, -7) and
        # (-403.085610, 0, -47). Both transformations must survive the
        # editable Sketch -> App::Link -> Part::Extrusion chain.
        self.contour.Placement = Placement(Vector(-289.8327438, 106.2546525, 0))
        self.bodyd.placements = lambda bridge: (
            Placement(Vector(-403.0856100, 0, -7)),
            Placement(Vector(-403.0856100, 0, -47)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        back = self.doc.getObject('Marz_Body_Back')
        top_blank = self.doc.getObject('Marz_Body_Top_Extrusion')
        back_blank = self.doc.getObject('Marz_Body_Back_Extrusion')
        expected_x = -692.9183538

        self.assertAlmostEqual(self.contour.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(self.contour.Shape.Placement.Base.y, 106.2546525, places=5)
        self.assertAlmostEqual(top_blank.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(back_blank.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(top_blank.Shape.Placement.Base.z, -7, places=5)
        self.assertAlmostEqual(back_blank.Shape.Placement.Base.z, -47, places=5)

        self.assertAlmostEqual(top.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(top.Shape.Placement.Base.y, 106.2546525, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.y, 106.2546525, places=5)
        self.assertAlmostEqual(top.Shape.Placement.Base.z, -7, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.z, -47, places=5)

        self.doc.recompute()
        self.assertAlmostEqual(top.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(top.Shape.Placement.Base.z, -7, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.z, -47, places=5)

    def test_neck_pocket_boolean_keeps_both_finished_body_placements(self):
        self.contour.Placement = Placement(Vector(-289.8327438, 106.2546525, 0))
        self.bodyd.placements = lambda bridge: (
            Placement(Vector(-403.0856100, 0, -7)),
            Placement(Vector(-403.0856100, 0, -47)))
        self.bodyd.neckPocketCarve = True
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        back = self.doc.getObject('Marz_Body_Back')
        expected_x = -692.9183538
        self.assertAlmostEqual(top.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.x, expected_x, places=5)
        self.assertAlmostEqual(top.Shape.Placement.Base.z, -7, places=5)
        self.assertAlmostEqual(back.Shape.Placement.Base.z, -47, places=5)
        self.assertEqual(top.BuildStatus, 'OK')
        self.assertEqual(back.BuildStatus, 'OK')

    def test_identity_source_still_uses_only_guitar_placement(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        self.assertEqual(top.Shape.Placement.Base.x, 5)
        self.assertEqual(self.contour.Placement.Base.x, 5)
        self.assertEqual(self.doc.getObject('Marz_Body_Top_Extrusion').Shape.Placement.Base.x, 5)
        self.assertEqual(top.Shape.Placement.Base.z, 5)

    def test_extrusion_axis_follows_body_local_z_not_world_z(self):
        tilted = Rotation(Vector(0.2, 0, 0.98))
        self.bodyd.placements = lambda _: (Placement(Vector(5, 0, 5), tilted),
                                           Placement(Vector(5, 0, -5), tilted))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        for side in ('Top', 'Back'):
            blank = self.doc.getObject('Marz_Body_' + side + '_Extrusion')
            self.assertEqual(blank.Dir.x, 0.2)
            self.assertEqual(blank.Dir.z, 0.98)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Placement.Base.x, 5)

    def test_repeated_regeneration_keeps_sketch_in_place(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(self.contour.Placement.Base.x, 5)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Placement.Base.x, 5)

    def test_body_parameter_shift_moves_sketch_once(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.bodyd.placements = lambda _: (Placement(Vector(17, 0, 8)),
                                           Placement(Vector(17, 0, -2)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(self.contour.Placement.Base.x, 17)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Placement.Base.x, 17)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Placement.Base.z, -2)

    def test_manual_sketch_placement_is_preserved_on_regenerate(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.contour.Placement = Placement(Vector(8, 1, 5))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(self.contour.Placement.Base.x, 8)
        self.assertEqual(self.contour.Placement.Base.y, 1)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Placement.Base.x, 8)

    def test_bridge_sketch_does_not_shift_anchor_on_second_regenerate(self):
        bridge = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BridgeRef')
        bridge.Shape = Shape(5)
        bridge_ref_seen = []
        def placements(ref):
            bridge_ref_seen.append(ref.Shape.Placement.Base.x)
            return (Placement(Vector(5, 0, 5)), Placement(Vector(5, 0, -5)))
        self.bodyd.placements = placements
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(bridge_ref_seen, [0, 0])
        self.assertEqual(bridge.Placement.Base.x, 5)

    def test_body_master_sketch_mirrors_contour_frame_without_driving_it(self):
        master = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyMaster')
        master.Shape = Shape(50)
        master.Placement = Placement(Vector(99, 0, 99))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        contour = self.doc.getObject('Marz_Sketch_BodyContour')
        self.assertEqual(master.Placement.Base.x, contour.Placement.Base.x)
        self.assertEqual(master.Placement.Base.z, contour.Placement.Base.z)
        self.assertEqual(master.Placement.Base.x, 5)
        self.assertEqual(master.Placement.Base.z, 5)

    def test_both_body_halves_use_master_contour_profile(self):
        import json
        master = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyMaster')
        master.SVGConversionValid = True
        master.SVGElementMap = json.dumps({'elements': [
            {'id': 'contour', 'role': 'body-contour', 'indices': [0]}]})
        master.Geometry = [types.SimpleNamespace(toShape=lambda: Shape(125))]
        self.part.Wire = lambda edges: Shape(sum(edge.Volume for edge in edges))
        Shape.isClosed = lambda self: True

        self.mod.regenerate_body(object(), self.bodyd, self.doc)

        profile = self.doc.getObject('Marz_Body_Top_MasterContour')
        top = self.doc.getObject('Marz_Body_Top_Extrusion')
        back = self.doc.getObject('Marz_Body_Back_Extrusion')
        self.assertIsNotNone(profile)
        self.assertIs(profile.Source, master)
        self.assertEqual(profile.BuildStatus, 'OK')
        self.assertIs(top.Base.LinkedObject, profile)
        self.assertIs(back.Base.LinkedObject, profile)
        self.assertEqual(profile.Placement.Base.x, self.contour.Placement.Base.x)
        self.assertEqual(profile.Placement.Base.z, self.contour.Placement.Base.z)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 500)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 1250)

    def test_first_grouped_pocket_operation_is_master_driven_without_double_cut(self):
        import json
        master = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyMaster')
        master.SVGConversionValid = True
        master.SVGElementMap = json.dumps({
            'elements': [
                {'id': 'contour', 'role': 'body-contour', 'indices': [0]},
                {'id': 'h1_0_200', 'role': 'pocket', 'indices': [1],
                 'start': 0, 'depth': 2, 'target': ''},
            ],
            'operations': [
                {'target': '', 'start': 0, 'end': 2, 'ids': ['h1_0_200']},
            ],
        })
        master.Geometry = [
            types.SimpleNamespace(toShape=lambda: Shape(100)),
            types.SimpleNamespace(toShape=lambda: Shape(2)),
        ]
        legacy = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyPockets')
        legacy.SVGConversionValid = True
        legacy.SVGElementMap = json.dumps({'elements': [
            {'id': 'h1_0_200', 'indices': [0], 'start': 0,
             'depth': 2, 'target': ''}]})
        legacy.Geometry = [types.SimpleNamespace(toShape=lambda: Shape(50))]

        self.part.Wire = lambda edges: Shape(sum(edge.Volume for edge in edges))
        Shape.isClosed = lambda self: True
        self.part.Face = lambda wire: types.SimpleNamespace(
            extrude=lambda direction: Shape(wire.Volume * abs(direction.z)))

        self.mod.regenerate_body(object(), self.bodyd, self.doc)

        pilot = self.doc.getObject('Marz_Body_MasterPocketPilot')
        legacy_both = self.doc.getObject('Marz_Body_SketchCutters_Both')
        combined = self.doc.getObject('Marz_Body_CombinedPocketCutters_Both')
        self.assertEqual(json.loads(pilot.IDs), ['h1_0_200'])
        self.assertEqual(json.loads(legacy_both.ExcludedIDs), ['h1_0_200'])
        self.assertTrue(legacy_both.Shape.isNull())
        self.assertEqual(pilot.Shape.Volume, 4)
        self.assertIs(combined.Master, pilot)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 396)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 996)

        master.Geometry[1] = types.SimpleNamespace(toShape=lambda: Shape(3))
        self.doc.recompute()
        self.assertEqual(pilot.Shape.Volume, 6)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Volume, 394)
        self.assertEqual(self.doc.getObject('Marz_Body_Back').Shape.Volume, 994)

    def test_body_pocket_sketch_shares_body_frame_and_cutters_use_source_frame(self):
        import json
        sketch = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyPockets')
        sketch.SVGConversionValid = True
        sketch.SVGElementMap = json.dumps({'elements': [
            {'id': 'ht1_0_200', 'indices': [0], 'start': 0,
             'depth': 2, 'target': 't'}]})
        sketch.Geometry = [types.SimpleNamespace(toShape=lambda: object())]
        wire_placements = []
        class Wire:
            def __init__(self, edges):
                self._placement = Placement()
            @property
            def Placement(self):
                return self._placement
            @Placement.setter
            def Placement(self, new):
                self._placement = new
                wire_placements.append(new.Base.x)
            def isClosed(self):
                return True
        self.part.Wire = Wire
        self.part.Face = lambda wire: types.SimpleNamespace(
            extrude=lambda direction: Shape(abs(direction.z)))
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        self.assertEqual(sketch.Placement.Base.x, 5)
        self.assertTrue(wire_placements)
        self.assertTrue(all(abs(x) < 1e-8 for x in wire_placements))

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

    def test_migration_shows_positioned_finished_body_not_source_blanks(self):
        # A saved static result can be hidden during migration; it must not
        # leave the unpositioned construction blank as the visible guitar.
        old_top = self.doc.addObject('Part::FeatureExt', 'Marz_Body_Top')
        old_top.ViewObject.Visibility = False
        old_back = self.doc.addObject('Part::FeatureExt', 'Marz_Body_Back')
        old_back.ViewObject.Visibility = False
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        for side in ('Top', 'Back'):
            finished = self.doc.getObject('Marz_Body_' + side)
            blank = self.doc.getObject('Marz_Body_' + side + '_Extrusion')
            self.assertTrue(finished.ViewObject.Visibility)
            self.assertFalse(blank.ViewObject.Visibility)
            self.assertEqual(finished.TypeId, 'Part::FeaturePython')
            self.assertIsInstance(finished.ViewObject.Proxy, self.mod.BodyViewProvider)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').Shape.Placement.Base.x, 5)

    def test_regenerate_repairs_inverted_legacy_display(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        blank = self.doc.getObject('Marz_Body_Top_Extrusion')
        # Reproduce the supplied FreeCAD screenshot.
        top.ViewObject.Visibility = False
        blank.ViewObject.Visibility = True
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='top')
        self.assertTrue(top.ViewObject.Visibility)
        self.assertFalse(blank.ViewObject.Visibility)
        self.assertTrue(self.doc.getObject('Marz_Body_Back').ViewObject.Visibility)

    def test_existing_parametric_result_respects_manual_hidden_state(self):
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        top = self.doc.getObject('Marz_Body_Top')
        top.ViewObject.Visibility = False
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='top')
        self.assertFalse(top.ViewObject.Visibility)
        self.assertFalse(self.doc.getObject('Marz_Body_Top_Extrusion').ViewObject.Visibility)

    def test_existing_static_output_is_migrated_only_on_regeneration(self):
        old = self.doc.addObject('Part::FeatureExt', 'Marz_Body_Top')
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='back')
        self.assertIs(old, self.doc.getObject('Marz_Body_Top'))
        self.mod.regenerate_body(object(), self.bodyd, self.doc, component='top')
        self.assertNotEqual(self.doc.getObject('Marz_Body_Top').TypeId, old.TypeId)
        self.assertEqual(self.doc.getObject('Marz_Body_Top').TypeId, 'Part::FeaturePython')

    def test_derived_pocket_cutters_use_body_view_provider(self):
        import json
        sketch = self.doc.addObject('Sketcher::SketchObject', 'Marz_Sketch_BodyPockets')
        sketch.SVGConversionValid = True
        sketch.SVGElementMap = json.dumps({'elements': []})
        self.mod.regenerate_body(object(), self.bodyd, self.doc)
        for label in ('Both', 'Top', 'Back'):
            cutter = self.doc.getObject('Marz_Body_SketchCutters_' + label)
            self.assertEqual(cutter.TypeId, 'Part::FeaturePython')
            self.assertIsInstance(cutter.ViewObject.Proxy, self.mod.BodyViewProvider)

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
