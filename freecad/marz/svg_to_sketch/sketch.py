# SPDX-License-Identifier: GPL-3.0-or-later
"""Native FreeCAD Sketcher adapter for the independent SVG primitive model.

Does not import Marz or FreeCAD until called. Each SVG object remains a
separate, provenance-preserving Sketcher object for side-by-side comparison.
Marz placement/semantic interpretation belongs to future integration stages.
"""
import json
from math import atan2, cos, sin, sqrt, radians, pi, hypot
from .reader import Affine, SVGReadError


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


def _axes(center, ux, uy, matrix):
    """Find major/minor axes of transformed conic, including skew and reflection."""
    U,V=matrix.vector(ux),matrix.vector(uy)
    qxx=U[0]*U[0]+V[0]*V[0]
    qxy=U[0]*U[1]+V[0]*V[1]
    qyy=U[1]*U[1]+V[1]*V[1]
    radius=sqrt((qxx-qyy)**2+4*qxy*qxy)
    major=sqrt(max(0,(qxx+qyy+radius)/2))
    minor=sqrt(max(0,(qxx+qyy-radius)/2))
    if minor<1e-10:
        raise SVGReadError('SVG transform collapses an ellipse')
    angle=atan2(2*qxy,qxx-qyy)/2
    if qxx+qyy and radius<1e-12*(qxx+qyy):
        # Circular conics are rotation invariant, use the actual first axis.
        angle=atan2(U[1],U[0])
    center=matrix.point(center)
    axis1=(major*cos(angle),major*sin(angle))
    axis2=(-minor*sin(angle),minor*cos(angle))
    return center,axis1,axis2


def _point_on_arc(center,rx,ry,phi,angle):
    u,v=rx*cos(angle),ry*sin(angle)
    return (center[0]+cos(phi)*u-sin(phi)*v,
            center[1]+sin(phi)*u+cos(phi)*v)


def geometry_for_element(element, *, y_up=True):
    """Return native Part geometry while retaining original SVG primitive types.

    No sketch is created or modified by this function. A single file/element
    may contain multiple independent subpaths.
    """
    import FreeCAD as App
    import Part
    m=(Affine(d=-1) @ element.transform) if y_up else element.transform
    def V(p):
        x,y=m.point(p)
        return App.Vector(x,y,0)
    result=[]
    for primitive in element.primitives:
        kind=primitive.kind
        pts=primitive.points
        if kind=='line':
            result.append(Part.LineSegment(V(pts[0]),V(pts[1])))
        elif kind in ('cubic','quadratic'):
            poles=[V(p) for p in pts]
            degree=3 if kind=='cubic' else 2
            bs=Part.BSplineCurve()
            bs.buildFromPolesMultsKnots(poles,[degree+1,degree+1],
                                        [0.,1.],False,degree)
            result.append(bs)
        elif kind in ('circle','ellipse'):
            rx,ry=primitive.values
            c,u,w=_axes(pts[0],(rx,0.),(0.,ry),m)
            C=App.Vector(*c,0); a=App.Vector(c[0]+u[0],c[1]+u[1],0)
            b=App.Vector(c[0]+w[0],c[1]+w[1],0)
            if abs(hypot(*u)-hypot(*w)) < 1e-9:
                result.append(Part.Circle(C,App.Vector(0,0,1),hypot(*u)))
            else:
                result.append(Part.Ellipse(a,b,C))
        elif kind=='arc':
            rx,ry,rotation,large,sweep=primitive.values
            phi=radians(rotation)
            center,rx,ry,start,delta=_arc_center(pts[0],pts[1],rx,ry,phi,large,sweep)
            axes=_axes(center,(rx*cos(phi),rx*sin(phi)),
                       (-ry*sin(phi),ry*cos(phi)),m)
            c,u,w=axes
            C=App.Vector(*c,0)
            maj=App.Vector(c[0]+u[0],c[1]+u[1],0)
            minor=App.Vector(c[0]+w[0],c[1]+w[1],0)
            r1,r2=hypot(*u),hypot(*w)
            if abs(r1-r2)<1e-9:
                # Three authored points define the exact circular arc, with
                # the middle point also resolving the sweep direction.
                first=_point_on_arc(center,rx,ry,phi,start)
                middle=_point_on_arc(center,rx,ry,phi,start+delta/2)
                last=_point_on_arc(center,rx,ry,phi,start+delta)
                result.append(Part.Arc(V(first),V(middle),V(last)))
            else:
                first,middle,last=(_point_on_arc(center,rx,ry,phi,start+t*delta)
                                   for t in (0,.5,1))
                def param(p):
                    q=m.point(p)
                    dx,dy=q[0]-c[0],q[1]-c[1]
                    return atan2((dx*w[0]+dy*w[1])/(r2*r2),
                                 (dx*u[0]+dy*u[1])/(r1*r1))
                t0,tm,t1=param(first),param(middle),param(last)
                # Choose the positive arc span which passes through midpoint.
                sweep01=(t1-t0)%(2*pi)
                if (tm-t0)%(2*pi)>sweep01+1e-6:
                    t0,t1=t1,t0
                    sweep01=(t1-t0)%(2*pi)
                ellipse=Part.Ellipse(maj,minor,C)
                result.append(Part.ArcOfEllipse(ellipse,t0,t0+sweep01))
        else:
            raise SVGReadError('Unknown primitive kind '+kind)
    return result


