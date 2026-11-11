# SPDX-License-Identifier: GPL-3.0-or-later
"""Marz semantic names carried by SVG ``id`` / Inkscape ``label`` values.

This module is deliberately independent of FreeCAD and SVG geometry.  The
SVG reader preserves authored metadata; this layer interprets only the Marz
naming grammar.  Consumers decide how parsed values affect guitar geometry.
"""
from dataclasses import dataclass
import re
from typing import Callable, Generic, Optional, TypeVar


_NUMBER = r'\d+(?:[pP\.]\d+)?'
_NUMBER_RE = re.compile(r'^' + _NUMBER + r'$')
_VALUE_OFFSET_RE = re.compile(
    r'^(?P<value>' + _NUMBER + r')(?:(?P<sign>[aAsS+\-])(?P<offset>' + _NUMBER + r'))?$')
_FRET_HEAD_RE = re.compile(r'^[fF](?P<fret>' + _NUMBER + r')(?P<rest>.*)$')
_POCKET_HEAD_RE = re.compile(r'^[hH](?P<target>[tTbB]?)(?P<index>\d+)(?P<rest>.*)$')
_LEGACY_POCKET_RE = re.compile(
    r'^[hH](?P<target>[tTbB]?)(?P<index>\d+)_(?P<start>\d+)_(?P<depth>\d+)'
    r'(?:(?:_\d+)?_w\d*)?$')
_WIRE_SUFFIX_RE = re.compile(r'(?:(?:_\d+)?_w\d*)$', re.I)


class SemanticSyntaxError(ValueError):
    """A name looks like Marz semantics, but its semantic fields are invalid."""

    def __init__(self, text: str, reason: str):
        self.text = text
        self.reason = reason
        super().__init__(f'{text}: {reason}')


@dataclass(frozen=True)
class AxisValue:
    """Normalized X/Y box alignment followed by a physical mm offset."""
    alignment: float
    offset: float = 0.0

    def display(self) -> str:
        return _format_number(self.alignment) + _format_offset(self.offset)


@dataclass(frozen=True)
class PositionValue:
    """A Z position expression: base value plus an optional signed mm offset."""
    base: float
    offset: float = 0.0

    @property
    def value(self) -> float:
        return self.base + self.offset

    def display(self) -> str:
        return _format_number(self.base) + _format_offset(self.offset)


@dataclass(frozen=True)
class FretSemantic:
    raw: str
    fret: float
    x: AxisValue = AxisValue(0.5, 0.0)
    y: AxisValue = AxisValue(0.5, 0.0)
    suffixes: tuple[str, ...] = ()
    prefix: str = 'f'
    compact: bool = False

    @property
    def placement_key(self):
        """Logical standalone-inlay grouping key (suffixes are non-semantic)."""
        return (self.fret, self.x.alignment, self.x.offset,
                self.y.alignment, self.y.offset)


@dataclass(frozen=True)
class PocketSemantic:
    raw: str
    index: int
    target: str
    start: float
    end: float
    suffixes: tuple[str, ...] = ()
    legacy: bool = False
    start_expression: Optional[PositionValue] = None
    end_expression: Optional[PositionValue] = None

    @property
    def depth(self) -> float:
        return self.end - self.start


T = TypeVar('T')


@dataclass(frozen=True)
class ResolvedSemantic(Generic[T]):
    source: str  # ``id`` or ``label``
    text: str
    value: T


def _number(text: str) -> float:
    if not _NUMBER_RE.fullmatch(text):
        raise ValueError(text)
    return float(re.sub('[pP]', '.', text))


def _format_number(value: float) -> str:
    if abs(value) < 5e-13:
        value = 0.0
    return format(value, '.12g')


def _format_offset(value: float) -> str:
    if abs(value) < 5e-13:
        return ''
    return ('+' if value > 0 else '-') + _format_number(abs(value))


