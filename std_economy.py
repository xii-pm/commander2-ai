"""Visible-information economy helpers, Python 3.6, no SDK or strategy import.

Integration contract:
* Construct Economy(army) once per game.
* In Agent.update, save old_cells and pending endpoints BEFORE resolving pending.
  After cells/memory/home/home_dist are refreshed, call observe(bot, old_cells,
  touched). All economy queries then refer to that observation.
* In Agent.available, include reserves(bot).get(src, 1) in the existing reserve
  maximum. This prevents ordinary transport from undoing a fort guard order.
* Call guard_action/raid_action after immediate defence and active assaults.
  Both return an ordinary bot.action result or None; they never send SDK moves.

A phase is an estimate anchored to a witnessed plain-growth pulse, never the
callback count modulo 50. Missing evidence expires it instead of wrapping it.
"""
from collections import deque

BLANK, KING, FORT, HILL, OBSTACLE, MARSH = range(1, 7)
BLOCKED = (HILL, OBSTACLE)


class Economy:
    PERIOD = 50
    LATE_WINDOW = 8
    MIN_WITNESSES = 3
    MAX_STEP_GAP = 4
    MAX_UNCERTAINTY = 4
    MAX_UNWITNESSED = 12
    MAX_OBSERVATIONS = 55
    TOUCH_COOLDOWN = 2
    GUARD_RADIUS = 3
    BASE_GUARD = 1
    MAX_RAID_FORCE = 6

    def __init__(self, army):
        self.army = army
        self._sequence = 0
        self._last_tick = None
        self._pulse_tick = None
        self._pulse_sequence = None
        self._valid_clock = False
        self._uncertainty = 1
        self._unwitnessed = 0
        self._recent_touched = {}
        self._witnesses = 0
        self._eligible = 0
        self._reason = 'no witnessed plain-growth pulse'
        self._cluster_key = None
        self._clusters = {}
        self._reserve_cache_key = None
        self._reserve_cache = {}

    @staticmethod
    def _distances(bot, start, allowed, limit=None):
        distance = {start: 0}
        queue = deque([start])
        while queue:
            pos = queue.popleft()
            if limit is not None and distance[pos] >= limit:
                continue
            for nxt in bot.neighbors.get(pos, ()):
                if nxt not in distance and allowed(nxt):
                    distance[nxt] = distance[pos] + 1
                    queue.append(nxt)
        return distance

    def _safe_witness(self, bot, pos, old_cells):
        for nxt in bot.neighbors.get(pos, ()):
            before, after = old_cells.get(nxt), bot.cells.get(nxt)
            # Unknown neighbours do not prove absence of an enemy. In the real
            # SDK the neighbourhood of continuously owned ground is visible.
            if (before is None or after is None or
                    before[1] not in (0, self.army) or after[1] not in (0, self.army)):
                return False
        return True

    def observe(self, bot, old_cells, touched=()):
        """Observe one completed update; touched includes both pending endpoints.

        The pulse denominator includes ALL eligible stable plains, not just the
        tiles that gained a unit. A touched square remains excluded for two more
        observations, covering delayed movement confirmation.
        """
        self._sequence += 1
        tick = int(bot.tick)
        delta = 1 if self._last_tick is None else tick - self._last_tick
        if delta < 0 or delta > self.MAX_STEP_GAP:
            self._valid_clock = False
            self._reason = 'observation gap or clock reset'
        elif delta > 1 and self._valid_clock:
            self._uncertainty += 1
            if self._uncertainty > self.MAX_UNCERTAINTY:
                self._valid_clock = False
                self._reason = 'too much timing uncertainty'
        self._last_tick = tick
        self._recent_touched = {p: until for p, until in self._recent_touched.items()
                                if until >= self._sequence}
        for pos in touched or ():
            self._recent_touched[pos] = self._sequence + self.TOUCH_COOLDOWN

        eligible, gained = [], []
        for pos, data in bot.cells.items():
            before = old_cells.get(pos)
            if (data[0] != BLANK or data[1] != self.army or before is None or
                    before[0] != BLANK or before[1] != self.army or
                    pos in self._recent_touched or not self._safe_witness(bot, pos, old_cells)):
                continue
            eligible.append(pos)
            if data[2] - before[2] == 1:
                gained.append(pos)
        self._eligible, self._witnesses = len(eligible), len(gained)
        if len(eligible) < self.MIN_WITNESSES:
            self._unwitnessed += 1
        else:
            self._unwitnessed = 0
        if self._unwitnessed > self.MAX_UNWITNESSED:
            self._valid_clock = False
            self._reason = 'continuous plain observations lost'

        pulse = (len(gained) >= self.MIN_WITNESSES and
                 len(gained) * 5 >= len(eligible) * 3)
        if pulse:
            separated = self._pulse_tick is None or tick - self._pulse_tick >= 40
            if 0 < delta <= self.MAX_STEP_GAP and separated:
                self._pulse_tick, self._pulse_sequence = tick, self._sequence
                # The event happened between observations. Keep at least one
                # step of uncertainty even with an apparently normal callback.
                self._uncertainty = max(1, delta)
                self._valid_clock = True
                self._unwitnessed = 0
                self._reason = 'synchronized safe plain growth'
            else:
                self._valid_clock = False
                self._reason = 'pulse timing ambiguous or implausibly repeated'
        self._refresh_clusters(bot)
        return self.phase_info(bot)

    def phase_info(self, bot):
        """Return known/phase/remaining/late plus explicit estimation metadata.

        known means a usable recent calibration, NOT an exact native step.
        No extrapolation is made past a possibly missed next growth pulse.
        """
        info = dict(known=False, phase=None, remaining=None, late=False,
                    estimated=True, exact=False, uncertainty=self._uncertainty,
                    phase_range=None, remaining_range=None,
                    witnesses=self._witnesses, eligible=self._eligible,
                    calibrated_at=self._pulse_tick, reason=self._reason)
        if not self._valid_clock or self._pulse_tick is None:
            return info
        if int(bot.tick) != self._last_tick:
            info['reason'] = 'current update has not been observed'
            return info
        elapsed = int(bot.tick) - self._pulse_tick
        age = self._sequence - self._pulse_sequence
        upper = elapsed + self._uncertainty
        if elapsed < 0 or upper >= self.PERIOD or age > self.MAX_OBSERVATIONS:
            info['reason'] = 'calibration expired before another witnessed pulse'
            return info
        info.update(known=True, phase=elapsed, remaining=self.PERIOD - elapsed,
                    phase_range=(elapsed, upper),
                    remaining_range=(self.PERIOD - upper, self.PERIOD - elapsed),
                    late=elapsed >= self.PERIOD - self.LATE_WINDOW)
        return info

    def _refresh_clusters(self, bot):
        forts = frozenset(p for p, d in bot.cells.items()
                          if d[0] == FORT and d[1] == self.army)
        if forts == self._cluster_key:
            return
        previous_centers = set(self._clusters)
        unassigned, clusters = set(forts), {}
        while unassigned:
            start = min(unassigned)
            component = frozenset(self._distances(bot, start, lambda p: p in forts))
            unassigned.difference_update(component)
            choices = []
            for pos in component:
                distance = self._distances(bot, pos, lambda p: p in component)
                choices.append((max(distance.values()), sum(distance.values()),
                                0 if pos in previous_centers else 1, pos))
            center = min(choices)[-1]
            clusters[center] = component
        self._cluster_key, self._clusters = forts, clusters

    def reserves(self, bot):
        """Estimate visible enemy pressure at owned-fort cluster centers.

        Outer forts retain the ordinary one-unit minimum. For a center, visible
        stacks within GUARD_RADIUS passable steps contribute their current
        force and growth. Under the usual one-command-per-update agent pattern,
        stacks from the same owner share a GUARD_RADIUS-command budget; owners
        are budgeted independently. This is a threat estimate, not a server
        enforced limit on PushMove calls.
        """
        self._refresh_clusters(bot)
        # Agent.available can ask hundreds of times during one decision. Threat
        # radii need recomputing only for a new observation/topology, not per donor.
        cache_key = (id(bot.cells), bot.tick, self._cluster_key)
        if cache_key == self._reserve_cache_key:
            return dict(self._reserve_cache)
        result = {}
        command_budget = self.GUARD_RADIUS
        for center in self._clusters:
            distance = self._distances(
                bot, center, lambda p: p in bot.cells and bot.cells[p][0] not in BLOCKED,
                self.GUARD_RADIUS)
            by_owner = {}
            for pos, steps in distance.items():
                kind, owner, units = bot.cells[pos]
                if owner <= 0 or owner == self.army:
                    continue
                growth = ((self.GUARD_RADIUS - steps + 1) // 2
                          if kind in (KING, FORT) else 0)
                force = max(0, units - steps) + growth
                by_owner.setdefault(owner, []).append((steps, force))
            incoming = 0
            for arrivals in by_owner.values():
                best = [0] * (command_budget + 1)
                for steps, force in arrivals:
                    cost = max(1, int(steps))
                    if cost > command_budget or force <= 0:
                        continue
                    for budget in range(command_budget, cost - 1, -1):
                        best[budget] = max(best[budget],
                                           best[budget - cost] + force)
                incoming += max(best)
            result[center] = max(self.BASE_GUARD, incoming + 2 if incoming else 0)
        self._reserve_cache_key, self._reserve_cache = cache_key, result
        return dict(result)

    @staticmethod
    def _protected(bot):
        result = set(bot.protected()) if hasattr(bot, 'protected') else set()
        result.update((getattr(bot, 'scout', None), getattr(bot, 'scout_rear', None)))
        if getattr(bot, 'assault', None):
            result.add(bot.assault['pos'])
        if getattr(bot, 'fort', None):
            result.add(bot.fort.get('stage'))
        result.discard(None)
        return result

    def guard_action(self, bot, urgent_only=False):
        """Concentrate local surplus on an under-strength fort-cluster center.

        During an assault, only allow an urgent response when a visible adjacent
        enemy can outnumber the fort center's current garrison.
        """
        assault = getattr(bot, 'assault', None)
        if (getattr(bot, 'pending', None) or
                (assault and not urgent_only) or
                (urgent_only and not assault)):
            return None
        home = getattr(bot, 'home', None)
        if (home in bot.cells and
                bot.cells[home][2] < getattr(bot, 'home_keep', 1)):
            return None
        reserves = self.reserves(bot)
        protected = self._protected(bot)
        urgent_reserves = None
        if urgent_only:
            urgent_reserves = {}
            for center in reserves:
                current = bot.cells[center][2]
                incoming_by_owner = {}
                can_capture = False
                for nxt in bot.neighbors.get(center, ()):
                    data = bot.cells.get(nxt)
                    if data is None:
                        continue
                    kind, owner, units = data
                    if owner <= 0 or owner == self.army:
                        continue
                    growth = 1 if kind in (KING, FORT) else 0
                    possible_force = max(0, units - 1) + growth
                    incoming_by_owner[owner] = max(
                        incoming_by_owner.get(owner, 0), possible_force)
                    if possible_force > current:
                        can_capture = True
                if not can_capture:
                    continue
                adjacent_incoming = sum(incoming_by_owner.values())
                keep = max(self.BASE_GUARD, adjacent_incoming + 2)
                if keep > current:
                    urgent_reserves[center] = keep
            if not urgent_reserves:
                return None
        target_reserves = urgent_reserves if urgent_only else reserves
        choices = sorted((keep - bot.cells[p][2], p)
                         for p, keep in target_reserves.items()
                         if keep > bot.cells[p][2] and p not in protected)
        for need, center in reversed(choices):
            distance = self._distances(
                bot, center, lambda p: p in bot.cells and bot.cells[p][1] == self.army,
                self.GUARD_RADIUS)
            excluded = set(protected) | (set(reserves) - {center})
            excluded.update(p for p, d in bot.cells.items()
                            if d[1] == self.army and p not in distance)
            # Existing gather respects home_keep, scout, rear and assault locks.
            move = bot.gather(center, 'urgent local defense for threatened fort'
                              if urgent_only else 'local reserve for fort cluster center',
                              role='fort_guard', limit=need, exclude=excluded)
            if move:
                return move
        return None

    def _counter_force(self, bot, pos, ignored=()):
        # Each enemy army can issue one neighbouring attack per step. Different
        # armies may attack in succession. Allow a growth unit before that move.
        by_owner = {}
        for nxt in bot.neighbors.get(pos, ()):
            data = bot.cells.get(nxt)
            if nxt in ignored or data is None or data[1] <= 0 or data[1] == self.army:
                continue
            kind, owner, units = data
            growth = 1 if kind in (BLANK, KING, FORT) else 0
            by_owner[owner] = max(by_owner.get(owner, 0), max(0, units + growth - 1))
        return sum(by_owner.values())

    def _owned_components(self, bot):
        owned = set(p for p, d in bot.cells.items() if d[1] == self.army)
        components = {}
        index = 0
        while owned:
            start = min(owned)
            part = self._distances(bot, start, lambda p: p in owned)
            for pos in part:
                components[pos] = index
            owned.difference_update(part)
            index += 1
        return components

    def _visible_enemy_cut(self, bot, target):
        """Count separated visible enemy road branches if this tile is removed.

        This values interruption of OBSERVED same-army roads. Unseen detours and
        routes through neutral ground can exist, so it is not a blockade claim.
        """
        owner = bot.cells[target][1]
        adjacent = set(p for p in bot.neighbors.get(target, ())
                       if p in bot.cells and bot.cells[p][1] == owner
                       and bot.cells[p][0] not in BLOCKED)
        if len(adjacent) < 2:
            return 0
        groups = 0
        while adjacent:
            start = min(adjacent)
            connected = self._distances(
                bot, start, lambda p: p != target and p in bot.cells
                and bot.cells[p][1] == owner and bot.cells[p][0] not in BLOCKED)
            adjacent.difference_update(connected)
            groups += 1
        return max(0, groups - 1)

    def _raid_value(self, bot, target, components):
        owner = bot.cells[target][1]
        distance = self._distances(
            bot, target, lambda p: p in bot.cells and bot.cells[p][0] not in BLOCKED, 4)
        producer_value = max((30.0 / (1 + steps) for p, steps in distance.items()
                              if bot.cells[p][0] in (KING, FORT) and bot.cells[p][1] == owner),
                             default=0.0)
        adjacent = bot.neighbors.get(target, ())
        links = set(components[p] for p in adjacent if p in components)
        road = sum(p in bot.cells and bot.cells[p][0] not in BLOCKED for p in adjacent)
        memory = getattr(bot, 'memory', {})
        sight = sum(p not in memory for p in [target] + list(adjacent))
        visits = getattr(bot, 'visits', {}).get(target, 0)
        disruption = 9 * min(3, self._visible_enemy_cut(bot, target))
        return (14 + producer_value + 8 * max(0, len(links) - 1) + disruption
                + min(road, 4) + sight - min(4, visits))

    def raid_action(self, bot):
        """Take a weak visible enemy plain in a calibrated late production window.

        Economic raids are small adjacent captures, never assault interruptions.
        One extra defender is budgeted for an intervening growth pulse, and both
        the destination and the source must survive visible adjacent counterplay.
        """
        phase = self.phase_info(bot)
        if (not phase['known'] or not phase['late'] or getattr(bot, 'pending', None)
                or getattr(bot, 'assault', None)):
            return None
        reserves, protected = self.reserves(bot), self._protected(bot)
        components, choices = self._owned_components(bot), []
        for target, (kind, owner, units) in bot.cells.items():
            if kind != BLANK or owner <= 0 or owner == self.army or units > 2:
                continue
            counter = self._counter_force(bot, target)
            # guards + possible growth + enough survivors to beat the counter.
            sent = units + 2 + counter
            if sent > self.MAX_RAID_FORCE:
                continue
            value = self._raid_value(bot, target, components) - sent * 1.5
            for src in bot.neighbors.get(target, ()):
                source = bot.cells.get(src)
                if source is None or source[1] != self.army or src in protected:
                    continue
                keep = max(2, reserves.get(src, 1),
                           self._counter_force(bot, src, ignored=(target,)) + 1)
                available = min(bot.available(src), max(0, source[2] - keep))
                if available < sent:
                    continue
                choices.append((value, src, target, sent))
        if not choices:
            return None
        _, src, target, sent = max(choices)
        return bot.action(src, target, sent, 'deny_growth',
                          'observed late plain-growth window; reserve counterattack and growth margin')