def _source_endpoint_joins(geometry, tolerance=1e-7):
    """Constrain only genuinely shared endpoints (no forced snapping).

    FreeCAD owns the native curve orientation; read its actual Start/EndPoint
    rather than assuming imported SVG arc directions are preserved.
    """
    endpoints=[]
    for idx,g in enumerate(geometry):
        if type(g).__name__ in ('Circle','Ellipse'):
            continue
        start,end=getattr(g,'StartPoint',None),getattr(g,'EndPoint',None)
        if start is not None and end is not None:
            endpoints.extend(((start,idx,1),(end,idx,2)))
    clusters=[]
    for item in endpoints:
        point=item[0]
        for group in clusters:
            q=group[0][0]
            if ((point.x-q.x)**2+(point.y-q.y)**2+
                    (point.z-q.z)**2) <= tolerance*tolerance:
                group.append(item)
                break
        else:
            clusters.append([item])
    result=[]
    for group in clusters:
        first=group[0]
        for item in group[1:]:
            if item[1]!=first[1]:
                result.append((first[1],first[2],item[1],item[2]))
    return result


def create_sketch(doc, element, name, *, y_up=True, connect_endpoints=True):
    """Create an independent native editable Sketcher source for comparison.

    Caller owns document, placement and lifecycle. This does not change the
    production Marz importer or any existing Sketcher object.
    Set connect_endpoints=False to measure geometry before the Sketcher solver
    applies Coincident constraints (diagnostic comparison only).
    """
    geometry=geometry_for_element(element,y_up=y_up)
    sketch=doc.addObject('Sketcher::SketchObject',name)
    sketch.addGeometry(geometry,False)
    joins=_source_endpoint_joins(geometry) if connect_endpoints else ()
    if joins:
        from Sketcher import Constraint
        sketch.addConstraint([Constraint('Coincident',*join) for join in joins])
    sketch.addProperty('App::PropertyString','SVGSourceID','SVG source')
    sketch.addProperty('App::PropertyString','SVGSourceLabel','SVG source')
    sketch.addProperty('App::PropertyString','SVGElementMap','SVG source')
    sketch.SVGSourceID=element.id
    sketch.SVGSourceLabel=element.label
    sketch.SVGElementMap=json.dumps({'version':1,'elements':[
        {'id':element.id,'label':element.label,'indices':list(range(len(geometry)))}]})
    return sketch