def _parse_value_offset(text: str, *, normalized=False, raw=''):
    match = _VALUE_OFFSET_RE.fullmatch(text)
    if not match:
        raise SemanticSyntaxError(raw or text, 'invalid numeric modifier')
    value = _number(match.group('value'))
    sign = match.group('sign')
    offset = _number(match.group('offset')) if match.group('offset') else 0.0
    if sign in ('s', 'S', '-'):
        offset = -offset
    if normalized and not (0.0 <= value <= 1.0):
        raise SemanticSyntaxError(raw or text, 'normalized alignment must be between 0 and 1')
    return value, offset


def _modifier_intent(token: str, axis: str) -> bool:
    """Distinguish malformed semantic tokens from arbitrary words like xaviar."""
    if not token or token[0].lower() != axis:
        return False
    tail = token[1:]
    if not tail:
        return True
    # A modifier value starts numerically.  This deliberately leaves words
    # such as `xaviar`, `apple`, or `zebra` as arbitrary suffixes.
    return tail[0].isdigit() or tail[0] == '.'


def _parse_axis_token(token: str, axis: str, raw: str) -> Optional[AxisValue]:
    if not token or token[0].lower() != axis:
        return None
    try:
        alignment, offset = _parse_value_offset(token[1:], normalized=True, raw=raw)
    except SemanticSyntaxError:
        if _modifier_intent(token, axis):
            raise SemanticSyntaxError(raw, f'invalid {axis.upper()} modifier {token!r}')
        return None
    return AxisValue(alignment, offset)


def _parse_position_token(token: str, raw: str) -> Optional[PositionValue]:
    if not token or token[0].lower() != 'z':
        return None
    try:
        base, offset = _parse_value_offset(token[1:], raw=raw)
    except SemanticSyntaxError:
        if _modifier_intent(token, 'z'):
            raise SemanticSyntaxError(raw, f'invalid Z modifier {token!r}')
        return None
    return PositionValue(base, offset)


def _parse_compact_inlay(text: str) -> Optional[FretSemantic]:
    """Parse the historical compact D13X0.25+2Y1.0-2.5 spelling."""
    head = re.match(r'^[dD](\d+)', text)
    if not head:
        return None
    fret = float(int(head.group(1)))
    pos = head.end()
    axes = {}
    while pos < len(text):
        axis = text[pos].lower()
        if axis not in ('x', 'y'):
            raise SemanticSyntaxError(text, 'invalid compact inlay modifier')
        pos += 1
        match = re.match(_NUMBER + r'(?:[aAsS+\-]' + _NUMBER + r')?', text[pos:])
        if not match:
            raise SemanticSyntaxError(text, f'invalid compact {axis.upper()} modifier')
        expression = match.group(0)
        alignment, offset = _parse_value_offset(expression, normalized=True, raw=text)
        if axis in axes:
            raise SemanticSyntaxError(text, f'duplicate {axis.upper()} modifier')
        axes[axis] = AxisValue(alignment, offset)
        pos += len(expression)
    if not axes:
        raise SemanticSyntaxError(text, 'compact D inlay requires X and/or Y modifier')
    return FretSemantic(text, fret, axes.get('x', AxisValue(0.5)),
                        axes.get('y', AxisValue(0.5)), prefix='d', compact=True)


