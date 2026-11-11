import unittest

from freecad.marz.inlay_placement import Bounds2D, place_inlay


class InlayPlacementTests(unittest.TestCase):
    def setUp(self):
        # X runs from the previous fret at 0 toward the next fret at -20.
        # Y runs from treble (+) toward bass (-).
        self.cell = ((0.0, -10.0), (0.0, 10.0),
                     (-20.0, 10.0), (-20.0, -10.0))
        self.bounds = Bounds2D(-2.0, 2.0, -1.0, 1.0)

    def test_default_center_is_center_of_available_box_placement_region(self):
        placed = place_inlay(self.cell, self.bounds)
        self.assertAlmostEqual(placed.x, -10.0)
        self.assertAlmostEqual(placed.y, 0.0)

    def test_box_edges_align_to_previous_next_treble_and_bass(self):
        prev_treble = place_inlay(self.cell, self.bounds, 0.0, 0.0)
        next_bass = place_inlay(self.cell, self.bounds, 1.0, 1.0)
        # Rectangle corners touch the corresponding cell corners after erosion.
        self.assertAlmostEqual(prev_treble.x, -2.0)
        self.assertAlmostEqual(prev_treble.y, 9.0)
        self.assertAlmostEqual(next_bass.x, -18.0)
        self.assertAlmostEqual(next_bass.y, -9.0)


    def test_box_alignment_is_not_shifted_by_legacy_midpoint_semantics(self):
        # The production placement must be derived from the actual fret-space
        # boundaries.  A historical midpoint anchor would move these exact
        # edge contacts away from the requested x0/y1 box alignment.
        placed = place_inlay(self.cell, self.bounds, 0.0, 1.0)
        self.assertAlmostEqual(placed.x + self.bounds.max_x, 0.0)
        self.assertAlmostEqual(placed.y + self.bounds.min_y, -10.0)

    def test_signed_offsets_move_inward_from_each_selected_edge(self):
        x0 = place_inlay(self.cell, self.bounds, 0.0, 0.5, offset_x=2.5)
        x1 = place_inlay(self.cell, self.bounds, 1.0, 0.5, offset_x=-2.5)
        y0 = place_inlay(self.cell, self.bounds, 0.5, 0.0, offset_y=2.5)
        y1 = place_inlay(self.cell, self.bounds, 0.5, 1.0, offset_y=-2.5)
        self.assertLess(x0.x, place_inlay(self.cell, self.bounds, 0.0, 0.5).x)
        self.assertGreater(x1.x, place_inlay(self.cell, self.bounds, 1.0, 0.5).x)
        self.assertLess(y0.y, place_inlay(self.cell, self.bounds, 0.5, 0.0).y)
        self.assertGreater(y1.y, place_inlay(self.cell, self.bounds, 0.5, 1.0).y)

    def test_normalized_positions_keep_complete_box_inside_slanted_cell(self):
        def cross(a, b, p):
            return ((b[0] - a[0]) * (p[1] - a[1]) -
                    (b[1] - a[1]) * (p[0] - a[0]))

        cell = ((1.0, -9.0), (-1.0, 10.0),
                (-21.5, 13.0), (-18.5, -12.0))
        polygon = [cell[0], cell[1], cell[2], cell[3]]
        orientation = 1 if sum(
            polygon[i][0] * polygon[(i + 1) % 4][1] -
            polygon[(i + 1) % 4][0] * polygon[i][1]
            for i in range(4)) > 0 else -1
        for ax in (0.0, 0.25, 0.5, 0.75, 1.0):
            for ay in (0.0, 0.5, 1.0):
                placed = place_inlay(cell, self.bounds, ax, ay)
                for lx, ly in self.bounds.corners:
                    point = (placed.x + lx, placed.y + ly)
                    for i in range(4):
                        a = polygon[i]
                        b = polygon[(i + 1) % 4]
                        self.assertGreaterEqual(orientation * cross(a, b, point), -1e-7)

    def test_oversized_inlay_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'does not fit'):
            place_inlay(self.cell, Bounds2D(-20, 20, -20, 20))


if __name__ == '__main__':
    unittest.main()
