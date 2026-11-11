# SPDX-License-Identifier: GPL-3.0-or-later
"""SVG -> geometric primitives, independent of FreeCAD and Marz guitar semantics.

Coordinates are millimetres in the SVG drawing plane (SVG Y-down). The
Sketcher adapter controls the target coordinate frame; this reader never
flips or anchors geometry. Unsupported constructs fail explicitly.
"""
from dataclasses import dataclass, replace
from math import atan2, cos, sin, pi, radians, sqrt, hypot
import re
from xml.etree import ElementTree as ET

INKSCAPE_LABEL = '{http://www.inkscape.org/namespaces/inkscape}label'
SHAPES = {'path', 'line', 'polyline', 'polygon', 'rect', 'circle', 'ellipse'}
NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
NUMBER = re.compile(NUM)
PATH_TOKENS = re.compile(r'[MmZzLlHhVvCcSsQqTtAa]|' + NUM + r'|[^\s,]')
TRANSFORM_TOKENS = re.compile(r'([a-zA-Z]+)\s*\(([^)]*)\)')
UNITS = {'mm': 1., 'cm': 10., 'in': 25.4, 'pt': 25.4/72,
         'pc': 25.4/6, 'px': 25.4/96, 'q': .25}


class SVGReadError(ValueError):
    pass


@dataclass(frozen=True)
class Affine:
    a: float = 1.
    b: float = 0.
    c: float = 0.
    d: float = 1.
    e: float = 0.
    f: float = 0.

    def __matmul__(self, other):
        return Affine(self.a*other.a+self.c*other.b,
                      self.b*other.a+self.d*other.b,
                      self.a*other.c+self.c*other.d,
                      self.b*other.c+self.d*other.d,
                      self.a*other.e+self.c*other.f+self.e,
                      self.b*other.e+self.d*other.f+self.f)

    def point(self, p):
        x, y = p
        return (self.a*x+self.c*y+self.e, self.b*x+self.d*y+self.f)

    def vector(self, p):
        x, y = p
        return (self.a*x+self.c*y, self.b*x+self.d*y)

    @property
    def determinant(self):
        return self.a*self.d-self.b*self.c


@dataclass(frozen=True)
class Primitive:
    kind: str
    points: tuple = ()  # local points, 2D
    values: tuple = ()  # rx, ry, rotation, large-arc, sweep for arc; rx,ry for ellipse
    subpath: int = 0  # Preserve M/m boundaries within one SVG path
    closes_path: bool = False  # Explicit Z/z closure of the original path


@dataclass(frozen=True)
class Element:
    id: str
    label: str
    tag: str
    transform: Affine
    primitives: tuple
    group_ids: tuple = ()

    def name(self, recognizer):
        """Recognize semantic ID first, then authored Inkscape label."""
        if self.id and recognizer(self.id):
            return self.id
        if self.label and recognizer(self.label):
            return self.label
        return None


def _nums(value):
    leftover = NUMBER.sub('', value).replace(',', ' ').strip()
    if leftover:
        raise SVGReadError('Invalid number list: ' + value[:100])
    return [float(m.group()) for m in NUMBER.finditer(value)]


def length_mm(value):
    m = re.fullmatch(r'\s*(' + NUM + r')\s*([a-zA-Z]*)\s*', value or '')
    if not m or m.group(2).lower() not in UNITS:
        raise SVGReadError('Unsupported length: ' + str(value))
    return float(m.group(1))*UNITS[m.group(2).lower() or 'px']


