# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent SVG reader / Sketcher adapter contract tests (no FreeCAD needed)."""
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from freecad.marz.svg_to_sketch.reader import (Affine, SVGReadError, read_svg,
                                              parse_path, transform)
from freecad.marz.svg_to_sketch.sketch import (_arc_center, _point_on_arc, create_sketch,
                                              geometry_for_element)

SVG='http://www.w3.org/2000/svg'
INK='http://www.inkscape.org/namespaces/inkscape'


def document(inner, width='100mm', height='50mm', viewbox='0 0 100 50'):
    return ('<svg xmlns="%s" xmlns:inkscape="%s" width="%s" height="%s" '
            'viewBox="%s">%s</svg>') % (SVG,INK,width,height,viewbox,inner)


def read_text(text):
    with tempfile.TemporaryDirectory() as tmp:
        name=Path(tmp,'drawing.svg')
        name.write_text(text,encoding='utf8')
        return read_svg(name)


class Vector:
    def __init__(self,*xyz): self.x,self.y,self.z=xyz


class Geo:
    def __init__(self,*args): self.args=args


class BSplineCurve:
    def buildFromPolesMultsKnots(self,*args): self.args=args


class FakePart(types.ModuleType):
    def __init__(self):
        super().__init__('Part')
        for name in ('LineSegment','Circle','Ellipse','Arc','ArcOfEllipse'):
            setattr(self,name,type(name,(Geo,),{}))
        self.BSplineCurve=BSplineCurve


class Sketch:
    def __init__(self):
        self.Geometry=[]
        self.PropertiesList=[]
    def addGeometry(self,g,construction):
        self.Geometry.extend(g)
    def addProperty(self,kind,name,group):
        self.PropertiesList.append(name)


class Doc:
    def addObject(self,typ,name):
        assert typ=='Sketcher::SketchObject'
        self.sketch=Sketch()
        return self.sketch


class SVGReaderTests(unittest.TestCase):
    def test_id_first_label_fallback(self):
        elements=read_text(document('<g id="layer1"><circle id="x1" '
            'inkscape:label="F13_" cx="5" cy="6" r="4"/>'
            '<path id="zehn" inkscape:label="f10p25" d="M0 0 L1 0"/></g>'))
        self.assertEqual([e.id for e in elements],['x1','zehn'])
        self.assertEqual([e.group_ids for e in elements],[('layer1',)]*2)
        matcher=lambda v:v.lower().startswith('f')
        self.assertEqual(elements[0].name(matcher),'F13_')
        self.assertEqual(elements[1].name(matcher),'f10p25')
        self.assertEqual(elements[1].name(lambda v:v=='zehn'),'zehn')

    def test_native_primitive_types(self):
        elements=read_text(document('<circle id="c" r="4" cx="5" cy="6"/>'
            '<ellipse id="e" rx="4" ry="5" cx="6" cy="7"/>'
            '<line id="l" x1="0" y1="0" x2="2" y2="3"/>'
            '<polyline id="p" points="0,0 1,2 2,0"/>'
            '<polygon id="g" points="0,0 1,2 2,0"/>'
            '<rect id="r" x="1" y="2" width="3" height="4"/>'
            '<rect id="rr" x="1" y="2" width="3" height="4" rx="1"/>'
            '<path id="b" d="M0 0 C1 2 2 1 3 3 Q4 5 6 8"/>'))
        kinds={e.id:[p.kind for p in e.primitives] for e in elements}
        self.assertEqual(kinds['c'],['circle'])
        self.assertEqual(kinds['e'],['ellipse'])
        self.assertEqual(kinds['l'],['line'])
        self.assertEqual(kinds['p'],['line','line'])
        self.assertEqual(kinds['g'],['line','line','line'])
        self.assertEqual(kinds['r'],['line']*4)
        self.assertEqual(kinds['rr'],['line','arc']*4)
        self.assertEqual(kinds['b'],['cubic','quadratic'])

    def test_path_all_commands_implicit_and_smooth(self):
        parts=parse_path('M0 0 5 0 l5 5 h-3 v2 c1 1 2 2 3 3 s4 4 5 5 '
                         'q1 1 2 2 t2 2 a5 6 30 0 1 3 4 z')
        self.assertEqual([p.kind for p in parts],
                         ['line','line','line','line','cubic','cubic',
                          'quadratic','quadratic','arc','line'])
        self.assertEqual(parts[5].points[1],
                         (2*parts[4].points[-1][0]-parts[4].points[-2][0],
                          2*parts[4].points[-1][1]-parts[4].points[-2][1]))

    def test_consecutive_subpaths(self):
        pieces=parse_path('M0 0 H1 V1 Z M3 0 H4 V1 Z')
        self.assertEqual(len(pieces),6)
        self.assertEqual(pieces[-1].points[-1],(3.,0.))

    def test_nested_transform_and_unit_conversion(self):
        els=read_text(document('<g id="outer" transform="translate(2,3)">'
            '<g id="inner" transform="rotate(90)">'
            '<line id="l" x1="1" y1="0" x2="2" y2="0"/></g></g>',
            width='200mm',height='100mm'))
        m=els[0].transform
        self.assertEqual(els[0].group_ids,('outer','inner'))
        self.assertAlmostEqual(m.point((1,0))[0],4.)
        self.assertAlmostEqual(m.point((1,0))[1],8.)

    def test_viewbox_aspect_ratio_meet_and_none(self):
        el=read_text(document('<circle r="1"/>',width='200mm',height='50mm'))[0]
        self.assertAlmostEqual(el.transform.point((0,0))[0],50)
        self.assertAlmostEqual(el.transform.point((100,50))[0],150)
        text=document('<circle r="1"/>',width='200mm',height='50mm').replace(
            '<svg xmlns=', '<svg preserveAspectRatio="none" xmlns=')
        el=read_text(text)[0]
        self.assertAlmostEqual(el.transform.point((100,50))[0],200)
        self.assertAlmostEqual(el.transform.point((100,50))[1],50)

    def test_svg_transform_matrix_and_order(self):
        m=transform('translate(10,20) scale(2)')
        self.assertEqual(m.point((3,5)),(16,30))
        m=transform('matrix(1,2,3,4,5,6)')
        self.assertEqual(m.point((1,1)),(9,12))

    def test_hidden_and_defs_are_skipped(self):
        e=read_text(document('<defs><circle id="definition" r="1"/></defs>'
            '<circle id="one" r="1"/><g style="display:none">'
            '<circle id="hidden" r="1"/></g>'))
        self.assertEqual([x.id for x in e],['one'])

    def test_bad_geometry_is_not_silently_accepted(self):
        with self.assertRaises(SVGReadError): parse_path('M1 1 A2 3 0 4 0 5 6')
        with self.assertRaises(SVGReadError): parse_path('M0 0 L1')
        with self.assertRaises(SVGReadError): transform('warp(1,2)')
        with self.assertRaises(SVGReadError): read_text(document('<use href="#x"/>'))

    def test_arc_center(self):
        c,rx,ry,start,delta=_arc_center((0,0),(10,0),5,5,0,0,1)
        self.assertAlmostEqual(c[0],5)
        self.assertAlmostEqual(c[1],0)
        self.assertAlmostEqual(abs(delta),math.pi)
        self.assertGreater(delta,0)

    def test_arc_quadrants_preserve_svg_circle_outline(self):
        parts=parse_path('M10 0 A10 10 0 0 1 0 10 '
                         'A10 10 0 0 1 -10 0 '
                         'A10 10 0 0 1 0 -10 '
                         'A10 10 0 0 1 10 0 Z')
        self.assertEqual([part.kind for part in parts],['arc']*4)
        points=[]
        for part in parts:
            rx,ry,rotation,large,sweep=part.values
            c,rx,ry,start,delta=_arc_center(*part.points,rx,ry,0,large,sweep)
            points.extend(_point_on_arc(c,rx,ry,0,start+delta*i/100)
                          for i in range(101))
        self.assertAlmostEqual(min(p[0] for p in points),-10.,places=6)
        self.assertAlmostEqual(max(p[0] for p in points),10.,places=6)
        self.assertAlmostEqual(min(p[1] for p in points),-10.,places=6)
        self.assertAlmostEqual(max(p[1] for p in points),10.,places=6)

    def test_legacy_wire_name_matches_multicontour_subpaths(self):
        from tools.compare_svg_imports import _same_svg_source
        for name in ('f12_', 'f12__w', 'f12__1_w', 'f12__2_w3'):
            self.assertTrue(_same_svg_source(name,'f12_'),name)
        for name in ('f12__1_unrelated','f12a_w','f12_3bad'):
            self.assertFalse(_same_svg_source(name,'f12_'),name)


