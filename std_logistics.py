"""Logistics methods preserved from the frozen BFS hunter."""
from std_geometry import BLANK, KING, FORT


class Logistics:
    def gather(self, goal, reason, role='supply', limit=None, exclude=(), max_distance=None):
        if goal not in self.owned:
            return None
        dist = self.bfs(goal, lambda p: p in self.cells and self.cells[p][1] == self.army)
        assault_supply = role == 'supply' and bool(self.assault)
        protected = set(exclude) | (self.protected() if role != 'defend' else set())
        choices = []
        for src in self.owned:
            if src == goal or src in protected or src not in dist:
                continue
            count = self.cells[src][2] - 1 if role == 'defend' and src != self.home else self.available(src)
            available = count
            distance = dist[src]
            if max_distance is not None and distance > max_distance:
                continue
            floor = 1.0 if self.cells[src][0] in (KING, FORT) else 1.5
            donor_rate = available / float(max(1, distance))
            if role != 'defend' and not assault_supply and donor_rate < floor:
                continue
            if (role != 'defend' and not assault_supply
                    and self.cells[src][0] == BLANK and available <= 2 and any(
                        n in self.cells and self.cells[n][0:2] == (BLANK, 0)
                        and self.cells[n][2] < available for n in self.neighbors[src])):
                continue
            if limit is not None:
                count = min(available, max(1, int(limit)))
            if count <= 0:
                continue
            dst = max((p for p in self.neighbors[src] if dist.get(p) == distance - 1),
                      key=lambda p: self.cells[p][2])
            # Normal missions rank full donor capacity; strike and defense rank
            # the payload capped by their live command budget.
            rate_payload = count if assault_supply or role == 'defend' else available
            delivery_rate = rate_payload / float(max(1, distance))
            choices.append((delivery_rate, -distance, count, src, dst))
        for delivery_rate, negative_distance, count, src, dst in sorted(choices, reverse=True):
            result = self.action(src, dst, count, role, reason)
            if result:
                steps = -negative_distance
                self.last_report.update(gather_goal=goal, gather_steps=steps,
                                        gather_payload_rate=round(count / float(max(1, steps)), 3),
                                        gather_requested=limit)
                if role == 'defend' and src == self.scout_rear:
                    self.scout_rear = None
                return result
        return None

    def regional(self):
        if not self.home:
            return None
        donors = [p for p in self.owned if self.cells[p][0] == BLANK and p not in self.protected()
                  and self.available(p) >= 1 and self.home_dist.get(p, 999) > 4]
        options = []
        for hub in donors:
            distance = self.bfs(hub, lambda p: p in self.cells and self.cells[p][1] == self.army, 2)
            local = [p for p in donors if p != hub and p in distance]
            if not local:
                continue
            score = sum(self.available(p) / float(1 + distance[p]) for p in local)
            score += len(self.new_sight(hub)) + (3 if hub == self.regional_hub else 0)
            options.append((score, hub, distance, local))
        if not options:
            return None
        _, hub, distance, local = max(options, key=lambda x: (x[0], x[1]))
        src = max(local, key=lambda p: self.available(p) / float(distance[p]))
        dst = next(p for p in self.neighbors[src] if distance.get(p) == distance[src] - 1)
        self.regional_hub = hub
        return self.action(src, dst, self.available(src), 'regional', 'pool nearby remote garrisons')