def transform(value):
    result = Affine()
    for m in TRANSFORM_TOKENS.finditer(value or ''):
        v = _nums(m.group(2))
        kind = m.group(1).lower()
        if kind == 'matrix' and len(v) == 6:
            part = Affine(*v)
        elif kind == 'translate' and len(v) in (1, 2):
            part = Affine(e=v[0], f=v[1] if len(v) == 2 else 0)
        elif kind == 'scale' and len(v) in (1, 2):
            part = Affine(a=v[0], d=v[1] if len(v) == 2 else v[0])
        elif kind == 'rotate' and len(v) in (1, 3):
            s, c = sin(radians(v[0])), cos(radians(v[0]))
            rot = Affine(a=c, b=s, c=-s, d=c)
            part = (Affine(e=v[1], f=v[2]) @ rot @
                    Affine(e=-v[1], f=-v[2])) if len(v) == 3 else rot
        elif kind == 'skewx' and len(v) == 1:
            from math import tan
            part = Affine(c=tan(radians(v[0])))
        elif kind == 'skewy' and len(v) == 1:
            from math import tan
            part = Affine(b=tan(radians(v[0])))
        else:
            raise SVGReadError('Unsupported SVG transform: ' + m.group())
        result = result @ part
    if TRANSFORM_TOKENS.sub('', value or '').strip(' \t\r\n,'):
        raise SVGReadError('Invalid transform: ' + str(value))
    return result


def _arc_center(p0, p1, rx, ry, phi, large, sweep):
    """SVG endpoint-arc -> center, corrected radii, start/delta angles."""
    c, s = cos(phi), sin(phi)
    dx, dy = (p0[0]-p1[0])/2, (p0[1]-p1[1])/2
    xx, yy = c*dx+s*dy, -s*dx+c*dy
    ratio = (xx/rx)**2+(yy/ry)**2
    if ratio > 1:
        rx,ry=rx*sqrt(ratio),ry*sqrt(ratio)
    numerator=max(0., (rx*ry)**2-(rx*yy)**2-(ry*xx)**2)
    denominator=(rx*yy)**2+(ry*xx)**2
    if denominator==0:
        raise SVGReadError('Degenerate SVG elliptical arc')
    k=(-1. if large==sweep else 1.)*sqrt(numerator/denominator)
    cx,cy=k*rx*yy/ry,-k*ry*xx/rx
    center=((p0[0]+p1[0])/2+c*cx-s*cy,
            (p0[1]+p1[1])/2+s*cx+c*cy)
    a0=atan2((yy-cy)/ry,(xx-cx)/rx)
    ex,ey=(-xx-cx)/rx,(-yy-cy)/ry
    a1=atan2(ey,ex)
    delta=(a1-a0)%(2*pi)
    if not sweep and delta>0:delta-=2*pi
    return center,rx,ry,a0,delta


