"""Recognize 314 from own spawn and witnessed terrain, then keep checking.

Unknown observations never count as matches or contradictions. A positive is
an observation-based identification, not proof against arbitrary edited maps.
The detector never fills the agent's cells or memory with the reference.
After recognition the specialized policy may plan on known static geometry.
"""
from std_geometry import KING, FORT, HILL, OFFSETS
from std_map314_profile import SIZE, SPAWNS, TERRAIN


class Map314Detector:
    def __init__(self, army, rows, cols):
        self.army, self.rows, self.cols = army, rows, cols
        self.result = 0
        self.status = 'pending'
        self.reason = 'waiting_for_own_king'
        self.spawn = None
        self.calls = 0
        self.first_match = None
        self.rejected_at = None
        self.conflict = None
        self.terrain_seen = set()
        self.hints_seen = set()
        self.opening_seen = set()
        if (rows, cols) != SIZE:
            self._reject('size_mismatch')

    def _reject(self, reason, pos=None, observed=None, expected=None):
        self.result, self.status, self.reason = 0, 'rejected', reason
        self.rejected_at = self.calls
        if pos is not None:
            self.conflict = dict(pos=pos, observed=observed, expected=expected)

    def _expected(self, pos):
        return int(TERRAIN[pos[0]][pos[1]])

    def observe(self, cells, hill_hints=None):
        self.calls += 1
        if self.status == 'rejected':
            return 0

        if self.spawn is None:
            own_kings = sorted(p for p, d in cells.items() if d[0] == KING and d[1] == self.army)
            if len(own_kings) == 1:
                self.spawn = own_kings[0]
                if self.spawn not in SPAWNS:
                    self._reject('spawn_mismatch', self.spawn, 'own_king', SPAWNS)
                    return 0

        for pos, data in sorted(cells.items()):
            kind, owner, _ = data
            if kind == 0 or owner < 0:
                continue  # Also accept a masked input without treating UNKNOWN as BLANK.
            if not (0 <= pos[0] < self.rows and 0 <= pos[1] < self.cols):
                self._reject('position_outside_map', pos)
                return 0
            expected = self._expected(pos)
            # Captured kings become forts. Other terrain types stay fixed.
            matches = kind == expected or expected == KING and kind == FORT
            if not matches:
                self._reject('terrain_mismatch', pos, kind, expected)
                return 0
            if owner > 3:
                self._reject('owner_outside_three_player_map', pos, owner, '0..3')
                return 0
            self.terrain_seen.add(pos)

        for pos in sorted(hill_hints or ()):
            if not (0 <= pos[0] < self.rows and 0 <= pos[1] < self.cols):
                self._reject('hint_outside_map', pos)
                return 0
            # The masked SDK HILL can stand for a mountain OR a hidden fort.
            # A former king can become a fort after elimination, too.
            if self._expected(pos) not in (HILL, FORT, KING):
                self._reject('silhouette_mismatch', pos, 'hill_or_fort', self._expected(pos))
                return 0
            self.hints_seen.add(pos)

        if self.spawn is not None:
            r, c = self.spawn
            required = {self.spawn} | {(r + dr, c + dc) for dr, dc in OFFSETS[r & 1]}
            self.opening_seen.update(required & self.terrain_seen)
            if required <= self.opening_seen:
                self.result, self.status, self.reason = 1, 'matched', 'spawn_and_opening_terrain_match'
                if self.first_match is None:
                    self.first_match = self.calls
            else:
                self.reason = 'waiting_for_opening_terrain'
        return self.result

    def report(self):
        return dict(result=self.result, status=self.status, reason=self.reason,
                    spawn=self.spawn, checks=self.calls, first_match=self.first_match,
                    rejected_at=self.rejected_at, conflict=self.conflict,
                    terrain_checked=len(self.terrain_seen), silhouettes_checked=len(self.hints_seen),
                    opening_checked=len(self.opening_seen))
