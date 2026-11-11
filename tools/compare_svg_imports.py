# SPDX-License-Identifier: GPL-3.0-or-later
"""Non-destructive SVG reader/Sketcher comparison.

Offline: python tools/compare_svg_imports.py FILE.svg ...
In FreeCAD Python console (from repository directory):
  from tools.compare_svg_imports import run
  run(['/absolute/path/to/test_neck.svg'], freecad=True)

Detailed JSON is written to the named report, with per-element exceptions,
primitive types, imported names, geometry counts, bounding boxes and sampled
Hausdorff-like deviations. Temporary FreeCAD documents are always closed.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from freecad.marz.svg_to_sketch.reader import read_svg

LEGACY = {
    'neck/inlay': re.compile(r'^f(\d+)_.*?(?:(_\d+)?_w\d*)?$',re.I),
    'pocket': re.compile(r'^h([tb]?)\d+_(\d+)_(\d+)(?:(_\d+)?_w\d*)?$',re.I),
    'reference': re.compile(r'^(?:contour|midline|transition|bridge|neckpocket)(?:_w\d*)?$',re.I),
    'ergonomic': re.compile(r'^ec([tb])_(\d+)(?:(_\d+)?_w\d*)?$',re.I),
    'ergonomic control': re.compile(r'^ec([tb])_(\d+)_(\d+)(?:(_\d+)?_w\d*)?$',re.I),
}


def old_identifier(element):
    """Model only current lexical classification, NOT current FreeCAD topology."""
    for name, pattern in LEGACY.items():
        candidate=element.name(lambda value: pattern.fullmatch(value))
        if candidate is not None:
            return {'category':name,'source':('id' if candidate==element.id else 'label'),
                    'value':candidate}
    return None


def _box(shape):
    b=shape.BoundBox
    return [round(v,6) for v in (b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax)]


def _sample_distance(first,second):
    """Approximate bidirectional max distance using 17 samples per edge."""
    import Part
    greatest=0.
    for shape,target in ((first,second),(second,first)):
        for edge in shape.Edges:
            for point in edge.discretize(Number=17):
                d=target.distToShape(Part.Vertex(point))[0]
                greatest=max(greatest,float(d))
    return greatest


def compare_freecad(filename, elements):
    import FreeCAD as App
    import importSVG
    from freecad.marz.svg_to_sketch.sketch import create_sketch
    from uuid import uuid4
    suffix=uuid4().hex[:9]
    previous=App.ActiveDocument.Name if App.ActiveDocument else None
    old=App.newDocument('SVG_old_'+suffix)
    try:
        importSVG.insert(str(filename),old.Name)
        old.recompute()
        # Record legacy data before creating or closing documents.
        old_objects=list(old.Objects)
        new=App.newDocument('SVG_new_'+suffix)
        try:
            output=[]
            for idx,element in enumerate(elements):
                entry={'id':element.id,'label':element.label}
                candidates=[]
                # FreeCAD importSVG generally keeps the original SVG id as Name,
                # then appends _wN for multi-wire paths. Keep all candidates.
                for ob in old_objects:
                    name=getattr(ob,'Name','')
                    if element.id and (name==element.id or name.startswith(element.id+'_w')):
                        if hasattr(ob,'Shape') and not ob.Shape.isNull():
                            candidates.append(ob)
                entry['legacy_objects']=[{'name':ob.Name,'label':ob.Label,
                                          'bbox_mm':_box(ob.Shape),
                                          'edges':len(ob.Shape.Edges),
                                          'edge_types':dict(Counter(type(edge.Curve).__name__
                                                                   for edge in ob.Shape.Edges))}
                                         for ob in candidates]
                try:
                    sketch=create_sketch(new,element,'SVG_compare_%03d'%idx)
                    new.recompute()
                    entry['native_geometry']=[type(g).__name__ for g in sketch.Geometry]
                    entry['native_bbox_mm']=_box(sketch.Shape)
                    entry['native_edges']=len(sketch.Shape.Edges)
                    if candidates:
                        import Part
                        old_compound=Part.makeCompound([ob.Shape for ob in candidates])
                        entry['max_sample_distance_mm']=round(_sample_distance(
                            old_compound,sketch.Shape),6)
                    else:
                        entry['warning']='No matching legacy object name'
                except Exception:
                    entry['error']=traceback.format_exc()
                output.append(entry)
            return output
        finally:
            App.closeDocument(new.Name)
    finally:
        App.closeDocument(old.Name)
        if previous and App.getDocument(previous):
            App.setActiveDocument(previous)


def run(filenames, *, freecad=False, report=None):
    data=[]
    for filename in filenames:
        path=Path(filename).resolve()
        elements=read_svg(path)
        items=[]
        for el in elements:
            counts=Counter(p.kind for p in el.primitives)
            items.append({'id':el.id,'label':el.label,'tag':el.tag,
                          'group_ids':list(el.group_ids),
                          'transform':list(vars(el.transform).values()),
                          'primitive_counts':dict(counts),
                          'legacy_identifier':old_identifier(el)})
        summary={'file':str(path), 'element_count':len(elements),
                 'primitive_counts':dict(Counter(p.kind for el in elements for p in el.primitives)),
                 'legacy_recognized':sum(item['legacy_identifier'] is not None for item in items),
                 'items':items}
        if freecad:
            summary['comparison']=compare_freecad(path,elements)
        data.append(summary)
    dest=Path(report).resolve() if report else Path('/tmp/marz-svg-compare.json')
    dest.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    for item in data:
        print('[SVG COMPARE] %s: %s elements, %s primitives, %s legacy lexical matches' % (
            item['file'],item['element_count'],sum(item['primitive_counts'].values()),
            item['legacy_recognized']))
        for e in item.get('comparison',[]):
            if e.get('error') or e.get('warning') or e.get('max_sample_distance_mm',0)>0.5:
                print('[SVG COMPARE] DIAG %s: %s %s max_distance=%s' % (
                    e['id'], e.get('error','').strip(), e.get('warning',''),
                    e.get('max_sample_distance_mm','n/a')))
    print('[SVG COMPARE] Full JSON report:', dest)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+')
    parser.add_argument('--freecad',action='store_true')
    parser.add_argument('--report',default='/tmp/marz-svg-compare.json')
    args=parser.parse_args()
    run(args.files,freecad=args.freecad,report=args.report)