def parse_fret_semantic(text: str, *, allow_fractional=True,
                        allow_xy=True, allow_compact=True) -> Optional[FretSemantic]:
    """Parse an F-prefixed semantic name, or the compact D inlay form.

    Underscore-delimited X/Y tokens are recognized only when the complete token
    matches.  Other tokens remain descriptive suffixes.  Tokens that clearly
    attempt X/Y syntax but are malformed raise :class:`SemanticSyntaxError`.
    """
    if not isinstance(text, str) or not text:
        return None
    if allow_compact and text[:1].lower() == 'd':
        return _parse_compact_inlay(text)
    match = _FRET_HEAD_RE.match(text)
    if not match:
        return None
    fret_text = match.group('fret')
    fret = _number(fret_text)
    if not allow_fractional and not fret.is_integer():
        raise SemanticSyntaxError(text, 'fractional fret position is not valid here')
    rest = match.group('rest')
    if rest and not rest.startswith('_'):
        # This is intentionally a semantic-looking error rather than silently
        # consuming text directly after the fret number.
        raise SemanticSyntaxError(text, 'suffix/modifier tokens must be underscore-delimited')
    tokens = rest[1:].split('_') if rest.startswith('_') else []
    axes = {}
    suffixes = []
    for token in tokens:
        if allow_xy:
            parsed = None
            for axis in ('x', 'y'):
                candidate = _parse_axis_token(token, axis, text)
                if candidate is not None:
                    parsed = (axis, candidate)
                    break
            if parsed:
                axis, value = parsed
                if axis in axes:
                    raise SemanticSyntaxError(text, f'duplicate {axis.upper()} modifier')
                axes[axis] = value
                continue
        suffixes.append(token)
    return FretSemantic(text, fret, axes.get('x', AxisValue(0.5)),
                        axes.get('y', AxisValue(0.5)), tuple(suffixes))


def parse_inlay_semantic(text: str) -> Optional[FretSemantic]:
    """Parse inlay semantics: integer F fret-space or compact D form."""
    return parse_fret_semantic(text, allow_fractional=False,
                               allow_xy=True, allow_compact=True)


def parse_neck_semantic(text: str) -> Optional[FretSemantic]:
    """Parse Neck section semantics, including fractional F positions."""
    return parse_fret_semantic(text, allow_fractional=True,
                               allow_xy=False, allow_compact=False)


def parse_pocket_semantic(text: str) -> Optional[PocketSemantic]:
    """Parse legacy start/depth pocket names or the new two-Z start/end form."""
    if not isinstance(text, str) or not text:
        return None
    legacy = _LEGACY_POCKET_RE.fullmatch(text)
    if legacy:
        start = int(legacy.group('start')) / 100.0
        depth = int(legacy.group('depth')) / 100.0
        return PocketSemantic(text, int(legacy.group('index')),
                              legacy.group('target').lower(), start,
                              start + depth, legacy=True)
    head = _POCKET_HEAD_RE.match(text)
    if not head:
        return None
    rest = head.group('rest')
    if not rest.startswith('_'):
        # hFoo / hx... are not pocket semantics; preserve them as unrelated IDs.
        return None
    tokens = rest[1:].split('_')
    z_values = []
    suffixes = []
    for token in tokens:
        position = _parse_position_token(token, text)
        if position is not None:
            z_values.append(position)
        else:
            suffixes.append(token)
    if not z_values:
        return None
    if len(z_values) != 2:
        raise SemanticSyntaxError(text, 'pocket Z syntax requires exactly two Z tokens')
    return PocketSemantic(text, int(head.group('index')),
                          head.group('target').lower(), z_values[0].value,
                          z_values[1].value, tuple(suffixes), False,
                          z_values[0], z_values[1])


def resolve_semantic(element_id: str, label: str,
                     parser: Callable[[str], Optional[T]]) -> Optional[ResolvedSemantic[T]]:
    """Resolve a semantic value with first-valid ID / label fallback.

    A malformed semantic-looking ID does not hide a valid authored label.  If
    neither source parses and at least one was malformed, re-raise the first
    semantic error so callers can display a useful validation message.
    """
    errors = []
    for source, text in (('id', element_id), ('label', label)):
        if not text:
            continue
        try:
            value = parser(text)
        except SemanticSyntaxError as exc:
            errors.append(exc)
            continue
        if value is not None:
            return ResolvedSemantic(source, text, value)
    if errors:
        raise errors[0]
    return None


def resolve_inlay(element_id: str, label: str = ''):
    return resolve_semantic(element_id, label, parse_inlay_semantic)


def resolve_neck(element_id: str, label: str = ''):
    return resolve_semantic(element_id, label, parse_neck_semantic)


def resolve_pocket(element_id: str, label: str = ''):
    return resolve_semantic(element_id, label, parse_pocket_semantic)