def parse_path(value):
    tokens = PATH_TOKENS.findall(value or '')
    out, i, cmd = [], 0, None
    p = (0., 0.)
    start = None
    prev_c = prev_q = None
    last_cmd = None
    subpath = -1

    def emit(kind, points, values=()):
        out.append(Primitive(kind, points, values, subpath))

    sizes = {'M':2,'L':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'T':2,'A':7}

    def consume(n):
        nonlocal i
        if i+n > len(tokens):
            raise SVGReadError('Truncated SVG path command ' + str(cmd))
        t = tokens[i:i+n]
        if any(not NUMBER.fullmatch(x) for x in t):
            raise SVGReadError('Invalid path parameters: ' + str(t))
        i += n
        return [float(x) for x in t]

    while i < len(tokens):
        if len(tokens[i]) == 1 and tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in 'Zz':
                if start is None:
                    raise SVGReadError('Close before move')
                if abs(p[0]-start[0])+abs(p[1]-start[1]) > 1e-12:
                    emit('line', (p, start))
                if out and out[-1].subpath == subpath:
                    out[-1] = replace(out[-1], closes_path=True)
                p = start
                prev_c = prev_q = None
                last_cmd = 'Z'
                cmd = None
                continue
            if cmd.upper() not in sizes:
                raise SVGReadError('Unsupported path command ' + cmd)
        if cmd is None:
            raise SVGReadError('Path parameter without command')
        k = cmd.upper()
        v = consume(sizes[k])
        relative = cmd.islower()

        def dest(x, y):
            return (p[0]+x, p[1]+y) if relative else (x, y)

        if k == 'M':
            subpath += 1
            p = dest(*v)
            start = p
            cmd = 'l' if relative else 'L'
        elif k in ('L','H','V'):
            target = (dest(*v) if k == 'L' else
                      (p[0]+v[0] if relative else v[0], p[1]) if k == 'H' else
                      (p[0], p[1]+v[0] if relative else v[0]))
            if p != target:
                emit('line', (p, target))
            p = target
        elif k in ('C','S'):
            if k == 'C':
                first = dest(v[0],v[1]); second = dest(v[2],v[3]); target = dest(v[4],v[5])
            else:
                first = (2*p[0]-prev_c[0], 2*p[1]-prev_c[1]) if last_cmd in ('C','S') and prev_c else p
                second = dest(v[0],v[1]); target = dest(v[2],v[3])
            emit('cubic', (p,first,second,target))
            p = target
            prev_c = second
        elif k in ('Q','T'):
            if k == 'Q':
                control = dest(v[0],v[1]); target = dest(v[2],v[3])
            else:
                control = (2*p[0]-prev_q[0], 2*p[1]-prev_q[1]) if last_cmd in ('Q','T') and prev_q else p
                target = dest(*v)
            emit('quadratic', (p,control,target))
            p = target
            prev_q = control
        else:  # A: SVG elliptical arc, retain exact endpoint parametrization
            rx,ry,angle,large,sweep,x,y = v
            if large not in (0,1) or sweep not in (0,1):
                raise SVGReadError('Invalid SVG arc flags')
            target = dest(x,y)
            if p != target:
                emit('arc' if rx and ry else 'line', (p,target),
                     (abs(rx),abs(ry),angle,int(large),int(sweep)))
            p = target
        if k not in ('C','S'):
            prev_c = None
        if k not in ('Q','T'):
            prev_q = None
        last_cmd = k
    return tuple(out)


def _affine_max_stretch(matrix):
    """Largest linear stretch of an affine transform."""
    trace = matrix.a*matrix.a + matrix.b*matrix.b + matrix.c*matrix.c + matrix.d*matrix.d
    determinant = matrix.determinant
    disc = max(0., trace*trace - 4*determinant*determinant)
    return sqrt(max(0., (trace + sqrt(disc))/2))


def _cubic_point(points, t):
    p0,p1,p2,p3=points
    u=1.-t
    return (u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
            u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1])


def _recognize_full_cubic_circular_subpaths(parts, matrix):
    """Recover circles serialized as four cubic Bezier spans.

    This deliberately mirrors Marz's established pocket-circle recovery:
    sample the actual curves, derive center/radius from sampled extents, and
    require every sample to lie within 0.01 mm of that circle.  The check is
    done before the affine SVG transform, with the tolerance tightened by the
    transform's maximum stretch so the final drawing-space error cannot exceed
    the established 0.01 mm criterion.
    """
    result=[]
    stretch=_affine_max_stretch(matrix)
    if stretch<=1e-15:
        return parts
    tolerance=0.01/stretch
    i=0
    while i<len(parts):
        j=i+1
        while j<len(parts) and parts[j].subpath==parts[i].subpath:
            j+=1
        section=parts[i:j]
        i=j
        if (len(section)!=4 or not section[-1].closes_path or
                any(p.kind!='cubic' for p in section)):
            result.extend(section)
            continue
        if hypot(section[0].points[0][0]-section[-1].points[-1][0],
                 section[0].points[0][1]-section[-1].points[-1][1])>1e-8:
            result.extend(section)
            continue
        sampled=[_cubic_point(part.points,k/64.)
                 for part in section for k in range(65)]
        xs=[p[0] for p in sampled]; ys=[p[1] for p in sampled]
        xmin,xmax,ymin,ymax=min(xs),max(xs),min(ys),max(ys)
        if min(xmax-xmin,ymax-ymin)<=1e-12:
            result.extend(section)
            continue
        cx,cy=(xmin+xmax)/2.,(ymin+ymax)/2.
        radius=(xmax-xmin+ymax-ymin)/4.
        if all(abs(hypot(x-cx,y-cy)-radius)<=tolerance for x,y in sampled):
            result.append(Primitive('circle',((cx,cy),),(radius,radius),
                                    section[0].subpath,closes_path=True))
        else:
            result.extend(section)
    return tuple(result)


