"""Persistent fog-of-war strategy, Python 3.6, standard library only.

Input cells are CURRENTLY VISIBLE (terrain, owner, units). All historical
information is timestamped. No filesystem, SDK, spectator or map access here.
"""
from collections import deque
import heapq
import math
from std_probe_economy import Economy
from std_probe_campaign import Campaign

BLANK, KING, FORT, HILL, OBSTACLE, MARSH = range(1, 7)
BLOCKED = (HILL, OBSTACLE)
OFFSETS = (((-1, 0), (0, 1), (1, 0), (1, -1), (0, -1), (-1, -1)),
           ((-1, 1), (0, 1), (1, 1), (1, 0), (0, -1), (-1, 0)))


def hex_distance(a, b):
    # odd-r offset: odd rows shift RIGHT, matching SDK direction tables.
    aq = a[1] - (a[0] - (a[0] & 1)) // 2
    bq = b[1] - (b[0] - (b[0] & 1)) // 2
    dq, dr = aq - bq, a[0] - b[0]
    return max(abs(dq), abs(dr), abs(dq + dr))


def move_number(units, sent):
    """Explicit troop counts. Native DLL probes verify that num=1 sends ONE.

    num=0 moves everything except one, 0<num<1 floors a proportion.
    """
    sent = int(min(sent, units - 1))
    if sent <= 0:
        raise ValueError('no movable units')
    # Use an explicit count even when it equals all currently movable troops:
    # an intervening production tick would make num=0 send MORE than planned.
    return sent


