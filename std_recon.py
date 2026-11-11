"""Recon methods preserved from the frozen BFS hunter."""
from std_geometry import BLOCKED, hex_distance


def search_evidence_active(bot):
    config = getattr(bot,"config",{})
    return (config.get("first_contact_search",False)
            and (not config.get("search_takeover_only",False)
                 or getattr(bot,"_search_transfer_seen",False)))


def first_contact_search_active(bot):
    return (search_evidence_active(bot)
            and not getattr(bot,"config",{}).get("search_transfer_filter",False))


def search_memory(bot):
    if (search_evidence_active(bot)
            and bot.config.get("search_transfer_filter",False)):
        view = None
        for p, original in bot.first_seen.items():
            latest = bot.memory.get(p)
            origin = getattr(bot,"first_enemy_seen",{}).get(p,original)
            if (latest and origin[1] > 0 and origin[1] != bot.army
                    and latest[1] > 0 and latest[1] != bot.army
                    and origin[1] != latest[1]):
                if view is None:
                    view = dict(bot.memory)
                view[p] = (original[0],origin[1],original[2],latest[3])
        return bot.memory if view is None else view
    if first_contact_search_active(bot):
        if len(bot.first_seen) == len(bot.memory):
            return bot.first_seen
        view = dict(bot.memory)
        view.update(bot.first_seen)
        return view
    return bot.memory


