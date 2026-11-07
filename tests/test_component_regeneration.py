"""Offline contracts for selective regeneration (no FreeCAD GUI required)."""
import ast
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'freecad' / 'marz' / 'feature'


def extract_function(filename, name, namespace, owner=None):
    tree = ast.parse((ROOT / filename).read_text())
    nodes = tree.body
    if owner:
        nodes = next(n.body for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner)
    node = copy.deepcopy(next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name))
    # Method/function annotations are intentionally not needed for isolated tests.
    node.returns = None
    for arg in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs):
        arg.annotation = None
    code = compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / filename), 'exec')
    exec(code, namespace)
    return namespace[name]


class Document:
    def __init__(self):
        self.objects = {}

    def getObject(self, name):
        return self.objects.get(name)


class Feature:
    def __init__(self, name):
        self.Name = name
        self.Shape = object()
        self.Label = name


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document()
        self.calls = []
        def object_factory(doc, name, label, **kwargs):
            if name not in doc.objects:
                doc.objects[name] = Feature(name)
            return doc.objects[name]
        def source_shapes(*args):
            self.calls.append('build')
            return {name: object() for name in (
                'Headstock', 'TopCutter', 'VoluteCutter', 'PocketCutter', 'TrussRod')}
        self.namespace = dict(PREFIX='Marz_Neck_', _object=object_factory,
                              _source_shapes=source_shapes,
                              Part=types.SimpleNamespace(Shape=lambda: None))
        self.sources = extract_function('neck_parametric.py', '_sources', self.namespace)
        self.sources(self.doc, None, None, None, None)
        self.assertEqual(self.calls, ['build'])
        self.before = {name: obj.Shape for name, obj in self.doc.objects.items()}
        self.calls.clear()

    def changed(self):
        return {name.removeprefix('Marz_Neck_') for name, obj in self.doc.objects.items()
                if obj.Shape is not self.before[name]}

    def test_normal_recompute_retains_all_edited_shapes(self):
        self.sources(self.doc, None, None, None, None)
        self.assertEqual(self.changed(), set())
        self.assertEqual(self.calls, [])

    def test_headstock_reset_does_not_change_truss_rod(self):
        self.sources(self.doc, None, None, None, None, reset_headstock=True)
        self.assertEqual(self.changed(), {'Headstock', 'TopCutter', 'VoluteCutter', 'PocketCutter'})

    def test_neck_reset_does_not_change_headstock(self):
        self.sources(self.doc, None, None, None, None, reset_trussrod=True)
        self.assertEqual(self.changed(), {'TrussRod'})

    def test_cutter_reset_does_not_replace_headstock_solid(self):
        self.sources(self.doc, None, None, None, None, reset_cutters=True)
        self.assertEqual(self.changed(), {'TopCutter', 'VoluteCutter', 'PocketCutter', 'TrussRod'})


