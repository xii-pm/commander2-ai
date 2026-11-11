"""Expansion methods preserved from the frozen BFS hunter."""
from std_geometry import BLANK, FORT, hex_distance


class Expansion:
    def network_leverage(self, pos):
        """Visible route value from joining allies or cutting enemy branches."""
        allied = sum(1 for p in self.neighbors[pos]
                     if p in self.cells and self.cells[p][1] == self.army)
        enemy = sum(1 for p in self.neighbors[pos]
                    if p in self.cells and self.cells[p][1] > 0 and self.cells[p][1] != self.army)
        nearby_producers = sum(1 for p, data in self.memory.items()
                               if data[0] == FORT and data[1] != self.army
                               and data[1] not in self.eliminated
                               and hex_distance(pos, p) <= 2)
        return (allied * self.NETWORK_ALLY_WEIGHT + enemy * self.NETWORK_ENEMY_WEIGHT +
                nearby_producers * self.NETWORK_PRODUCER_WEIGHT)

    def expand(self):
        choices = []
        focus = self.focus()
        for src in self.owned:
            if src in self.protected():
                continue
            have = self.available(src)
            # Initial footholds, then allow the king to accumulate a real field army.
            if src == self.home and len(self.owned) >= 4 and have < 12:
                continue
            for dst in self.neighbors[src]:
                if dst not in self.cells:
                    continue
                kind, owner, units = self.cells[dst]
                if kind != BLANK or owner != 0 or units > 1 or have <= units:
                    continue
                if self.counter(dst) >= units + 1:
                    continue
                sight = self.new_sight(dst)
                progress = hex_distance(src, focus) - hex_distance(dst, focus)
                if not self.kings:
                    hint_weight = self.HILL_HINT_UNSEEN_KING_WEIGHT
                elif progress >= 0:
                    hint_weight = self.HILL_HINT_FORWARD_WEIGHT
                else:
                    hint_weight = self.HILL_HINT_BACKWARD_WEIGHT
                score = len(sight) * 3 + len(sight & self.hill_hints) * hint_weight
                hint_approach = self.hill_hint_approach(src, dst)
                score += hint_approach * self.hill_hint_approach_weight()
                score += progress * 20 + self.network_leverage(dst)
                score += hex_distance(src, self.home) * 0.25
                choices.append((score, src, dst, units + 1))
        if choices:
            _, src, dst, count = max(choices)
            return self.action(src, dst, count, 'expand', 'one/two-soldier boundary claim')
        return None

    def fort_guard_action(self):
        if (self.kings and
                self.calls % self.POST_KING_GUARD_INTERVAL != 0):
            return None
        return self.economy.guard_action(self)

    def urgent_fort_guard_action(self):
        task = self.assault
        if not task:
            return None
        used = int(task.get('urgent_fort_guard_actions', 0))
        if used >= self.MAX_ASSAULT_URGENT_FORT_GUARDS:
            return None
        move = self.economy.guard_action(self, urgent_only=True)
        if move:
            task['urgent_fort_guard_actions'] = used + 1
            self.last_report['urgent_fort_guard_actions'] = used + 1
        return move