def _recognize_full_circular_subpaths(parts):
    """Preserve complete circular SVG paths as one native circle primitive.

    Inkscape may serialize a single circle as four SVG arcs. Importing these
    as independent Sketcher arcs and constraining their joins gives Sketcher
    needless degrees of freedom and can collapse the original circle. Accept
    consolidation only if the authored arc pieces share one circle to within
    0.00001 original SVG coordinate units. Geometry is not approximated
    when the authored arcs differ materially.
    """
    result=[]
    i=0
    while i<len(parts):
        j=i+1
        while j<len(parts) and parts[j].subpath==parts[i].subpath:
            j+=1
        section=parts[i:j]
        i=j
        if (len(section)<2 or not section[-1].closes_path or
                any(p.kind!='arc' for p in section)):
            result.extend(section)
            continue
        try:
            centers=[]
            radii=[]
            sweeps=[]
            sampled=[]
            for part in section:
                rx,ry,rot,large,sweep=part.values
                if abs(rx-ry)>1e-7*max(rx,ry):
                    break
                phi=radians(rot)
                center,rx,ry,start,delta=_arc_center(
                    *part.points,rx,ry,phi,large,sweep)
                centers.append(center)
                radii.append(rx)
                sweeps.append(delta)
                for t in (0.,.25,.5,.75,1.):
                    angle=start+t*delta
                    sampled.append((center[0]+rx*cos(angle),
                                    center[1]+rx*sin(angle)))
            else:
                cx=sum(p[0] for p in centers)/len(centers)
                cy=sum(p[1] for p in centers)/len(centers)
                radius=sum(radii)/len(radii)
                # The SVG path must traverse exactly one complete revolution.
                # Preserve incomplete circles and arcs with mixed directions.
                if (abs(abs(sum(sweeps))-2*pi)<1e-3 and
                        all(d*sum(sweeps)>0 for d in sweeps) and
                        hypot(*(a-b for a,b in zip(section[0].points[0],
                                                   section[-1].points[-1])))<1e-6 and
                        max(abs(hypot(x-cx,y-cy)-radius)
                            for x,y in sampled)<1e-5):
                    result.append(Primitive('circle',((cx,cy),),
                                            (radius,radius),section[0].subpath,
                                            closes_path=True))
                    continue
        except (SVGReadError, ZeroDivisionError, ValueError):
            pass
        result.extend(section)
    return tuple(result)


def _shape(tag, attrs, matrix=Affine()):
    g = lambda key: float(attrs.get(key, 0))
    if tag == 'path':
        parts=_recognize_full_circular_subpaths(parse_path(attrs.get('d','')))
        return _recognize_full_cubic_circular_subpaths(parts,matrix)
    if tag in ('polyline','polygon'):
        p = list(zip(*[iter(_nums(attrs.get('points','')))]*2))
        if tag == 'polygon' and p and p[-1] != p[0]:
            p.append(p[0])
        parts=tuple(Primitive('line',(a,b)) for a,b in zip(p,p[1:]) if a!=b)
        return (parts[:-1]+(replace(parts[-1],closes_path=True),)
                if len(parts)>1 and p[0]==p[-1] else parts)
    if tag == 'line':
        p=((g('x1'),g('y1')),(g('x2'),g('y2')))
        return (Primitive('line',p),) if p[0]!=p[1] else ()
    if tag in ('circle','ellipse'):
        rx=g('r') if tag=='circle' else g('rx'); ry=rx if tag=='circle' else g('ry')
        if rx<=0 or ry<=0:
            return ()
        return (Primitive(tag, ((g('cx'),g('cy')),), (rx,ry)),)
    if tag=='rect':
        x,y,w,h = g('x'),g('y'),g('width'),g('height')
        if w<=0 or h<=0:
            return ()
        if g('rx') or g('ry'):
            rx=min(g('rx') or g('ry'),w/2)
            ry=min(g('ry') or g('rx'),h/2)
            return (
                Primitive('line', ((x+rx,y),(x+w-rx,y))),
                Primitive('arc', ((x+w-rx,y),(x+w,y+ry)),(rx,ry,0,0,1)),
                Primitive('line', ((x+w,y+ry),(x+w,y+h-ry))),
                Primitive('arc', ((x+w,y+h-ry),(x+w-rx,y+h)),(rx,ry,0,0,1)),
                Primitive('line', ((x+w-rx,y+h),(x+rx,y+h))),
                Primitive('arc', ((x+rx,y+h),(x,y+h-ry)),(rx,ry,0,0,1)),
                Primitive('line', ((x,y+h-ry),(x,y+ry))),
                Primitive('arc', ((x,y+ry),(x+rx,y)),(rx,ry,0,0,1), closes_path=True))
        corners=[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]
        parts=tuple(Primitive('line',(a,b)) for a,b in zip(corners,corners[1:]))
        return parts[:-1]+(replace(parts[-1],closes_path=True),)
    return ()


