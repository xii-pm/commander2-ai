"""Hex geometry invariants: offsets, distances and troop-count encoding."""
import sys
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from std_geometry import (BLANK, BLOCKED, FORT, HILL, KING, MARSH,  # noqa: E402
                          OBSTACLE, OFFSETS, hex_distance, move_number)

ROWS = COLS = 24


def neighbours(cell):
    """All in-board neighbours of a cell, using the SDK parity table."""
    row, col = cell
    for dr, dc in OFFSETS[row & 1]:
        nxt = (row + dr, col + dc)
        if 0 <= nxt[0] < ROWS and 0 <= nxt[1] < COLS:
            yield nxt


class OffsetsTest(unittest.TestCase):
    def test_every_offset_neighbour_is_one_step_away(self):
        for row in range(ROWS):
            for col in range(COLS):
                for nxt in neighbours((row, col)):
                    self.assertEqual(hex_distance((row, col), nxt), 1)

    def test_each_cell_has_at_most_six_neighbours(self):
        for row in range(ROWS):
            for col in range(COLS):
                seen = set(neighbours((row, col)))
                self.assertLessEqual(len(seen), 6)
                self.assertNotIn((row, col), seen)

    def test_offsets_are_antisymmetric(self):
        for row in range(4):
            for col in range(4):
                for nxt in neighbours((row, col)):
                    self.assertIn((row, col), set(neighbours(nxt)))


class DistanceTest(unittest.TestCase):
    def test_zero_and_symmetry(self):
        for cell in ((0, 0), (3, 11), (23, 23)):
            self.assertEqual(hex_distance(cell, cell), 0)
        for a, b in (((0, 0), (5, 7)), ((3, 11), (15, 17)), ((23, 0), (0, 23))):
            self.assertEqual(hex_distance(a, b), hex_distance(b, a))

    def test_triangle_inequality(self):
        points = ((0, 0), (5, 7), (3, 11), (15, 17), (23, 3))
        for a in points:
            for b in points:
                for c in points:
                    self.assertLessEqual(hex_distance(a, c),
                                         hex_distance(a, b) + hex_distance(b, c))

    def test_matches_breadth_first_search(self):
        """hex_distance must equal the shortest path on the real move graph."""
        for source in ((0, 0), (3, 11), (15, 5), (23, 23)):
            dist = {source: 0}
            queue = deque([source])
            while queue:
                cell = queue.popleft()
                for nxt in neighbours(cell):
                    if nxt not in dist:
                        dist[nxt] = dist[cell] + 1
                        queue.append(nxt)
            for target in ((0, 0), (3, 11), (23, 23), (12, 4)):
                self.assertEqual(hex_distance(source, target), dist[target],
                                 'distance mismatch {} -> {}'.format(source, target))


class MoveNumberTest(unittest.TestCase):
    def test_explicit_counts_are_clamped_to_movable_troops(self):
        self.assertEqual(move_number(10, 3), 3)
        self.assertEqual(move_number(10, 10), 9)
        self.assertEqual(move_number(10, 99), 9)

    def test_impossible_sends_raise(self):
        for units, sent in ((1, 1), (5, 0), (5, -2)):
            with self.assertRaises(ValueError):
                move_number(units, sent)

    def test_terrain_constants_match_the_platform_encoding(self):
        self.assertEqual((BLANK, KING, FORT, HILL, OBSTACLE, MARSH),
                         (1, 2, 3, 4, 5, 6))
        self.assertEqual(set(BLOCKED), {HILL, OBSTACLE})


if __name__ == '__main__':
    unittest.main()
