"""State methods preserved from the frozen BFS hunter."""
import math
from std_geometry import KING, FORT, MARSH, BLOCKED, OFFSETS, hex_distance
from std_economy import Economy


class State:
    def __init__(self, army, rows, cols):
        self.army, self.rows, self.cols = army, rows, cols
        self.neighbors = {(r, c): [(r + dr, c + dc) for dr, dc in OFFSETS[r & 1]
                                  if 0 <= r + dr < rows and 0 <= c + dc < cols]
                          for r in range(rows) for c in range(cols)}
        self.tick = 0
        self.calls = 0
        self.cells, self.previous, self.memory = {}, {}, {}
        self.first_seen = {}
        self.first_enemy_seen = {}
        self.owned, self.enemies = [], []
        self.hill_hints, self.kings = set(), {}
        self.known_owners, self.eliminated = set(), set()
        self.home, self.rally = None, None
        self.home_keep = 1
        self.home_contact_risk = False
        self.home_guard_hold_by_owner = {}
        self.last_home_reserve_by_owner = {}
        self.home_dist, self.risk_dist = {}, {}
        self.mission = None
        self.pending = None
        self.scout = self.scout_rear = None
        self.rear_until = 0
        self.probe_last = -100
        self.hunt_probe_attempt = -100
        self.hunt_anchor_probe_count = 0
        self.counter_raid_last = -100
        self.failures, self.visits = {}, {}
        self.regional_hub = None
        self.path_cache = {}
        self.fort_reserves = {}
        self.economy = Economy(army)
        self.last_report = {}

    @property
    def assault(self):
        return self.mission if self.mission and self.mission['kind'] == 'assault' else None

    @property
    def fort(self):
        if self.mission and self.mission['kind'] == 'fort':
            return dict(stage=self.mission['pos'])
        return None

    def remember_strike_guard(self, pos):
        if not self.mission or pos is None:
            return
        kept = self.mission.get('strike_guard_kept')
        if isinstance(kept, list):
            cells = list(kept)
        elif isinstance(kept, set):
            cells = sorted(kept)
        else:
            cells = [] if kept is None else [kept]
        if pos not in cells:
            cells.append(pos)
        self.mission['strike_guard_kept'] = cells[-8:]

    def protected(self):
        result = {self.scout_rear}
        if self.mission:
            result.add(self.mission['pos'])
            result.add(self.mission.get('strike_guard_stage'))
            kept = self.mission.get('strike_guard_kept')
            if isinstance(kept, (list, set)):
                result.update(kept)
            else:
                result.add(kept)
        result.discard(None)
        return result

    def estimate_cell(self, p, arrival=0):
        if p in self.cells:
            kind, owner, units = self.cells[p]
            age = 0
        elif p in self.memory:
            kind, owner, units, seen = self.memory[p]
            age = self.tick - seen
            if owner == self.army:
                owner = -1  # own land is visible; historical ownership is invalid
            elif owner in self.eliminated:
                owner, units = 0, 0
        else:
            return None
        if owner in self.eliminated:
            owner, units = 0, 0
        if owner != 0 and owner != self.army:
            units += int(math.ceil((age + arrival) * (0.52 if kind in (KING, FORT) else 0.02)))
            if age:
                units += 2 + int(math.ceil(age * 0.12))
        return kind, owner, units

    def update(self, cells, hill_hints=None):
        self.calls += 1
        touched = {self.pending['src'], self.pending['dst']} if self.pending else set()
        delta = 1
        for p, data in cells.items():
            old = self.previous.get(p)
            if (old and data[0] in (KING, FORT) and old[1] == data[1] == self.army
                    and p not in touched and all(cells.get(n, (0, -1, 0))[1] in (0, self.army)
                                                 for n in self.neighbors[p])):
                gain = data[2] - old[2]
                if 2 <= gain <= 10:
                    delta = max(delta, 2 * gain - 1)
        self.tick += delta  # estimate only; economy has its own witnessed calibration
        self.cells, self.path_cache = dict(cells), {}
        self._counter_cache = {}
        self._sight_cache = {}
        self.owned = sorted(p for p, d in cells.items() if d[1] == self.army)
        self.enemies = sorted(p for p, d in cells.items() if d[1] > 0 and d[1] != self.army)
        self.known_owners.update(cells[p][1] for p in self.enemies)
        self.home = next((p for p in self.owned if cells[p][0] == KING), None)
        self.resolve_pending()
        for p, (kind, owner, units) in cells.items():
            if kind == KING and owner > 0 and owner != self.army:
                old = self.kings.get(owner)
                if old and old['pos'] == p:
                    dt = max(1, self.tick - old['seen'])
                    change = units - old['units']
                    rate = min(5.0, max(0, change / float(dt)))
                    old['rate'] = 0.75 * old['rate'] + 0.25 * rate
                    old['samples'] += 1
                    old['saving'] += int(abs(change - 0.52 * dt) <= 2 and change >= -1)
                    old.update(units=units, seen=self.tick)
                else:
                    self.kings[owner] = dict(pos=p, units=units, seen=self.tick,
                                             rate=0.52, samples=0, saving=0)
            self.memory[p] = kind, owner, units, self.tick
            self.first_seen.setdefault(p, (kind, owner, units, self.tick))
            if owner > 0 and owner != self.army:
                self.first_enemy_seen.setdefault(p, (kind, owner, units, self.tick))
            original_owner = self.first_enemy_seen.get(p,self.first_seen[p])[1]
            if (original_owner > 0 and original_owner != self.army
                    and owner > 0 and owner != self.army and original_owner != owner):
                self._search_transfer_seen = True
        for owner, model in list(self.kings.items()):
            p = model['pos']
            if p in cells and (cells[p][0] != KING or cells[p][1] != owner):
                if cells[p][0] in (KING, FORT) and cells[p][1] != owner:
                    self.eliminated.add(owner)
                del self.kings[owner]
        self.enemies = [p for p in self.enemies if self.cells[p][1] not in self.eliminated]
        self.home_guard_hold_by_owner = {
            owner: floor for owner, floor in self.home_guard_hold_by_owner.items()
            if owner not in self.eliminated}
        self.hill_hints = set(hill_hints or ()) - set(self.memory)
        if self.scout not in self.owned:
            self.scout = None
        if self.scout_rear not in self.owned or self.tick >= self.rear_until:
            self.scout_rear = None
        if self.home:
            self.home_dist = self.bfs(self.home, lambda p: p in cells and cells[p][1] == self.army)
            # For defence only: assume unknown approaches passable, not map truth.
            self.risk_dist = self.bfs(self.home, lambda p: self.memory.get(p, (0,))[0] not in BLOCKED)
        self.economy.observe(self, self.previous, touched)
        self.fort_reserves = self.economy.reserves(self)
        # Immediate garrison and mission-horizon risk are separate quantities.
        # Long lookahead remains a launch gate but must not become a permanent
        # home convoy objective during an already active field operation.
        self.home_keep = self.reserve_home(self.HOME_DEFENSE_HORIZON)
        # Adjacent visible contact is only a King-exposure risk proxy; the
        # SDK does not report whether an opponent has actually seen our King.
        for pos in self.enemies:
            if self.home and hex_distance(self.home, pos) <= 1:
                owner = self.cells[pos][1]
                force = self.last_home_reserve_by_owner.get(owner, 0)
                floor = self.home_contact_floor(force)
                self.home_guard_hold_by_owner[owner] = max(
                    self.home_guard_hold_by_owner.get(owner, 0), floor)
        # After contact is observed, latch the strongest force seen inside the
        # immediate response horizon so a temporary visibility gap cannot
        # unlock the King garrison before the threat is eliminated.
        for owner, current in list(self.home_guard_hold_by_owner.items()):
            force = self.last_home_reserve_by_owner.get(owner, 0)
            if force:
                floor = self.home_contact_floor(force)
                self.home_guard_hold_by_owner[owner] = max(current, floor)
        self.home_contact_risk = bool(self.home_guard_hold_by_owner)
        if self.mission and self.mission['pos'] not in self.owned:
            target = self.mission['target']
            if not self.restage_assault():
                self.failures[target] = self.tick
                self.mission = None
        self.previous = dict(cells)
        self.last_report = dict(tick=self.tick, mode='save', owned=len(self.owned),
                                units=sum(cells[p][2] for p in self.owned),
                                home_keep=self.home_keep, home_contact_risk=self.home_contact_risk,
                                home_contact_risk_by=sorted(self.home_guard_hold_by_owner),
                                home_guard_floor=max(self.home_keep, self.home_guard_hold()),
                                home_guard_hold_by_owner=dict(self.home_guard_hold_by_owner),
                                unconfirmed_hills=len(self.hill_hints),
                                growth_cycle=self.economy.phase_info(self))

    def resolve_pending(self):
        if not self.pending:
            return
        order = self.pending
        a, b = self.cells.get(order['src']), self.cells.get(order['dst'])
        confirmed = False
        if b and b[1] == self.army:
            if order['before_dst'][1] != self.army:
                confirmed = True
            elif a and a[1] == self.army:
                age = max(1, self.tick - order['tick'])
                before = (order['before_src'], order['before_dst'])
                bases = (before[0][2] - order['sent'], before[1][2] + order['sent'])
                periods = [2 if d[0] in (KING, FORT) else 50 for d in before]
                possible = []
                for old, base, observed, period in zip(before, bases, (a[2], b[2]), periods):
                    pulses = range(age // period, int(math.ceil(age / float(period))) + 1)
                    sign = -1 if old[0] == MARSH else 1
                    possible.append({k for k in pulses if observed == max(0, base + sign * k)})
                confirmed = all(possible)
                if periods[0] == periods[1] and not (possible[0] & possible[1]):
                    confirmed = False
        if confirmed:
            self.visits[order['dst']] = self.visits.get(order['dst'], 0) + 1
            if self.mission and self.mission['pos'] == order['src'] and order['advance']:
                trail = list(self.mission.get('trail', [order['src']]))
                if not trail or trail[-1] != order['src']:
                    trail.append(order['src'])
                self.mission.update(pos=order['dst'], progress=self.tick,
                                    trail=trail[-12:])
            if order['role'] == 'scout':
                self.scout = order['dst']
            self.pending = None
        elif self.tick - order['tick'] >= 3 or not a or a[1] != self.army:
            self.pending = None  # retain mission position; retry only from observation

    def finish(self, move):
        protected = self.protected()
        expansion_units, expansion_sources = 0, 0
        single_soldier_cells = 0
        blocked_stacks, protected_stacks = [], []
        for pos in self.owned:
            units = self.cells[pos][2]
            available = self.available(pos)
            if units == 1:
                single_soldier_cells += 1
            if pos not in protected:
                expansion_units += available
                expansion_sources += int(available > 0)
            if units <= 1:
                continue
            if pos in protected:
                protected_stacks.append(dict(pos=pos, units=units, available=available,
                                             lock='mission_protected'))
            elif available == 0:
                reserve = max(1, self.fort_reserves.get(pos, 1),
                              self.home_keep if pos == self.home else 1)
                if pos == self.home:
                    reserve = max(reserve, self.home_guard_hold())
                lock = ('home_guard' if pos == self.home and reserve > self.home_keep
                        else 'home_keep' if pos == self.home
                        else 'fort_cluster' if self.fort_reserves.get(pos, 1) > 1
                        else 'reserve')
                blocked_stacks.append(dict(pos=pos, units=units, reserve=reserve, lock=lock))
        blocked_stacks.sort(key=lambda item: (item['units'], item['pos']), reverse=True)
        protected_stacks.sort(key=lambda item: (item['units'], item['pos']), reverse=True)
        self.last_report.update(mission=dict(self.mission) if self.mission else None,
                                home_keep=self.home_keep,
                                kings={owner: dict(pos=m['pos'], **self.predict_king(owner))
                                       for owner, m in self.kings.items()},
                                expansion_available_units=expansion_units,
                                expansion_available_sources=expansion_sources,
                                single_soldier_cells=single_soldier_cells,
                                reserve_blocked_stacks=blocked_stacks[:8],
                                protected_stacks=protected_stacks[:8])
        return move
