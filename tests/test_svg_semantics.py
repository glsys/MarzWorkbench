# SPDX-License-Identifier: GPL-3.0-or-later
"""FreeCAD-independent contract tests for Marz SVG semantic names."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freecad.marz.svg_semantics import (
    AxisValue, SemanticSyntaxError, parse_inlay_semantic, parse_neck_semantic,
    parse_pocket_semantic, resolve_inlay, resolve_neck, resolve_pocket)


class FretSemanticTests(unittest.TestCase):
    def test_all_documented_token_and_suffix_examples(self):
        examples = (
            'f12_x0p0a0_y0p0a0p0_apple',
            'f12_y0p0a0p0_x0p0a0_xaviar',
            'f12_y0p0a0p0_x0p0a0_',
            'f12_y0p0a0p0_x0p0a0',
            'f12_y0p0a0p0_',
            'f12_y0p0a0p0',
            'f12_',
            'f12',
        )
        for text in examples:
            with self.subTest(text=text):
                parsed = parse_inlay_semantic(text)
                self.assertEqual(parsed.fret, 12)
        parsed = parse_inlay_semantic(examples[1])
        self.assertIn('xaviar', parsed.suffixes)
        self.assertEqual(parsed.x, AxisValue(0, 0))
        self.assertEqual(parsed.y, AxisValue(0, 0))

    def test_xy_order_case_decimal_and_sign_aliases(self):
        variants = (
            'f13_x0p25a2p5_y1s2p5',
            'F13_Y1S2P5_X0P25A2P5',
            'f13_y1-2.5_x0.25+2.5',
        )
        expected = None
        for text in variants:
            parsed = parse_inlay_semantic(text)
            current = (parsed.fret, parsed.x, parsed.y)
            expected = expected or current
            self.assertEqual(current, expected)
        self.assertEqual(expected[1], AxisValue(.25, 2.5))
        self.assertEqual(expected[2], AxisValue(1, -2.5))

    def test_missing_axes_default_to_center_and_display_compactly(self):
        centered = parse_inlay_semantic('f13_')
        self.assertEqual(centered.x, AxisValue(.5, 0))
        self.assertEqual(centered.y, AxisValue(.5, 0))
        self.assertEqual(centered.x.display(), '0.5')
        self.assertEqual(AxisValue(0, 2).display(), '0+2')
        self.assertEqual(AxisValue(.5, -4).display(), '0.5-4')

    def test_compact_legacy_d_form(self):
        parsed = parse_inlay_semantic('D13X0.25+2Y1.0-2.5')
        self.assertEqual(parsed.fret, 13)
        self.assertEqual(parsed.x, AxisValue(.25, 2))
        self.assertEqual(parsed.y, AxisValue(1, -2.5))
        self.assertTrue(parsed.compact)
        self.assertEqual(parsed.prefix, 'd')

    def test_fractional_neck_positions_use_same_numeric_aliases(self):
        for text, expected in (('f5p5_', 5.5), ('F5P75_profile', 5.75),
                               ('f10.25', 10.25), ('f10p25', 10.25),
                               ('f0_', 0), ('f20_', 20)):
            with self.subTest(text=text):
                self.assertEqual(parse_neck_semantic(text).fret, expected)
        with self.assertRaises(SemanticSyntaxError):
            parse_inlay_semantic('f5p5_')

    def test_malformed_modifier_errors_but_free_text_does_not(self):
        parsed = parse_inlay_semantic('f12_xaviar_apple')
        self.assertEqual(parsed.suffixes, ('xaviar', 'apple'))
        with self.assertRaises(SemanticSyntaxError):
            parse_inlay_semantic('f12_x0p')
        with self.assertRaises(SemanticSyntaxError):
            parse_inlay_semantic('f12_x1p1')
        with self.assertRaises(SemanticSyntaxError):
            parse_inlay_semantic('f12_x0_x1')

    def test_id_first_then_label_fallback(self):
        resolved = resolve_inlay('f13_x0', 'f15_y1')
        self.assertEqual((resolved.source, resolved.value.fret), ('id', 13))
        resolved = resolve_inlay('positioned', 'f13_x0a2p0_y1s2p5_part2')
        self.assertEqual(resolved.source, 'label')
        self.assertEqual(resolved.value.x, AxisValue(0, 2))
        self.assertEqual(resolved.value.y, AxisValue(1, -2.5))
        # A malformed semantic ID must not hide a valid authored label.
        resolved = resolve_inlay('f13_x0p', 'f13_')
        self.assertEqual(resolved.source, 'label')
        with self.assertRaises(SemanticSyntaxError):
            resolve_inlay('f13_x0p', '')

    def test_fixture_neck_label_fallback(self):
        resolved = resolve_neck('zehn', 'f10p25')
        self.assertEqual(resolved.source, 'label')
        self.assertEqual(resolved.value.fret, 10.25)


class PocketSemanticTests(unittest.TestCase):
    def test_legacy_start_depth_is_preserved(self):
        parsed = parse_pocket_semantic('hb1_0_2000')
        self.assertTrue(parsed.legacy)
        self.assertEqual(parsed.target, 'b')
        self.assertEqual(parsed.index, 1)
        self.assertEqual(parsed.start, 0)
        self.assertEqual(parsed.depth, 20)
        self.assertEqual(parsed.end, 20)
        self.assertEqual(parse_pocket_semantic('H4_25_50').start, .25)
        self.assertEqual(parse_pocket_semantic('H4_25_50').depth, .5)

    def test_new_z_start_end_not_start_depth(self):
        parsed = parse_pocket_semantic('ht1_z0.0_z0.0+0.5')
        self.assertFalse(parsed.legacy)
        self.assertEqual(parsed.target, 't')
        self.assertEqual((parsed.start, parsed.end, parsed.depth), (0, .5, .5))
        parsed = parse_pocket_semantic('h3_z0p0_z1p0')
        self.assertEqual((parsed.start, parsed.end, parsed.depth), (0, 1, 1))
        parsed = parse_pocket_semantic('h2_z0_z0a0p5')
        self.assertEqual((parsed.start, parsed.end), (0, .5))
        self.assertEqual(parsed.end_expression.display(), '0+0.5')

    def test_new_z_case_aliases_and_suffixes(self):
        a = parse_pocket_semantic('HT7_Z0P5_Z2S0P25_note')
        b = parse_pocket_semantic('ht7_z0.5_z2-0.25_note')
        self.assertEqual((a.target, a.start, a.end, a.suffixes),
                         (b.target, b.start, b.end, b.suffixes))
        self.assertEqual((a.start, a.end, a.depth), (.5, 1.75, 1.25))

    def test_pocket_id_first_label_fallback(self):
        body = resolve_pocket('newsyntax', 'ht1_z0.0_z0.0+0.5')
        self.assertEqual((body.source, body.value.target, body.value.depth),
                         ('label', 't', .5))
        head = resolve_pocket('newsyntax2', 'h3_z0p0_z1p0')
        self.assertEqual((head.source, head.value.start, head.value.end),
                         ('label', 0, 1))
        old = resolve_pocket('h1_0_5', 'h9_z0_z1')
        self.assertEqual((old.source, old.value.index, old.value.depth),
                         ('id', 1, .05))

    def test_unrelated_hx_names_remain_unrelated(self):
        self.assertIsNone(parse_pocket_semantic('hx4_0_4000'))
        self.assertIsNone(parse_pocket_semantic('hole1'))

    def test_malformed_z_tokens_are_rejected(self):
        with self.assertRaises(SemanticSyntaxError):
            parse_pocket_semantic('h1_z0p_z1')
        with self.assertRaises(SemanticSyntaxError):
            parse_pocket_semantic('h1_z0')
        with self.assertRaises(SemanticSyntaxError):
            parse_pocket_semantic('h1_z0_z1_z2')


if __name__ == '__main__':
    unittest.main()
