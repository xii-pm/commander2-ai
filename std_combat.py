"""Combat methods preserved from the frozen BFS hunter."""
import math
from std_geometry import BLANK, KING, FORT, MARSH, BLOCKED, hex_distance


class Combat:
    def available(self, src, keep=None):
        if src not in self.cells or self.cells[src][1] != self.army:
            return 0
        home_reserve = self.home_keep if src == self.home else 1
        if src == self.home:
            home_reserve = max(home_reserve, self.home_guard_hold())
        reserve = max(1, self.fort_reserves.get(src, 1), home_reserve)
        if keep is not None:
            reserve = max(reserve, keep)
        return max(0, self.cells[src][2] - reserve)

    def action(self, src, dst, count, role, reason, advance=False):
        if (self.pending or src not in self.cells or dst not in self.cells
                or self.cells[src][1] != self.army or dst not in self.neighbors[src]
                or self.cells[dst][0] in BLOCKED):
            return None
        # Central enforcement: ordinary tasks cannot accidentally drain guards.
        cap = self.cells[src][2] - 1 if role == 'defend' and src != self.home else self.available(src)
        count = int(min(count, cap))
        if count <= 0 or (self.cells[dst][1] != self.army and count <= self.cells[dst][2]):
            return None
        self.pending = dict(src=src, dst=dst, sent=count, role=role, tick=self.tick,
                            before_src=self.cells[src], before_dst=self.cells[dst], advance=advance)
        self.last_report.update(mode=role, src=src, dst=dst, send=count, reason=reason)
        return src, dst, count

    def counter(self, pos, excluded=()):
        # One adjacent move per opponent; different opponents may attack in succession.
        cache = getattr(self, '_counter_cache', None)
        key = (pos, tuple(excluded))
        if cache is not None and key in cache:
            return cache[key]
        excluded = key[1]
        by_owner = {}
        for n in self.neighbors[pos]:
            if n in excluded or n not in self.cells:
                continue
            kind, owner, units = self.cells[n]
            if owner > 0 and owner != self.army:
                by_owner[owner] = max(by_owner.get(owner, 0), units)  # includes one growth margin
        result = sum(by_owner.values())
        if cache is not None:
            cache[key] = result
        return result

    def predict_king(self, owner, travel=0, excluded=()):
        model = self.kings[owner]
        age = self.tick - model['seen']
        saving = model['samples'] >= 4 and model['saving'] >= 0.7 * model['samples']
        estimate = model['units'] + int(math.ceil(max(0.52, model['rate']) * (age + travel)))
        uncertainty = 2 + int(math.ceil(age * (0.1 if saving else 0.35) + travel * 0.15))
        flank = sum(max(0, self.cells[p][2] - 1) for p in self.enemies
                    if p != model['pos'] and p not in excluded and self.cells[p][1] == owner
                    and hex_distance(p, model['pos']) <= travel + 1)
        return dict(expected=estimate, upper=estimate + uncertainty + flank, age=age,
                    uncertainty=uncertainty, reinforcements=flank)

    def immediate_capture(self, kings_only=False, enemy_only=False, neutral_only=False,
                          empty_only=False):
        choices = []
        for dst, (kind, owner, units) in self.cells.items():
            if (owner == self.army or (enemy_only and owner == 0)
                    or (neutral_only and owner != 0)
                    or (empty_only and units > 0)
                    or kind not in ((KING,) if kings_only else (FORT,))):
                continue
            for src in self.neighbors[dst]:
                assault_surplus_capture = bool(
                    enemy_only and kind == FORT and owner > 0 and units == 0
                    and self.assault and self.mission['pos'] == src)
                mission_capture = bool(
                    (enemy_only or neutral_only) and self.mission
                    and self.mission['pos'] == src
                    and self.mission['kind'] != 'assault')
                if mission_capture and neutral_only:
                    mission_target = self.mission.get('target')
                    mission_capture = bool(mission_target is not None
                                           and hex_distance(dst, mission_target)
                                           < hex_distance(src, mission_target))
                if (kind == FORT and src in self.protected()
                        and not mission_capture and not assault_surplus_capture):
                    continue
                have = self.available(src)
                empty_fort = kind == FORT and units == 0
                if kind == KING:
                    needed = units + 1
                    count = have
                elif empty_fort:
                    retaliation = self.counter(dst, excluded=(dst,))
                    needed = retaliation + 1
                    count = needed
                else:
                    # Preserve R50's proven margin against growing/defended forts.
                    needed = units + 1 + (1 if owner > 0 else 0)
                    count = min(have, needed + 2)
                if have < needed:
                    continue
                if empty_fort and self.counter(src, excluded=(dst,)) > self.cells[src][2] - count:
                    continue
                if assault_surplus_capture:
                    assault_plan = self.best_plan(src, self.mission['target'])
                    if (not assault_plan
                            or have - count < assault_plan['needed']):
                        continue
                enemy_priority = 0 if owner > 0 else 1
                leverage = self.network_leverage(dst) if kind == FORT else 0
                choices.append((enemy_priority, 0 if empty_fort else 1, -leverage,
                                units, src, dst, count, kind, owner,
                                assault_surplus_capture, mission_capture))
        for (_, _, _, units, src, dst, count, kind, owner,
             assault_surplus_capture, mission_capture) in sorted(choices):
            move = self.action(src, dst, count, 'capture', 'adjacent king' if kings_only else 'cheap producer',
                               advance=bool(self.mission and self.mission['pos'] == src
                                            and not assault_surplus_capture))
            if move:
                if kind == FORT and units == 0:
                    self.last_report.update(empty_fort_capture=True,
                                            empty_fort_owner=owner,
                                            empty_fort_sent=count,
                                            empty_fort_retaliation=self.counter(dst, excluded=(dst,)))
                if assault_surplus_capture:
                    self.last_report['assault_surplus_capture'] = True
                return move
        return None

    def counter_raid_action(self):
        """Take a weak enemy plain when the captured tile can survive retaliation.

        The baseline captures forts but leaves ordinary enemy territory alone.
        A small, guarded raid denies a growth tile and opens fresh vision without
        diverting the committed field army or spending an unsafe source garrison.
        """
        if (self.pending or self.assault or
                self.tick - self.counter_raid_last < self.COUNTER_RAID_INTERVAL):
            return None
        focus = self.focus()
        choices = []
        for dst in self.enemies:
            kind, owner, guards = self.cells[dst]
            if kind not in (BLANK, MARSH) or owner in self.eliminated:
                continue
            counter = self.counter(dst, excluded=(dst,))
            # Two spare troops cover strict capture and one plausible reply.
            sent = guards + counter + 2
            for src in self.neighbors[dst]:
                if src in self.protected():
                    continue
                available = self.available(src)
                if available < sent:
                    continue
                remaining = self.cells[src][2] - sent
                # The destination's defenders become ours after a successful raid;
                # do not count them as a threat against the source afterwards.
                if self.counter(src, excluded=(dst,)) > remaining:
                    continue
                progress = hex_distance(src, focus) - hex_distance(dst, focus)
                nearby_producer = max(
                    (18.0 / (1 + hex_distance(dst, p))
                     for p, data in self.memory.items()
                     if data[1] == owner and data[0] in (KING, FORT)), default=0.0)
                sight = len(self.new_sight(dst))
                value = (10.0 + sight * 2.5 + self.network_leverage(dst) * 0.6
                         + progress * 1.5 + nearby_producer
                         - self.visits.get(dst, 0) * 2.0)
                efficiency = value / (1.0 + sent * 0.035)
                if efficiency >= 5.0:
                    choices.append((efficiency, value, -sent, src, dst, sent))
        if not choices:
            return None
        _, _, _, src, dst, sent = max(choices)
        move = self.action(src, dst, sent, 'counter_raid',
                           'capture exposed enemy land and deny its expansion')
        if move:
            self.counter_raid_last = self.tick
        return move