class Agent:
    EVERY_STEP = False
    RALLY_RADIUS = 2
    SCOUT_BUDGET = 12
    SCOUT_MAX_BUDGET = 48  # only when observed path attrition requires a larger scout
    SCOUT_INTERVAL = 3
    KING_MAX_AGE = 70
    FORT_MAX_ROUTE = 14

    def __init__(self, army, rows, cols):
        self.army, self.rows, self.cols = army, rows, cols
        self.neighbors = {}
        for r in range(rows):
            for c in range(cols):
                self.neighbors[(r, c)] = [(r + dr, c + dc) for dr, dc in OFFSETS[r % 2]
                                          if 0 <= r + dr < rows and 0 <= c + dc < cols]
        self.tick = 0
        self.calls = 0
        self.memory = {}  # pos -> (kind, last_owner, last_units, observation_tick)
        self.hill_hints = set()  # masked fog silhouettes; NOT confirmed terrain
        self.kings = {}   # observed enemy king models
        self.home = None
        self.rally = None
        self.rally_since = 0
        self.fort = None
        self.scout = None
        self.scout_last = -20
        self.scout_rear = None
        self.scout_rear_until = 0
        self.rear_record = None
        self.scout_losses = {}
        self.regional_hub = None
        self.regional_since = 0
        self.assault = None
        self.pending = None
        self.previous = {}
        self.visits = {}
        self.cells = {}
        self.owned = []
        self.enemies = []
        self.home_dist = {}
        self.risk_dist = {}
        self.home_keep = 2
        self.last_report = {}
        self.last_attempt = {}
        self.path_cache = {}
        self.economy = Economy(army)
        self.fort_reserves = {}
        self.campaign = Campaign()

    def bfs(self, start, allowed):
        distance = {start: 0}
        queue = deque([start])
        while queue:
            pos = queue.popleft()
            for nxt in self.neighbors[pos]:
                if nxt not in distance and allowed(nxt):
                    distance[nxt] = distance[pos] + 1
                    queue.append(nxt)
        return distance

    def growth(self, kind, owner, steps):
        if owner <= 0:
            return 0
        return int(math.ceil(max(0, steps) * (0.52 if kind in (FORT, KING) else 0.02)))

    def estimate_cell(self, pos, arrival=0):
        if pos in self.cells:
            kind, owner, units = self.cells[pos]
            age = 0
        elif pos in self.memory:
            kind, owner, units, seen = self.memory[pos]
            age = self.tick - seen
        else:
            return None
        if owner == self.army and pos not in self.cells:
            # Own ground is always visible. Lost visibility invalidates old ownership.
            owner, units = -1, max(1, units)
        extra = self.growth(kind, owner, age + arrival)
        if age and owner != 0:
            extra += int(math.ceil(age * 0.12)) + 2
        return kind, owner, units + extra

    def paths(self, start, owned_only=False, avoid_enemy=False):
        """Dijkstra balances command distance with combat cost on KNOWN terrain."""
        key = (start, owned_only, avoid_enemy)
        if key in self.path_cache:
            return self.path_cache[key]
        costs, parent, lengths = {start: 0.0}, {start: None}, {start: 0}
        queue = [(0.0, start)]
        while queue:
            cost, pos = heapq.heappop(queue)
            if cost != costs[pos]:
                continue
            for nxt in self.neighbors[pos]:
                data = self.estimate_cell(nxt)
                if data is None or data[0] in BLOCKED:
                    continue
                kind, owner, units = data
                if owned_only and (nxt not in self.cells or owner != self.army):
                    continue
                if avoid_enemy and owner > 0 and owner != self.army and units > 4:
                    continue
                edge = 1.0
                if owner != self.army:
                    edge += units * 0.13 + (0.7 if owner > 0 else 0)
                if nxt not in self.cells:
                    edge += 0.7
                if kind == MARSH:
                    edge += 3
                new = cost + edge
                if new < costs.get(nxt, float('inf')):
                    costs[nxt], parent[nxt], lengths[nxt] = new, pos, lengths[pos] + 1
                    heapq.heappush(queue, (new, nxt))
        self.path_cache[key] = costs, parent, lengths
        return costs, parent, lengths

    @staticmethod
    def path(parent, target):
        if target not in parent:
            return None
        route = []
        while target is not None:
            route.append(target)
            target = parent[target]
        return list(reversed(route))

    def update(self, cells, hill_hints=None):
        if hill_hints is not None:
            self.hill_hints = set(hill_hints) - set(cells) - set(self.memory)
        self.path_cache = {}
        self.calls += 1
        # SDK has no global step. Stationary uncontested producer growth can expose
        # coalesced callbacks. Keep this an estimate, never claim exact modulo 50.
        delta = 1
        touched = set()
        if self.pending:
            touched = {self.pending['src'], self.pending['dst']}
        for p, data in cells.items():
            old = self.previous.get(p)
            if (old and old[0] in (KING, FORT) and old[1] == data[1] == self.army
                    and p not in touched and all(cells.get(n, (0, 0, 0))[1] in (0, self.army)
                                                for n in self.neighbors[p])):
                gain = data[2] - old[2]
                if 2 <= gain <= 10:
                    delta = max(delta, 2 * gain - 1)
        self.tick += delta
        self.cells = cells
        self.owned = sorted(p for p, d in cells.items() if d[1] == self.army)
        self.enemies = sorted(p for p, d in cells.items() if d[1] > 0 and d[1] != self.army)
        for p in self.owned:
            if cells[p][0] == KING:
                self.home = p
        self.resolve_pending()
        for p, (kind, owner, units) in cells.items():
            if kind == KING and owner > 0 and owner != self.army:
                model = self.kings.get(owner)
                if model is None or model['pos'] != p:
                    model = dict(pos=p, units=units, seen=self.tick, rate=0.52,
                                 samples=0, saving=0, inflow=0, outflow=0)
                    self.kings[owner] = model
                else:
                    dt = max(1, self.tick - model['seen'])
                    change = units - model['units']
                    rate = max(-5.0, min(8.0, change / float(dt)))
                    model['rate'] = model['rate'] * 0.75 + max(0.0, rate) * 0.25
                    model['samples'] += 1
                    if change >= -1 and abs(change - dt * 0.52) <= 2:
                        model['saving'] += 1
                    elif change < -1:
                        model['outflow'] += 1
                    elif change > dt * 0.52 + 2:
                        model['inflow'] += 1
                    model.update(units=units, seen=self.tick)
            self.memory[p] = (kind, owner, units, self.tick)
        for owner, model in list(self.kings.items()):
            p = model['pos']
            if p in cells and (cells[p][0] != KING or cells[p][1] != owner):
                del self.kings[owner]
        if self.scout is not None and (self.scout not in cells or cells[self.scout][1] != self.army):
            self.scout_losses[self.scout] = self.tick
            self.scout = None
        if self.scout_rear not in cells or cells.get(self.scout_rear, (0, 0))[1] != self.army:
            self.scout_rear = None
        if self.assault and self.assault['owner'] not in self.kings:
            self.assault = None
        if self.home is not None:
            self.home_dist = self.bfs(self.home, lambda p: p in cells and cells[p][1] == self.army)
            # Threat reach assumes unseen terrain passable. That is conservative,
            # not a source of hidden map facts. All six approaches are evaluated.
            self.risk_dist = self.bfs(self.home, lambda p: self.memory.get(p, (0,))[0] not in BLOCKED)
        self.home_keep = max(self.reserve_home(3), self.campaign.home_reserve)
        self.economy.observe(self, self.previous, touched)
        self.fort_reserves = self.economy.reserves(self)
        self.previous = dict(cells)
        self.last_report = dict(tick=self.tick, mode='hold', rally=self.rally,
                               growth_cycle=self.economy.phase_info(self),
                               fort_guards=[dict(pos=p, keep=k) for p, k in sorted(self.fort_reserves.items())],
                               unconfirmed_hills=len(self.hill_hints),
                                owned=len(self.owned), units=sum(cells[p][2] for p in self.owned),
                                scout=self.scout, home_keep=self.home_keep)

    def resolve_pending(self):
        if not self.pending:
            return
        order = self.pending
        src, dst = order['src'], order['dst']
        a, b = self.cells.get(src), self.cells.get(dst)
        # Do not advance a route merely because a command was sent.
        confirmed = False
        if b is not None and b[1] == self.army:
            if order['old_owner'] != self.army:
                confirmed = True
            elif a is not None and a[1] == self.army:
                # Both endpoints must fit the sent quantity plus possible natural
                # growth. A producer growing alone is NOT evidence of a transfer.
                age = max(1, self.tick - order['time'])
                sg = a[2] - (order['src_units'] - order['sent'])
                dg = b[2] - (order['old_units'] + order['sent'])
                sp = 2 if order['src_kind'] in (KING, FORT) else 50
                dp = 2 if order['dst_kind'] in (KING, FORT) else 50
                confirmed = (age // sp <= sg <= int(math.ceil(age / float(sp)))
                             and age // dp <= dg <= int(math.ceil(age / float(dp))))
                if sp == dp and sg != dg:
                    confirmed = False
        if confirmed:
            self.campaign.confirmed(order, self.tick)
            if order['role'] == 'scout':
                self.scout = dst
            if order['role'] == 'assault' and self.assault:
                self.assault['pos'] = dst
            self.visits[dst] = self.visits.get(dst, 0) + 1
            self.last_attempt.pop((src, dst, order['role']), None)
            self.pending = None
        elif self.tick - order['time'] >= 3 or a is None or a[1] != self.army:
            self.pending = None

    def predict_king(self, owner, travel=0, path_defenders=()):
        model = self.kings[owner]
        age = max(0, self.tick - model['seen'])
        saving = (model['samples'] >= 4 and model['saving'] >= model['samples'] * 0.7
                  and model['outflow'] <= 1)
        rate = max(0.52, min(5.0, model['rate']))
        estimate = model['units'] + int(math.ceil(rate * (age + travel)))
        uncertainty = 2 + int(math.ceil(age * (0.10 if saving else 0.35) + travel * 0.15))
        # Nearby visible stacks may reinforce the king during our march.
        reinforcements = 0
        for pos in self.enemies:
            data = self.cells[pos]
            if data[1] != owner or pos == model['pos'] or pos in path_defenders:
                continue
            if hex_distance(pos, model['pos']) <= travel + 1:
                reinforcements += max(0, data[2] - 1)
        return dict(expected=estimate, upper=estimate + uncertainty + reinforcements,
                    age=age, style='saving' if saving else 'unknown',
                    uncertainty=uncertainty, reinforcements=reinforcements)

    def reserve_home(self, horizon, exclude_owner=None):
        # Estimate force reaching home by the horizon; no arbitrary upper cap.
        by_owner = {}
        for pos in self.enemies:
            kind, owner, units = self.cells[pos]
            if owner == exclude_owner:
                continue
            distance = self.risk_dist.get(pos, 999)
            if distance <= horizon:
                force = max(0, units - distance) + self.growth(kind, owner, max(0, horizon - distance))
                if force:
                    by_owner[owner] = by_owner.get(owner, 0) + force
        # Brief loss of vision does not erase an approaching army. A stale stack
        # can have moved towards us; avoid double-counting it and its visible successor.
        for pos, (kind, owner, units, seen) in self.memory.items():
            age = self.tick - seen
            if (pos in self.cells or owner <= 0 or owner in (self.army, exclude_owner)
                    or age > 8 or units <= 3):
                continue
            remaining = max(0, self.risk_dist.get(pos, 999) - age)
            if remaining <= horizon:
                force = max(0, units - remaining) + self.growth(kind, owner, age)
                by_owner[owner] = max(by_owner.get(owner, 0), force)
        base = 1 if self.tick < 30 and len(self.owned) < 15 else 2
        return max(base, sum(by_owner.values()) + (2 if by_owner else 0))

    def available(self, src, keep=None):
        if src not in self.cells or self.cells[src][1] != self.army:
            return 0
        reserve = max(self.home_keep if src == self.home else 1, self.fort_reserves.get(src, 1))
        if keep is not None:
            reserve = max(reserve, keep)
        return max(0, self.cells[src][2] - reserve)

    def action(self, src, dst, count, role, reason):
        if (src not in self.cells or dst not in self.cells or dst not in self.neighbors[src]
                or self.cells[src][1] != self.army or self.cells[dst][0] in BLOCKED):
            return None
        count = int(min(count, self.cells[src][2] - 1))
        if count <= 0:
            return None
        target = self.cells[dst]
        if target[1] != self.army and count <= target[2]:
            return None
        if self.pending:
            return None
        signature = (src, dst, role)
        retry_interval = 1 if self.EVERY_STEP else 2
        if self.tick - self.last_attempt.get(signature, -99) < retry_interval:
            return None
        self.last_attempt[signature] = self.tick
        self.pending = dict(src=src, dst=dst, old_owner=target[1], old_units=target[2],
                            src_units=self.cells[src][2], src_kind=self.cells[src][0],
                            dst_kind=target[0], sent=count, time=self.tick, role=role)
        self.last_report.update(mode=role, reason=reason, src=src, dst=dst, send=count,
                                rally=self.rally, scout=self.scout)
        return src, dst, count

    def step_on(self, route, count, role, reason):
        if route is None or len(route) < 2:
            return None
        return self.action(route[0], route[1], count, role, reason)

    def return_efficient(self, src, distance):
        """Useful soldiers per command on owned roads; small remote stacks stay regional.

        A normal owned road already has a garrison: merging offsets the one left
        behind. Transport costs COMMANDS, not one extra casualty on every such tile.
        Empty owned garrisons and future enemy cuts can reduce realized delivery.
        """
        count = self.available(src)
        rate = count / float(max(1, distance))
        if self.cells[src][0] in (KING, FORT):
            return distance <= 3 or rate >= 1.0
        return distance <= 3 or rate >= 1.5

    def regional_action(self):
        """Merge remote low-yield garrisons locally into a scouting vanguard."""
        if self.rally is None:
            return None
        to_main = self.bfs(self.rally, lambda p: p in self.cells and self.cells[p][1] == self.army)
        donors = [p for p in self.owned if self.cells[p][0] == BLANK and self.available(p) > 0
                  and self.home_dist.get(p, 999) >= 5 and p not in (self.scout, self.scout_rear)
                  and p not in self.campaign.protected()
                  and not (self.assault and p == self.assault['pos'])
                  and not self.return_efficient(p, to_main.get(p, 999))]
        if len(donors) < 2:
            return None
        if (self.regional_hub not in self.cells or self.cells.get(self.regional_hub, (0, 0))[1] != self.army
                or self.tick - self.regional_since > 24):
            candidates = []
            for hub in donors:
                distance = self.bfs(hub, lambda p: p in self.cells and self.cells[p][1] == self.army)
                local = [p for p in donors if distance.get(p, 999) <= 2]
                if len(local) < 2:
                    continue
                score = sum(self.available(p) / (1 + distance[p]) for p in local)
                score += len(self.new_sight(hub)) * 0.6
                candidates.append((score, hub))
            if not candidates:
                return None
            self.regional_hub = max(candidates)[1]
            self.regional_since = self.tick
        hub = self.regional_hub
        if hub == self.scout:
            return None
        distance = self.bfs(hub, lambda p: p in self.cells and self.cells[p][1] == self.army)
        local = [p for p in donors if p != hub and distance.get(p, 999) <= 2]
        if not local:
            return None
        src = max(local, key=lambda p: self.available(p) / float(distance[p]))
        dst = next(p for p in self.neighbors[src] if distance.get(p, 999) == distance[src] - 1)
        self.last_report['regional_hub'] = hub
        return self.action(src, dst, self.available(src), 'regional', 'remote plain troops: merge locally, avoid expensive return')

    def gather(self, goal, reason, role='gather', limit=None, exclude=()):
        if goal not in self.cells or self.cells[goal][1] != self.army:
            return None
        dist = self.bfs(goal, lambda p: p in self.cells and self.cells[p][1] == self.army)
        choices = []
        protected = set(exclude)
        if role not in ('defend', 'guard'):
            protected.update(self.campaign.protected())
        if self.scout is not None and role != 'defend':
            protected.add(self.scout)
        if role not in ('defend', 'guard') and self.scout_rear is not None:
            protected.add(self.scout_rear)
        if self.assault:
            protected.add(self.assault['pos'])
        for src in self.owned:
            if src == goal or src in protected or src not in dist:
                continue
            if role in ('gather', 'fort') and not self.return_efficient(src, dist[src]):
                continue
            count = (self.cells[src][2] - 1) if role == 'defend' and src != self.home else self.available(src)
            if (role == 'gather' and self.cells[src][0] == BLANK and count <= 2
                    and any(n in self.cells and self.cells[n][1] == 0 and self.cells[n][0] == BLANK
                            and self.cells[n][2] < count for n in self.neighbors[src])):
                continue  # peripheral one/two soldiers can expand immediately instead of returning
            if limit is not None:
                count = min(count, limit + dist[src] - 1)
            if count <= 0 or (count < 2 and dist[src] > 1):
                continue
            onward = [p for p in self.neighbors[src] if dist.get(p, 999) == dist[src] - 1]
            if not onward:
                continue
            dst = max(onward, key=lambda p: self.cells[p][2])
            score = (count + max(0, self.cells[dst][2] - 1) * 0.1) / (1 + dist[src] * 0.22)
            choices.append((score, src, dst, count))
        for _, src, dst, count in sorted(choices, reverse=True):
            result = self.action(src, dst, count, role, reason)
            if result:
                return result
        return None

    def defend(self):
        if self.home not in self.cells:
            return None
        threat = self.reserve_home(4)
        if threat <= 2:
            return None
        missing = threat - self.cells[self.home][2]
        if missing > 0:
            # Recall has precedence over attack; rally is at most two owned steps away.
            if self.assault and self.risk_dist.get(self.assault['pos'], 999) <= 4:
                self.assault = None
            result = self.gather(self.home, 'visible threat: reinforce king', role='defend', limit=missing + 2)
            if result:
                return result
        # Intercept a visible threatening army when it can be eliminated cheaply.
        options = []
        for enemy in self.enemies:
            if self.risk_dist.get(enemy, 999) > 3:
                continue
            for src in self.neighbors[enemy]:
                count = self.available(src)
                if count > self.cells[enemy][2]:
                    options.append((self.cells[enemy][2], src, enemy, count))
        for _, src, dst, count in sorted(options, reverse=True):
            move = self.action(src, dst, count, 'defend', 'intercept near-home threat')
            if move:
                return move
        return None

    def select_rally(self):
        if self.home is None:
            return
        candidates = [p for p, d in self.home_dist.items() if d <= self.RALLY_RADIUS]
        goals = [v['pos'] for v in self.kings.values()]
        if not goals:
            goals = [p for p, d in self.cells.items() if d[0] == FORT and d[1] != self.army]
        if not goals:
            goals = [p for p in self.cells if any(n not in self.memory for n in self.neighbors[p])]
        if not goals:
            goals = [self.home]
        def score(p):
            approach = min(hex_distance(p, target) for target in goals)
            d = self.home_dist[p]
            # Limit recall cost; use stable producer/owned staging rather than chasing scouts.
            value = -approach * 1.5 - d * 1.2
            if self.cells[p][0] in (KING, FORT):
                value += 1.3
            value += min(4, self.cells[p][2] * 0.025)
            if p == self.rally:
                value += 2.8
            return value
        best = max(candidates, key=score)
        if self.rally not in candidates or self.tick - self.rally_since >= 16:
            if best != self.rally:
                self.rally, self.rally_since = best, self.tick

    def direct_objective(self, kings_only=False):
        candidates = []
        for target, (kind, owner, guards) in self.cells.items():
            if kind not in (KING, FORT) or owner == self.army or (kings_only and kind != KING):
                continue
            for src in self.neighbors[target]:
                if kind == FORT and (src == self.scout_rear or
                                     (self.assault and src == self.assault['pos'])):
                    continue  # Do not consume the scout reserve or committed strike.
                keep = self.home_keep
                if kind == KING and src == self.home:
                    keep = self.reserve_home(2, exclude_owner=owner)
                count = self.available(src, keep if src == self.home else None)
                if kind == KING and src == self.home:
                    count = max(0, self.cells[src][2] - keep)
                if guards < count:
                    score = (1000 if kind == KING else 100) - guards
                    candidates.append((score, src, target, count, kind))
        for _, src, target, count, kind in sorted(candidates, reverse=True):
            # Forts receive only enough to capture + small local reserve, not all the main stack.
            send = count if kind == KING else min(count, self.cells[target][2] + 3)
            move = self.action(src, target, send, 'capture', 'capture king' if kind == KING else 'cheap producer opportunity')
            if move:
                return move
        return None

    def choose_fort(self):
        if self.rally is None:
            return
        if self.fort:
            goal = self.fort['target']
            data = self.cells.get(goal)
            if data and (data[1] == self.army or data[0] != FORT):
                self.fort = None
            elif self.tick - self.fort['started'] > 100:
                self.fort = None
        if self.fort:
            return
        costs, parent, lengths = self.paths(self.rally)
        choices = []
        producer_count = sum(self.cells[p][0] in (KING, FORT) for p in self.owned)
        for goal, data in self.cells.items():
            if data[0] != FORT or data[1] == self.army or goal not in parent:
                continue
            if self.kings and producer_count >= 3 and data[2] > 4:
                continue  # Enough income: save the main army for the king strike.
            if lengths[goal] > self.FORT_MAX_ROUTE:
                continue
            route = self.path(parent, goal)
            score = 90.0 / (3 + lengths[goal] + data[2] * 0.12)
            if data[1] > 0 and data[1] != self.army:
                score += 8  # gain a producer while also denying enemy production
            if data[2] <= 4:
                score += 20  # Empty/one-unit producers deserve a staging plan immediately.
            if self.kings and data[2] > 12:
                score *= 0.6
            choices.append((score, goal, route))
        if choices:
            _, goal, route = max(choices)
            self.fort = dict(target=goal, stage=route[-2], started=self.tick)

    def fort_action(self):
        if not self.fort:
            return None
        target, stage = self.fort['target'], self.fort['stage']
        if stage == self.scout_rear or (self.assault and stage == self.assault['pos']):
            return None
        data = self.estimate_cell(target, 2)
        if data is None:
            return None
        needed = data[2] + 3
        if stage in self.cells and self.cells[stage][1] == self.army:
            have = self.available(stage)
            if target in self.cells and have > self.cells[target][2]:
                return self.action(stage, target, min(have, needed), 'fort', 'take staged producer')
            # Accumulate on the neighboring square, preserving the home garrison.
            return self.gather(stage, 'save reinforcements beside producer', 'fort', limit=max(1, needed - have))
        # Occupy the neighboring empty square early, even before total capture force exists.
        sources = sorted(self.owned, key=lambda p: self.available(p), reverse=True)[:8]
        options = []
        for src in sources:
            if src in (self.scout, self.scout_rear) or (self.assault and src == self.assault['pos']):
                continue
            costs, parent, lengths = self.paths(src)
            route = self.path(parent, stage)
            if not route or len(route) < 2:
                continue
            # Avoid starting a forward march that cannot even reach its staging square.
            loss = sum((1 + self.estimate_cell(p)[2]) if self.estimate_cell(p)[1] != self.army
                       else max(0, 1 - self.estimate_cell(p)[2]) for p in route[1:])
            available = self.available(src)
            if available < max(1, loss):
                continue
            count = min(available, loss + needed)
            options.append((costs[stage] - count * 0.03, src, route, count))
        if options:
            _, src, route, count = min(options)
            return self.step_on(route, count, 'fort', 'occupy empty staging square near producer')
        return None

    def assault_plan(self, source, owner):
        target = self.kings[owner]['pos']
        _, parent, _ = self.paths(source)
        route = self.path(parent, target)
        if route is None or len(route) < 2:
            return None
        steps = len(route) - 1
        prediction = self.predict_king(owner, steps + 2, path_defenders=set(route[1:-1]))
        # A stale king must be scouted again before a committed attack.
        if prediction['age'] > self.KING_MAX_AGE:
            return None
        cost = steps  # at least one unit is left at each departure
        for i, pos in enumerate(route[1:-1], 1):
            kind, belonging, defenders = self.estimate_cell(pos, i)
            if belonging != self.army:
                cost += defenders
        needed = int(cost + prediction['upper'] + max(4, steps * 0.3))
        return dict(route=route, steps=steps, needed=needed, prediction=prediction, owner=owner)

    def assault_action(self):
        if not self.kings:
            self.assault = None
            return None
        if self.assault:
            src, owner = self.assault['pos'], self.assault['owner']
            if src not in self.cells or self.cells[src][1] != self.army:
                self.assault = None
                return None
            plan = self.assault_plan(src, owner)
            if not plan or self.available(src) + 1 < plan['needed']:
                self.assault = None
                self.last_report['abort'] = 'reinforced or stale target; regroup/recon'
                return None
            self.last_report['attack'] = dict(owner=owner, needed=plan['needed'], steps=plan['steps'],
                                               **plan['prediction'])
            return self.step_on(plan['route'], self.available(src), 'assault', 'committed king strike; recalculate each step')
        options = []
        sources = sorted(self.owned, key=lambda p: self.cells[p][2], reverse=True)[:6]
        for src in sources:
            if (src == self.scout or self.home_dist.get(src, 999) > self.RALLY_RADIUS + 1
                    or self.available(src) < 12):
                continue
            for owner in self.kings:
                plan = self.assault_plan(src, owner)
                if not plan:
                    continue
                # Estimate home vulnerability for the entire travel window. Keep
                # observed attacks covered plus a small unseen-threat buffer.
                guard = self.reserve_home(plan['steps'] + 3) + 4 + plan['steps'] // 4
                if src == self.home:
                    available = max(0, self.cells[src][2] - guard)
                else:
                    home_units = self.cells.get(self.home, (0, 0, 0))[2]
                    available = self.available(src) if home_units >= guard else 0
                if available < plan['needed']:
                    continue
                options.append((plan['steps'] + plan['needed'] * 0.02, src, owner, plan, available))
        if options:
            _, src, owner, plan, count = min(options)
            self.assault = dict(pos=src, owner=owner, launched=self.tick)
            self.last_report['attack'] = dict(owner=owner, needed=plan['needed'], steps=plan['steps'],
                                               **plan['prediction'])
            return self.step_on(plan['route'], count, 'assault', 'force and home-window checks passed')
        return None

    def new_sight(self, pos):
        return set(p for p in [pos] + self.neighbors[pos] if p not in self.memory)

    def search_focus(self):
        if self.kings:
            return min(self.kings.values(), key=lambda m: m['seen'])['pos']
        enemy = [p for p, d in getattr(self,"_search_evidence",self.memory).items()
                 if d[1] > 0 and d[1] != self.army]
        if enemy:
            # Move through the observed enemy front, not parallel to it along map edges.
            r = sum(p[0] for p in enemy) / float(len(enemy))
            c = sum(p[1] for p in enemy) / float(len(enemy))
            r += (r - self.home[0]) * 0.4
            c += (c - self.home[1]) * 0.4
            return max(0, min(self.rows - 1, int(r))), max(0, min(self.cols - 1, int(c)))
        # A geographical search PRIOR, not a claim about opponent spawn coordinates.
        # Prefer the opposite interior over repeatedly clearing our own outer edge.
        return self.rows - 1 - self.home[0], self.cols - 1 - self.home[1]

    def scout_action(self, force=False):
        """Compare local launch sites; use spare commands to keep useful recon moving."""
        if (not force and self.tick - self.scout_last < self.SCOUT_INTERVAL) or self.assault:
            return None
        candidates = [self.scout, self.scout_rear, self.regional_hub]
        focus = self.search_focus()
        sources = [p for p in self.owned if self.available(p) >= 1
                   and not (self.assault and self.assault['pos'] == p)]
        sources.sort(key=lambda p: (hex_distance(p, focus), -self.available(p)))
        candidates.extend(sources[:3])
        candidates.extend(sorted(sources, key=lambda p: self.available(p), reverse=True)[:2])
        current = self.scout
        best, best_score = None, -float('inf')
        # Planning has no side effects. Only the selected action becomes pending.
        for source in dict.fromkeys(candidates):
            if source is None or self.available(source) < 1:
                continue
            choice = self.scout_from(source, preview=True)
            if choice and source == current:
                # A viable existing scout owns its task. Comparing fresh long-route
                # progress scores each turn otherwise repeatedly relaunches from home.
                best = choice
                break
            if choice and choice[0] > best_score:
                best_score, best = choice[0], choice
        if best is None:
            return None
        _, route, count, threatened = best
        src = route[0]
        reason = ('enemy can swallow scout: send at most one third, retain rear' if threatened
                  else 'information gain per command and troop loss')
        move = self.step_on(route, count, 'scout', reason)
        if move:
            self.scout_last = self.tick
            if threatened:
                self.scout_rear = src
        return move

    def scout_from(self, source, preview=False):
        # Scouting continues until a route to a fresh king is known. Revisit old
        # observations instead of pretending the old defender count is current.
        fresh = [k for k in self.kings if self.tick - self.kings[k]['seen'] < 20]
        if self.assault:
            return None
        if fresh and self.rally is not None and any(self.assault_plan(self.rally, k) for k in fresh):
            return None
        src = source
        budget = min(self.available(src), self.SCOUT_MAX_BUDGET)
        if budget < 1:
            return None
        _, parent, lengths = self.paths(src)
        focus = self.search_focus()
        enemy_evidence = [p for p, d in getattr(self,"_search_evidence",self.memory).items()
                          if d[1] > 0 and d[1] != self.army]
        king_goals = [k['pos'] for k in self.kings.values()]
        choices = []
        for pos in parent:
            if pos == src:
                continue
            route = self.path(parent, pos)
            if len(route) > 18:
                continue
            unknown = self.new_sight(pos)
            info = len(unknown)
            hill_gain = len(unknown & self.hill_hints)
            revisit = max((12.0 / (1 + hex_distance(pos, k)) for k in king_goals), default=0)
            if not info and revisit < 4:
                continue
            loss = 0
            for step, cell in enumerate(route[1:], 1):
                data = self.estimate_cell(cell, step)
                loss += (1 + data[2]) if data[1] != self.army else max(0, 1 - data[2])
            if loss > budget:
                continue
            enemy_distance = min((hex_distance(pos, p) for p in enemy_evidence), default=0)
            depth = hex_distance(pos, self.home) - hex_distance(src, self.home) if self.home else 0
            progress = hex_distance(src, focus) - hex_distance(pos, focus)
            score = (info * 5 + hill_gain * 8 + revisit + max(-3, min(5, depth)) * 1.2
                     + progress * 5) / (1 + lengths[pos] * 0.3 + loss * 0.12)
            score += 24.0 / (1 + hex_distance(pos, focus))
            # Absolute position matters when comparing different launch sites.
            score -= hex_distance(pos, focus) * 0.65
            if src == self.scout:
                score += 3.0  # continue a useful scout instead of creating many fragments
            if enemy_evidence:
                score += 9.0 / (1 + enemy_distance)
            score -= self.visits.get(pos, 0) * 2
            # Avoid walking a tiny scout next to an army that can eat it immediately.
            danger = max((self.cells[n][2] for n in self.neighbors[pos]
                          if n in self.cells and self.cells[n][1] > 0 and self.cells[n][1] != self.army), default=0)
            score -= min(15, danger * 0.5)
            choices.append((score, route, max(loss + 2, min(budget, 8))))
        if not choices:
            return None
        # Compare alternate low-loss routes before accepting a dangerous probing move.
        for score, route, count in sorted(choices, key=lambda x: x[0], reverse=True):
            dst = route[1]
            if dst not in self.cells or self.tick - self.scout_losses.get(dst, -99) < 20:
                continue
            count = budget if src == self.scout else min(budget, count)
            kind, owner, guards = self.cells[dst]
            guards = guards if owner != self.army else 0
            counter = max((max(0, self.cells[n][2] - 1) for n in self.neighbors[dst]
                           if n in self.cells and self.cells[n][1] > 0
                           and self.cells[n][1] != self.army), default=0)
            threatened = counter >= max(1, count - guards)
            if threatened:
                count = min(count, self.available(src) // 3)
                # Leave two on the forward square so a future scout can still move.
                # If one-third cannot break through, try another route or wait.
                if count <= guards + 1:
                    continue
            if count <= guards:
                continue
            return score, route, count, threatened
        return None

    def local_expand(self, unrestricted=False):
        options = []
        producers = [p for p in self.owned if self.cells[p][0] in (KING, FORT)]
        for src in self.owned:
            if (src == self.scout_rear or (src == self.scout and not unrestricted)
                    or (self.assault and src == self.assault['pos'])):
                continue
            available = self.available(src)
            if available < 1:
                continue
            for dst in self.neighbors[src]:
                if dst not in self.cells or self.cells[dst][0] in BLOCKED:
                    continue
                kind, owner, units = self.cells[dst]
                if kind != BLANK or owner != 0 or units > 1 or available <= units:
                    continue
                radius = min((hex_distance(dst, p) for p in producers), default=99)
                if not unrestricted and radius > (4 if len(self.owned) < 30 else 2):
                    continue
                if not unrestricted and len(self.owned) > 60:
                    continue
                # Expansion is a one/two-soldier claim from the boundary, not a squad.
                send = units + 1
                counter = max((max(0, self.cells[n][2] - 1) for n in self.neighbors[dst]
                               if n in self.cells and self.cells[n][1] > 0
                               and self.cells[n][1] != self.army), default=0)
                if counter >= send:
                    continue
                sight = self.new_sight(dst)
                score = len(sight) * 2.5 + len(sight & self.hill_hints) * 6
                score += min(10, self.home_dist.get(src, 10)) * 0.6 - radius * 0.25
                score += 7 if len(self.owned) < 10 else 0
                score -= self.visits.get(dst, 0)
                options.append((score, src, dst, send))
        for _, src, dst, count in sorted(options, reverse=True):
            result = self.action(src, dst, count, 'expand', 'peripheral one/two-soldier claim; keep main force together')
            if result:
                if src == self.scout:
                    self.scout = None  # no useful recon route; release this group to territory tasks
                return result
        return None

    def decide(self, cells, hill_hints=None):
        self.update(cells, hill_hints=hill_hints)
        return self.decide_observed()

    def decide_observed(self):
        if not self.owned or self.home is None:
            return None
        if self.pending:
            self.last_report['mode'] = 'await_action'
            return None
        self.select_rally()
        if self.kings and self.rally is not None:
            plans = [self.assault_plan(self.rally, owner) for owner in self.kings]
            plans = [plan for plan in plans if plan is not None]
            if plans:
                travel = min(plan['steps'] for plan in plans)
                # This floor applies to ALL outgoing moves, including later gather.
                # Otherwise guard->rally->guard would oscillate forever.
                self.home_keep = max(self.home_keep, self.reserve_home(travel + 3) + 4 + travel // 4)
                self.last_report['home_keep'] = self.home_keep
        move = self.direct_objective(kings_only=True)
        if move:
            return move
        move = self.defend()
        if move:
            return move
        move = self.assault_action()
        if move:
            return move
        move = self.direct_objective()
        if move:
            return move
        move = self.economy.guard_action(self)
        if move:
            return move
        move = self.economy.raid_action(self)
        if move:
            return move
        self.choose_fort()
        if self.fort:
            move = self.fort_action()
            if move:
                return move
        if self.tick - self.scout_last >= self.SCOUT_INTERVAL:
            move = self.scout_action()
            if move:
                return move
        if len(self.owned) < 10:
            move = self.local_expand()
            if move:
                return move
        # Before launch, place the required static reserve on the home king.
        if self.kings and self.rally != self.home:
            if self.cells[self.home][2] < self.home_keep:
                move = self.gather(self.home, 'prepare guard for strike window', 'guard',
                                   limit=self.home_keep - self.cells[self.home][2])
                if move:
                    return move
        if self.EVERY_STEP or self.tick % 3 == 0 or (self.scout is None and self.tick % 2 == 0):
            move = self.regional_action()
            if move:
                return move
        if self.EVERY_STEP or self.tick % 3 != 0 or self.kings:
            exclusions = [self.fort['stage']] if self.fort else []
            move = self.gather(self.rally, 'consolidate into near-king rally', exclude=exclusions)
            if move:
                return move
        move = self.scout_action(force=True)
        if move:
            return move
        move = self.local_expand(unrestricted=True)
        if move:
            return move
        self.last_report.update(mode='save', rally=self.rally, fort=self.fort,
                                kings={k: self.predict_king(k) for k in self.kings})
        return None
