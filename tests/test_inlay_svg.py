import os
import tempfile
import unittest

from freecad.marz.inlay_svg import collect_inlay_assignments


class InlaySvgGroupingTest(unittest.TestCase):
    def _parse(self, body):
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' "
               "xmlns:inkscape='http://www.inkscape.org/namespaces/inkscape' "
               "width='40mm' height='20mm' viewBox='0 0 40 20'>" +
               body + "</svg>")
        handle = tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False)
        try:
            handle.write(svg)
            handle.close()
            return collect_inlay_assignments(handle.name)
        finally:
            try:
                os.unlink(handle.name)
            except FileNotFoundError:
                pass

    def test_standalone_suffixes_share_one_logical_inlay(self):
        assignments, errors = self._parse(
            "<path id='f13_x0a2_y1s2_part1' d='M1 1h2v2h-2z'/>"
            "<circle id='part2' inkscape:label='f13_x0a2_y1s2_part2' "
            "cx='5' cy='2' r='1'/>")
        self.assertEqual((), errors)
        self.assertEqual(2, len(assignments))
        self.assertEqual(assignments[0].key, assignments[1].key)
        self.assertEqual((13.0, 0.0, 2.0, 1.0, -2.0),
                         assignments[0].semantic.placement_key)

    def test_tagged_groups_stay_distinct_at_same_placement(self):
        assignments, errors = self._parse(
            "<g id='groupA' inkscape:label='f13_x0a2_y1s2_logo'>"
            "<circle id='a1' cx='5' cy='2' r='1'/><circle id='a2' cx='8' cy='2' r='1'/></g>"
            "<g id='groupB' inkscape:label='f13_x0a2_y1s2_logo'>"
            "<circle id='b1' cx='12' cy='2' r='1'/></g>")
        self.assertEqual((), errors)
        keys = {}
        for item in assignments:
            keys.setdefault(item.key, []).append(item.element_id)
        self.assertEqual(2, len(keys))
        self.assertIn(['a1', 'a2'], list(keys.values()))
        self.assertIn(['b1'], list(keys.values()))
        self.assertTrue(all(item.owner_kind == 'group' for item in assignments))

    def test_valid_label_falls_back_from_unrelated_id(self):
        assignments, errors = self._parse(
            "<circle id='positioned' inkscape:label='f13_x0a2_y1s2_part2' "
            "cx='5' cy='2' r='1'/>")
        self.assertEqual((), errors)
        self.assertEqual(1, len(assignments))
        self.assertEqual('f13_x0a2_y1s2_part2', assignments[0].reference)

    def test_malformed_semantics_are_reported_but_noise_is_ignored(self):
        assignments, errors = self._parse(
            "<circle id='f13_x0p' cx='5' cy='2' r='1'/>"
            "<circle id='noise' cx='10' cy='2' r='1'/>")
        self.assertEqual((), assignments)
        self.assertEqual(1, len(errors))
        self.assertEqual('f13_x0p', errors[0].reference)


if __name__ == '__main__':
    unittest.main()