class SketcherAdapterTests(unittest.TestCase):
    def setUp(self):
        self.modules=patch.dict(sys.modules,{'FreeCAD':types.SimpleNamespace(Vector=Vector),
                                             'Part':FakePart()})
        self.modules.start()
    def tearDown(self):self.modules.stop()

    def test_native_circle_ellipse_and_line(self):
        shapes=read_text(document('<circle id="a" cx="10" cy="4" r="3"/>'
           '<ellipse id="b" cx="10" cy="4" rx="3" ry="2"/>'
           '<g transform="scale(2,1)"><circle id="c" cx="10" cy="4" r="3"/></g>'
           '<line id="l" x1="0" x2="1" y1="2" y2="2"/>'))
        self.assertEqual([type(geometry_for_element(x)[0]).__name__ for x in shapes],
                         ['Circle','Ellipse','Ellipse','LineSegment'])

    def test_cubic_and_quadratic_spline_degrees(self):
        el=read_text(document('<path id="b" d="M0 0 C1 2 2 1 3 3 Q4 5 6 8"/>'))[0]
        g=geometry_for_element(el)
        self.assertEqual([x.args[-1] for x in g],[3,2])
        self.assertEqual([len(x.args[0]) for x in g],[4,3])

    def test_circular_and_elliptical_arcs(self):
        el=read_text(document('<path id="a" d="M0 0 A5 5 0 0 1 10 0"/>'
                              '<path id="b" d="M0 0 A5 7 0 0 1 10 0"/>'))
        self.assertEqual([type(geometry_for_element(e)[0]).__name__ for e in el],
                         ['Arc','ArcOfEllipse'])

    def test_sketch_preserves_source_metadata(self):
        element=read_text(document('<path id="zehn" inkscape:label="f10p25" '
                                   'd="M0 0 H1"/>'))[0]
        d=Doc()
        sketch=create_sketch(d,element,'svg_cmp',connect_endpoints=False)
        self.assertEqual(sketch.SVGSourceID,'zehn')
        self.assertEqual(sketch.SVGSourceLabel,'f10p25')
        mapping=json.loads(sketch.SVGElementMap)
        self.assertEqual(mapping['elements'][0]['indices'],[0])


if __name__=='__main__':unittest.main()