class Recon:
    def search_memory(self):
        return search_memory(self)

    def new_sight(self, p):
        cache = getattr(self, '_sight_cache', None)
        if cache is None:
            return {n for n in [p] + self.neighbors[p] if n not in self.memory}
        if p not in cache:
            cache[p] = {n for n in [p] + self.neighbors[p] if n not in self.memory}
        return cache[p]

    def hill_hint_approach(self, src, dst):
        if not self.hill_hints:
            return 0
        source_distance = min(hex_distance(src, hint) for hint in self.hill_hints)
        target_distance = min(hex_distance(dst, hint) for hint in self.hill_hints)
        return max(0, source_distance - target_distance)

    def hill_hint_approach_weight(self):
        # Keep the light gradient for both seats; R77 gained territory and held a draw.
        return self.HILL_HINT_APPROACH_WEIGHT

    def king_route_limit(self):
        # Static generated maps are 24x24; 4/3 of the side length covers the
        # observed p95 (24) and worst connected king route (32), within MAX_ROUTE.
        return min(self.MAX_ROUTE,
                   max(14, min(self.rows, self.cols) * self.KING_ROUTE_SCALE_NUM // self.KING_ROUTE_SCALE_DEN))

    def focus(self):
        if self.kings:
            origin = self.mission['pos'] if self.mission else self.home
            distance = self.routes(origin)[1] if origin else {}
            candidates = []
            for owner, model in self.kings.items():
                age = self.tick - model['seen']
                travel = distance.get(model['pos'], hex_distance(origin, model['pos']) if origin else 20)
                prediction = self.predict_king(owner, min(self.king_route_limit(), travel))
                score = prediction['upper'] + 3 * travel + 0.5 * age
                candidates.append((score, travel, model['pos']))
            return min(candidates)[-1]
        unknown = self.known_owners - self.eliminated - set(self.kings)
        regions = []
        origin = self.mission['pos'] if self.mission else self.home
        for owner in unknown:
            territory = [(p, data) for p, data in self.search_memory().items() if data[1] == owner]
            if not territory:
                continue
            latest = max(data[3] for _, data in territory)
            distance = min((hex_distance(origin, p) for p, _ in territory), default=999)
            r = sum(p[0] for p, _ in territory) / float(len(territory))
            c = sum(p[1] for p, _ in territory) / float(len(territory))
            target = (max(0, min(self.rows - 1, int(r + (r - self.home[0]) * 0.4))),
                      max(0, min(self.cols - 1, int(c + (c - self.home[1]) * 0.4))))
            regions.append((latest, distance, owner, target))
        if regions:
            return min(regions)[-1]
        enemies = [p for p, d in self.search_memory().items()
                   if d[1] > 0 and d[1] != self.army and d[1] not in self.eliminated]
        if enemies:
            r = sum(p[0] for p in enemies) / float(len(enemies))
            c = sum(p[1] for p in enemies) / float(len(enemies))
            return (max(0, min(self.rows - 1, int(r + (r - self.home[0]) * 0.4))),
                    max(0, min(self.cols - 1, int(c + (c - self.home[1]) * 0.4))))
        return self.rows - 1 - self.home[0], self.cols - 1 - self.home[1]

    def refresh_stale_king(self, src, target):
        """Send a capped probe to revisit stale terrain around a known king."""
        sources = []
        for p in (self.scout, src):
            if p in self.owned and p not in sources:
                sources.append(p)
        choices = []
        for origin in sources:
            available = self.available(origin)
            count = min(self.RECON_UNIT_CAP,
                        available if origin == self.scout else available // 3)
            if count < 2:
                continue
            parent, distance = self.routes(origin)
            for pos in parent:
                if pos == origin or hex_distance(pos, target) > 2:
                    continue
                area = set([pos] + self.neighbors[pos])
                stale = {p for p in area if p not in self.memory or
                         self.tick - self.memory[p][3] >= self.RECON_MEMORY_AGE}
                if not stale:
                    continue
                route = self.path(parent, pos)
                if not route or len(route) < 2 or len(route) > self.RECON_ROUTE_LIMIT:
                    continue
                first = route[1]
                if first not in self.cells or self.cells[first][0] in BLOCKED:
                    continue
                kind, owner, guards = self.cells[first]
                progress = hex_distance(origin, target) - hex_distance(first, target)
                if progress <= 0:
                    continue
                if owner != self.army and count <= guards:
                    continue
                resident = guards if owner == self.army else 0
                if count + resident <= self.counter(first, excluded=(first,)) + 1:
                    continue
                score = len(stale) * 8 + len(stale & self.hill_hints) * 5
                score += progress * 8
                score -= distance[pos] * 3 + hex_distance(pos, target) * 4
                choices.append((score, origin, first, count))
        for _, origin, dst, count in sorted(choices, reverse=True):
            move = self.action(origin, dst, count, 'scout',
                               'refresh stale king-area intelligence with a capped probe')
            if move:
                self.scout_rear, self.rear_until = origin, self.tick + 12
                self.probe_last = self.tick
                return move
        return None

    def advance_king_scout(self, target):
        """Move a capped probe through visible frontier toward a known king."""
        if (not self.EVERY_STEP and self.tick - self.probe_last < 8):
            return None
        protected = self.protected()
        sources = sorted((p for p in self.owned
                          if p not in protected and self.available(p) >= 2),
                         key=lambda p: (hex_distance(p, target), -self.available(p), p))[:12]
        choices = []
        for src in sources:
            available = self.available(src)
            cap = min(self.RECON_UNIT_CAP, available)
            if cap < 2:
                continue
            for dst in self.neighbors[src]:
                if dst not in self.cells:
                    continue
                kind, owner, guards = self.cells[dst]
                if kind in BLOCKED:
                    continue
                progress = hex_distance(src, target) - hex_distance(dst, target)
                if progress <= 0:
                    continue
                counter = self.counter(dst, excluded=(dst,))
                if owner == self.army:
                    count = cap
                    if self.cells[dst][2] + count <= counter + 1:
                        continue
                else:
                    count = guards + counter + 2
                    if count > cap:
                        continue
                remaining = self.cells[src][2] - count
                if self.counter(src, excluded=(dst,)) > remaining:
                    continue
                sight = self.new_sight(dst)
                score = progress * 40 + len(sight) * 3
                score += len(sight & self.hill_hints) * 2
                score -= guards * 0.5 + counter * 1.5 + self.visits.get(dst, 0) * 2
                if src == self.scout:
                    score += 8
                choices.append((score, -hex_distance(dst, target), src, dst, count))
        for _, _, src, dst, count in sorted(choices, reverse=True):
            move = self.action(src, dst, count, 'scout',
                               'advance capped probe toward known king')
            if move:
                self.scout_rear, self.rear_until = src, self.tick + 12
                self.probe_last = self.tick
                return move
        return None

    def scout_known_king(self, target=None):
        """Probe and advance toward the best remembered enemy king position."""
        if (not self.EVERY_STEP and self.tick - self.probe_last < 8):
            return None
        models = [(owner, model) for owner, model in self.kings.items()
                  if target is None or model['pos'] == target]
        if (models and all(self.tick - model['seen'] > self.KING_MAX_AGE
                           for _, model in models)
                and self.tick - self.probe_last < self.KING_STALE_PROBE_INTERVAL):
            return None
        for owner, model in sorted(models, key=lambda item: (
                self.tick - item[1]['seen'] + hex_distance(self.home, item[1]['pos']),
                item[1]['pos'])):
            pos = model['pos']
            origins = sorted((p for p in self.owned if self.available(p) >= 2),
                             key=lambda p: (hex_distance(p, pos), -self.available(p), p))[:6]
            if self.scout in origins:
                origins.remove(self.scout)
                origins.insert(0, self.scout)
            if origins:
                move = self.refresh_stale_king(origins[0], pos)
                if move:
                    return move
            move = self.advance_king_scout(pos)
            if move:
                return move
        return None

    def hunt_sweep_target(self):
        """Choose a rotating, map-relative sector when enemy land is still hidden."""
        directions = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
        interval = max(1, self.HUNT_PROBE_INTERVAL * self.HUNT_PROBES_PER_SECTOR)
        cycle = max(0, self.hunt_probe_attempt // interval)
        sector = (max(0, self.army - 1) + cycle) % len(directions)
        dq, dr = directions[sector]
        home_row, home_col = self.home
        home_q = home_col - (home_row - (home_row & 1)) // 2
        target = self.home
        for steps in range(1, max(self.rows, self.cols) + 1):
            row = home_row + dr * steps
            q = home_q + dq * steps
            col = q + (row - (row & 1)) // 2
            if not (0 <= row < self.rows and 0 <= col < self.cols):
                break
            target = (row, col)
        return target

    def advance_hunt_scout(self, target, mission_pos=None, home_probe_safe=False):
        """Move a capped scout into a visible frontier toward the search sector."""
        protected = self.protected()
        sources = []
        if (self.scout in self.owned and self.scout != self.home
                and self.scout != mission_pos and self.scout not in protected):
            sources.append(self.scout)
        others = [p for p in self.owned
                  if p != self.home and p != mission_pos and p != self.scout_rear
                  and p not in sources and p not in protected and self.available(p) >= 1]
        others.sort(key=lambda p: (hex_distance(p, target), -self.available(p), p))
        sources.extend(others[:12])
        if mission_pos is not None:
            sources.append(mission_pos)
        if home_probe_safe:
            sources.append(self.home)

        unique_sources = []
        for pos in sources:
            if pos not in unique_sources:
                unique_sources.append(pos)
        choices = []
        for src in unique_sources:
            available = self.available(src)
            if available < 1:
                continue
            if src == self.home:
                surplus = max(0, self.cells[self.home][2]
                              - max(self.home_keep, self.HUNT_HOME_KEEP_MINIMUM))
                cap = min(self.HUNT_PROBE_CAP, available // 3, surplus)
            else:
                cap = min(self.HUNT_PROBE_CAP,
                          available if src in (self.scout, mission_pos)
                          else max(1, available // 3))
            if cap < 1:
                continue
            for dst in self.neighbors[src]:
                if dst not in self.cells:
                    continue
                kind, owner, guards = self.cells[dst]
                if kind in BLOCKED:
                    continue
                progress = hex_distance(src, target) - hex_distance(dst, target)
                if progress < 0:
                    continue
                sight = self.new_sight(dst)
                if not sight:
                    continue
                counter = self.counter(dst, excluded=(dst,))
                if owner == self.army:
                    count = cap
                    if self.cells[dst][2] + count <= counter + 1:
                        continue
                else:
                    count = guards + counter + 2
                    if count > cap:
                        continue
                remaining = self.cells[src][2] - count
                if self.counter(src, excluded=(dst,)) > remaining:
                    continue
                score = progress * 40 + len(sight) * 3
                score += len(sight & self.hill_hints) * 4
                score -= guards * 0.5 + counter * 1.5 + self.visits.get(dst, 0) * 2
                if src == self.scout:
                    score += 8
                choices.append((score, -hex_distance(dst, target), src, dst, count))
        for _, _, src, dst, count in sorted(choices, reverse=True):
            reason = 'bounded King hunt toward hidden-owner sector'
            move = self.action(src, dst, count, 'scout', reason)
            if move:
                self.scout = dst
                self.scout_rear, self.rear_until = src, self.tick + 12
                self.probe_last = self.tick
                self.last_report['hunt_probe_target'] = dst
                return move
        return None

    def hunt_probe(self):
        """Use a small, periodic scout to reveal an unseen opponent King."""
        if (not self.home or self.kings or self.pending
                or self.calls <= self.HUNT_OPENING_CALLS):
            return None
        possible = set(range(1, self.army))
        if self.army == 1:
            possible.add(2)
        remaining = (self.known_owners | possible) - self.eliminated
        remaining.discard(self.army)
        if not remaining:
            return None
        if ((not self.EVERY_STEP and self.tick - self.probe_last < 8)
                or self.tick - self.hunt_probe_attempt < self.HUNT_PROBE_INTERVAL):
            return None
        if self.mission:
            if (self.mission['kind'] not in ('frontier', 'fort')
                    or self.tick - self.mission['started'] < self.HUNT_PROBE_MISSION_MIN_AGE):
                return None
            mission_pos = self.mission['pos']
            if mission_pos == self.home:
                return None
        else:
            mission_pos = None

        self.hunt_probe_attempt = self.tick
        self.last_report['hunt_probe_check'] = self.tick
        enemy_memory = [data for data in self.search_memory().values()
                        if data[1] > 0 and data[1] != self.army
                        and data[1] not in self.eliminated]
        if enemy_memory:
            focus = self.focus()
            region_focus, inferred_anchor = True, False
        elif self.hunt_anchor_probe_count < 4:
            focus = self.focus()
            region_focus, inferred_anchor = True, True
        else:
            focus = self.hunt_sweep_target()
            region_focus, inferred_anchor = False, False
        if focus is None:
            return None
        home_probe_safe = self.home_keep <= self.HUNT_PROBE_HOME_KEEP_MAX
        move = self.advance_hunt_scout(focus, mission_pos, home_probe_safe)
        if not move and (region_focus or inferred_anchor):
            if inferred_anchor:
                self.hunt_anchor_probe_count = 4
            fallback_focus = self.hunt_sweep_target()
            if fallback_focus != focus:
                self.last_report['hunt_probe_fallback'] = 'rotating sector'
                move = self.advance_hunt_scout(fallback_focus, mission_pos, home_probe_safe)
                if move:
                    focus = fallback_focus
                    region_focus, inferred_anchor = False, False
        if not move:
            self.last_report['hunt_probe_skip'] = 'no safe visible frontier toward focus or sector'
            return None
        if inferred_anchor:
            self.hunt_anchor_probe_count += 1
        self.last_report['hunt_focus'] = focus
        self.last_report['hunt_region_focus'] = region_focus
        return move