class BodyOutputTests(unittest.TestCase):
    def setUp(self):
        self.writes = []
        writes = self.writes
        class Target:
            def __init__(self, name):
                self.name = name
            def set(self, shape, *, doc):
                writes.append((self.name, shape))
        namespace = dict(BodyTopPart=Target('top'), BodyBackPart=Target('back'),
                         App=types.SimpleNamespace(ActiveDocument=object()))
        self.method = extract_function('body.py', 'create_parts', namespace, owner='BodyFeature')
        self.fake = types.SimpleNamespace(_build=lambda progress: ('TOP', 'BACK'))

    def test_top_writes_only_top(self):
        self.method(self.fake, None, component='top')
        self.assertEqual(self.writes, [('top', 'TOP')])

    def test_back_writes_only_back(self):
        self.method(self.fake, None, component='back')
        self.assertEqual(self.writes, [('back', 'BACK')])

    def test_update_all_still_writes_both(self):
        self.method(self.fake, None)
        self.assertEqual(self.writes, [('top', 'TOP'), ('back', 'BACK')])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class Body:
            def __init__(self, model):
                pass
            def create_parts(self, listener, *, component=None):
                calls.append(('body', component))
        class Fretboard:
            def __init__(self, model):
                pass
            def createFretboardPart(self, listener):
                calls.append(('fretboard',))
        class Listener:
            pass
        def make_create(model, fbd, neckd, **kwargs):
            calls.append(('neck_tree', kwargs))
        builder_module = types.ModuleType('freecad.marz.model.fretboard_builder')
        builder_module.buildFretboardData = lambda model: object()
        neck_data_module = types.ModuleType('freecad.marz.model.neck_data')
        neck_data_module.NeckData = lambda model, fbd: object()
        parametric_module = types.ModuleType('freecad.marz.feature.neck_parametric')
        parametric_module.create = make_create
        svg_module = types.ModuleType('freecad.marz.feature.svg_sketch')
        svg_module.refresh_pocket_cutters = lambda doc, category: calls.append(('pockets', category))
        self.module_stubs = {
            'freecad.marz.feature.svg_sketch': svg_module,
            'freecad': types.ModuleType('freecad'),
            'freecad.marz': types.ModuleType('freecad.marz'),
            'freecad.marz.model': types.ModuleType('freecad.marz.model'),
            'freecad.marz.feature': types.ModuleType('freecad.marz.feature'),
            'freecad.marz.model.fretboard_builder': builder_module,
            'freecad.marz.model.neck_data': neck_data_module,
            'freecad.marz.feature.neck_parametric': parametric_module,
        }
        class Instrument:
            pass
        class Props:
            @staticmethod
            def save_object_to_model(model, obj):
                calls.append(('properties',))
        self.namespace = dict(Instrument=Instrument, InstrumentProps=Props,
                              progress_indicator=lambda _: nullcontext(), transaction=lambda _: nullcontext(),
                              traceTime=lambda *args: nullcontext(),
                              BodyFeature=Body, FretboardFeature=Fretboard,
                              QApplication=types.SimpleNamespace(processEvents=lambda: None))
        self.method = extract_function('instrument.py', 'regenerate_component', self.namespace,
                                       owner='MarzInstrument')
        self.self_obj = types.SimpleNamespace(Object=types.SimpleNamespace(Document=object()),
                                              recompute=lambda: calls.append(('recompute',)))

    def run_target(self, component):
        with patch.dict(sys.modules, self.module_stubs):
            self.method(self.self_obj, component, object())
        self.assertEqual(self.calls[-1], ('recompute',))

    def test_body_top_only(self):
        self.run_target('body_top')
        self.assertIn(('body', 'top'), self.calls)
        self.assertNotIn(('body', 'back'), self.calls)

    def test_body_back_only(self):
        self.run_target('body_back')
        self.assertIn(('body', 'back'), self.calls)
        self.assertNotIn(('body', 'top'), self.calls)

    def test_fretboard_only(self):
        self.run_target('fretboard')
        self.assertIn(('fretboard',), self.calls)

    def test_neck_isolated_from_headstock(self):
        self.run_target('neck')
        self.assertIn(('neck_tree', dict(regenerate_neck=True, regenerate_headstock=False)), self.calls)

    def test_headstock_isolated_from_neck(self):
        self.run_target('headstock')
        self.assertIn(('neck_tree', dict(regenerate_neck=False, regenerate_headstock=True)), self.calls)

    def test_invalid_target_is_rejected_without_side_effects(self):
        with self.assertRaises(ValueError):
            self.method(self.self_obj, 'other', object())
        self.assertEqual(self.calls, [])

    def test_all_five_buttons_capture_distinct_target_and_ignore_qt_checked(self):
        tree = ast.parse((ROOT / 'edit_form_layout.py').read_text())
        hook = next(n for n in ast.walk(tree) if isinstance(n, ast.Lambda) and
                    any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and
                        c.func.attr == 'regenerate_component' for c in ast.walk(n)))
        outputs = []
        for target in ('body_top', 'body_back', 'neck', 'headstock', 'fretboard'):
            form = types.SimpleNamespace(regenerate_component=lambda target: outputs.append(target))
            # Emulate each iteration's lexical binding, then Qt clicked(bool).
            cb = eval(compile(ast.Expression(hook), '<button>', 'eval'), {'form': form, 'component': target})
            cb(True)
        self.assertEqual(outputs, ['body_top', 'body_back', 'neck', 'headstock', 'fretboard'])


if __name__ == '__main__':
    unittest.main()
