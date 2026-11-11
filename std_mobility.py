"""Short-lived uncertainty about a recently visible mobile hostile stack.

Unlike cell history, a departure does not assert that the departing force died.
Only currently unseen cells reachable from a recorded legal position can carry
the extra warning. Records are combined by maximum, never added to each other
or to the ordinary threat estimate. This is a bounded heuristic, not a force
identity tracker, an all-path bound, or a delivery/survival certificate.
"""
from collections import deque

from std_geometry import BLOCKED


class MobileWarning:
    def __init__(self):
        self.records = []
        self.updated_at = None
        self.cache = {}

    def observe(self, bot):
        if self.updated_at == bot.tick:
            return
        self.updated_at = bot.tick
        self.cache = {}
        window = bot.config.get('mobile_memory', 0)
        self.records = [r for r in self.records
                        if 0 <= bot.tick-r['seen'] <= window
                        and r['owner'] not in bot.eliminated]
        largest = {}
        for pos in bot.enemies:
            _, owner, units = bot.cells[pos]
            if units < 8 or bot.risk_dist.get(pos, 999) > 12+window:
                continue
            rank = units, -bot.risk_dist.get(pos, 999), pos
            if owner not in largest or rank > largest[owner][0]:
                largest[owner] = rank, pos, units
        for owner, (_, pos, units) in sorted(largest.items()):
            self.records.append(dict(owner=owner, pos=pos, units=units,
                                     seen=bot.tick))

    @staticmethod
    def unseen_reachable(bot, record, age):
        start = record['pos']
        distance = {start: 0}
        queue = deque([start])
        while queue:
            pos = queue.popleft()
            if distance[pos] >= age:
                continue
            for nxt in bot.neighbors[pos]:
                if nxt in distance or bot.memory.get(nxt, (0,))[0] in BLOCKED:
                    continue
                distance[nxt] = distance[pos]+1
                queue.append(nxt)
        return [pos for pos in distance if pos not in bot.cells]

    def curve(self, bot, horizon, margin, exclude=()):
        self.observe(bot)
        key = horizon, margin, tuple(sorted(exclude))
        if key in self.cache:
            return self.cache[key]
        curve, active = [0]*(horizon+1), []
        for record in self.records:
            if record['pos'] in exclude:
                continue
            age = bot.tick-record['seen']
            # A newly seen stack has no unobserved movement yet. Older records
            # only describe uncertainty in CURRENT fog, never an occupied cell
            # whose current observation already accounts for its units.
            if age <= 0:
                continue
            hidden = self.unseen_reachable(bot, record, age)
            eta = min([bot.risk_dist.get(p, 999) for p in hidden] or [999])
            eta = max(1, eta)
            if eta > horizon:
                continue
            force = max(0, record['units']-eta)
            if not force:
                continue
            active.append(dict(owner=record['owner'], last_pos=record['pos'],
                               age=age, observed_units=record['units'],
                               hidden_options=len(hidden), eta=eta, force=force))
            for h in range(eta, horizon+1):
                curve[h] = max(curve[h], force+margin)
        self.cache[key] = curve, active
        return curve, active