def read_svg(filename):
    root = ET.parse(filename).getroot()
    if root.tag.rsplit('}',1)[-1] != 'svg':
        raise SVGReadError('Not an SVG document')
    vb = _nums(root.get('viewBox',''))
    if len(vb)==4:
        x,y,w,h=vb
        if w<=0 or h<=0:
            raise SVGReadError('Invalid SVG viewBox')
        width=length_mm(root.get('width',str(w)+'px'))
        height=length_mm(root.get('height',str(h)+'px'))
        # SVG defaults to xMidYMid meet, unlike naive independent x/y scaling.
        preserve=root.get('preserveAspectRatio','xMidYMid meet')
        if preserve.strip() == 'none':
            sx,sy=width/w,height/h
            root_transform=Affine(a=sx,d=sy,e=-x*sx,f=-y*sy)
        else:
            opts=preserve.split()
            align=next((v for v in opts if v.startswith('x') and 'Y' in v),'xMidYMid')
            mode='slice' if 'slice' in opts else 'meet'
            scale=(max if mode=='slice' else min)(width/w,height/h)
            ox=(0 if align.startswith('xMin') else width-w*scale if align.startswith('xMax') else (width-w*scale)/2)
            oy=(0 if 'YMin' in align else height-h*scale if 'YMax' in align else (height-h*scale)/2)
            root_transform=Affine(a=scale,d=scale,e=ox-x*scale,f=oy-y*scale)
    else:
        root_transform=Affine(a=25.4/96,d=25.4/96)

    out=[]
    def walk(node, parent, groups, hidden=False):
        tag=node.tag.rsplit('}',1)[-1]
        # Ignore non-rendered definitions, guides, text, clips, and hidden groups.
        if tag in ('defs','clipPath','mask','pattern','marker','symbol','metadata','namedview','text','tspan'):
            return
        style=node.get('style','')
        hidden=hidden or node.get('display')=='none' or bool(re.search(r'(^|;)\s*display\s*:\s*none',style))
        if hidden:
            return
        matrix=parent @ transform(node.get('transform',''))
        if tag in SHAPES:
            parts=_shape(tag,node.attrib,matrix)
            if parts:
                out.append(Element(node.get('id',''),node.get(INKSCAPE_LABEL,''),tag,
                                   matrix,parts,groups))
        elif tag in ('use','foreignObject'):
            raise SVGReadError('Unsupported rendered SVG object %s (%s)' %
                               (tag,node.get('id','')))
        elif tag not in ('svg','g','a','switch'):
            # Raster images and non-geometric metadata are not Sketcher sources.
            return
        next_groups=groups+((node.get('id',''),) if tag=='g' else ())
        for child in node:
            walk(child,matrix,next_groups,hidden)
    walk(root,root_transform,())
    return tuple(out)
