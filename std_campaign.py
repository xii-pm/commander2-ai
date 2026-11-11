"""Campaign methods preserved from the frozen BFS hunter."""
from std_geometry import KING, FORT, hex_distance


class Campaign:
    def objectives(self, src):
        focus = self.focus()
        choices = []
        parent, _ = self.routes(src)
        for dst in parent:
            if dst == src or (not self.EVERY_STEP and self.tick - self.failures.get(dst, -999) < 24):
                continue
            kind, owner, units = self.estimate_cell(dst)
            sight = self.new_sight(dst)
            if owner == self.army:
                continue
            king = kind == KING and owner in self.kings
            fort = kind == FORT
            # Stale king routes are scouted from neighboring reachable squares.
            if not king and not fort and not sight:
                if not self.kings or min(hex_distance(dst, m['pos']) for m in self.kings.values()) > 2:
                    continue
            plan = self.best_plan(src, dst)
            if not plan:
                continue
            progress = hex_distance(src, focus) - hex_distance(dst, focus)
            value = (180 if king else 85 if fort else 0)
            value += (20 if owner > 0 and fort else 8 if owner > 0 else 0)
            value += len(sight) * 5 + len(sight & self.hill_hints) * 9 + progress * 10
            value += self.network_leverage(dst)
            value -= plan['steps'] * 2.2 + plan['loss'] * 0.35 + hex_distance(dst, focus) * 1.0
            value -= self.visits.get(dst, 0) * 3
            choices.append((value, dst, 'assault' if king else 'fort' if fort else 'frontier', plan))
        return sorted(choices, key=lambda item: (item[0], item[1]), reverse=True)

    def launch(self, king_only=False):
        sources = sorted(self.owned, key=lambda p: self.available(p), reverse=True)[:6]
        if self.regional_hub in self.owned and self.regional_hub not in sources:
            sources.append(self.regional_hub)
        options = []
        for src in sources:
            if src == self.scout_rear or self.available(src) < 8:
                continue
            if king_only:
                objectives = []
                for model in self.kings.values():
                    dst = model['pos']
                    plan = self.best_plan(src, dst)
                    if (plan and plan['steps'] <= self.king_route_limit()
                            and self.king_assault_start_ready(src, plan)):
                        score = 1000 - plan['steps'] * 4 - plan['needed'] * 0.3
                        objectives.append((score, dst, 'assault', plan))
            else:
                objectives = self.objectives(src)
            for score, dst, kind, plan in objectives[:10]:
                if kind == 'assault' and not self.king_assault_start_ready(src, plan):
                    continue
                guard = self.reserve_home(min(self.LAUNCH_GUARD_WINDOW,
                                              plan['steps'] + self.LAUNCH_GUARD_LEAD)) + self.LAUNCH_GUARD_MARGIN
                have = self.available(src)
                if src == self.home:
                    have = min(have, max(0, self.cells[src][2] - guard))
                elif self.cells[self.home][2] < guard:
                    continue
                partial_assault = False
                support_delivered = 0
                first = plan['route'][1]
                if first not in self.cells:
                    continue
                first_data = self.cells[first]
                if kind == 'assault':
                    first_guard = first_data[2] if first_data[1] != self.army else 0
                    first_counter = self.counter(first, excluded=(first,))
                    required = max(plan['needed'], first_guard + first_counter + 2)
                    if have < required:
                        if src == self.home:
                            continue
                        donors, _, support_delivered, ready = self.strike_support_plan(
                            src, plan, self.KING_ASSAULT_START_COMMANDS,
                            required=required)
                        if not ready:
                            continue
                        partial_assault = True
                elif have < plan['needed']:
                    # Establish an adjacent staging square before a defended fort.
                    if kind != 'fort' or len(plan['route']) < 3:
                        continue
                    stage = plan['route'][-2]
                    stage_plan = self.best_plan(src, stage)
                    if not stage_plan or have < stage_plan['needed']:
                        continue
                count = have if kind == 'assault' else min(have, max(plan['needed'] + 4, int(have * 0.7)))
                if count < 6:
                    continue
                if partial_assault:
                    remaining = max(0, required - have - support_delivered)
                    score += support_delivered * 0.02 - remaining * 0.1
                else:
                    survivors = count + first_data[2] if first_data[1] == self.army else count - first_data[2]
                    if survivors <= self.counter(first) + 1:
                        continue
                options.append((score + count * 0.025, src, dst, kind, plan,
                                count, guard, partial_assault))
        if not options:
            return None
        _, src, dst, kind, plan, count, guard, partial_assault = max(
            options, key=lambda x: (x[0], x[1]))
        # The launch-window guard is local to this choice. Keep home_keep as
        # the immediate-response budget used by reserve and move accounting.
        self.mission = dict(pos=src, target=dst, kind=kind, started=self.tick,
                            progress=self.tick, trail=[src])
        if kind == 'assault' and partial_assault:
            self.mission['start_plan'] = plan
            self.king_assault_start_ready(src, plan)
        if partial_assault:
            move = self.mission_action()
        else:
            move = self.action(src, plan['route'][1], count,
                               'assault' if kind == 'assault' else 'campaign',
                               'launch persistent BFS objective', advance=True)
        if not move and not partial_assault:
            self.mission = None
        return move

    def strike_support_plan(self, src, plan, max_commands=None, required=None):
        """Return the local donors that fit both the order and intel budgets."""
        if max_commands is None:
            max_commands = self.STRIKE_COMMAND_BUDGET
        target = plan['route'][-1]
        model = next((m for m in self.kings.values() if m['pos'] == target), None)
        if model:
            remaining_intel = self.KING_MAX_AGE - (self.tick - model['seen']) - plan['steps'] - 2
            if remaining_intel < 0:
                return [], 0, 0, False
            max_commands = min(max_commands, remaining_intel)
        required = plan['needed'] if required is None else required
        shortage = max(0, required - self.available(src))
        if shortage == 0:
            return [], 0, 0, True
        distance = self.bfs(src, lambda p: p in self.cells and self.cells[p][1] == self.army)
        donors = sorted((-self.available(p) / float(max(1, distance[p])), distance[p],
                         -self.available(p), p) for p in self.owned
                        if p != src and p in distance and distance[p] <= self.STRIKE_SUPPORT_RADIUS
                        and p not in self.protected() and self.available(p) > 0)
        selected, commands, delivered = [], 0, 0
        for _, steps, negative, donor in donors:
            cost = max(1, steps)
            if commands + cost > max_commands:
                continue
            selected.append(donor)
            commands += cost
            delivered += -negative
            if delivered >= shortage:
                return selected, commands, delivered, True
        return selected, commands, delivered, False

    def strike_support(self, src, plan, max_commands=None):
        """Can this forward group become strike-ready before its intel expires?"""
        return self.strike_support_plan(src, plan, max_commands)[-1]

    def strike_support_possible(self, src, plan, max_commands=None):
        """Allow an assault mission to gather partial support before it is ready."""
        donors, _, _, ready = self.strike_support_plan(src, plan, max_commands)
        return ready or bool(donors)

    def king_assault_start_ready(self, src, plan):
        """Require a compact, ready support plan before replacing a campaign."""
        if not plan or len(plan.get('route', ())) < 2:
            return False
        first = plan['route'][1]
        if first not in self.cells:
            return False
        first_guard = self.cells[first][2] if self.cells[first][1] != self.army else 0
        required = max(plan['needed'], first_guard + self.counter(first, excluded=(first,)) + 2)
        donors, commands, delivered, ready = self.strike_support_plan(
            src, plan, self.KING_ASSAULT_START_COMMANDS, required=required)
        self.last_report.update(king_assault_start_source=src,
                                king_assault_start_required=required,
                                king_assault_start_commands=commands,
                                king_assault_start_delivered=delivered,
                                king_assault_start_donors=len(donors),
                                king_assault_start_ready=ready)
        return ready

    def resume_strike_guard(self, src):
        """Finish a previously staged corridor guard before any other order."""
        task = self.mission
        if not task or task.get('kind') != 'assault':
            return None
        pos = task.get('strike_guard_pending')
        staging = task.get('strike_guard_stage')
        if (pos not in self.cells or staging not in self.cells
                or self.cells[staging][1] != self.army):
            return None
        kind, owner, guards = self.cells[pos]
        was_enemy = owner != self.army
        if owner == self.army:
            amount = max(5, self.fort_reserves.get(pos, 1),
                         self.counter(pos) + 1) - self.cells[pos][2]
        elif owner > 0 and kind != KING:
            amount = guards + self.counter(pos, excluded=(pos,)) + 2
            if task.get('strike_guard_lost_force', 0) < max(32, amount * 2):
                return None
        else:
            return None
        if amount <= 0:
            if owner == self.army:
                self.remember_strike_guard(pos)
            for key in ('strike_guard_pending', 'strike_guard_stage',
                        'strike_guard_lost_force'):
                task.pop(key, None)
            return None
        stage_force = self.available(staging)
        if stage_force >= amount:
            move = self.action(staging, pos, amount, 'supply',
                               'complete staged King-strike bridge guard',
                               advance=False)
            if move:
                if was_enemy:
                    self.last_report.update(strike_bridge_reopen=True,
                                            strike_bridge_pos=pos,
                                            strike_bridge_from=staging,
                                            strike_bridge_required=amount,
                                            strike_bridge_remote_force=task.get(
                                                'strike_guard_lost_force', 0),
                                            strike_bridge_staged=False)
                else:
                    self.remember_strike_guard(pos)
                    for key in ('strike_guard_pending', 'strike_guard_stage',
                                'strike_guard_lost_force'):
                        task.pop(key, None)
                self.last_report.update(strike_corridor_guard=True,
                                        strike_corridor_guard_pos=pos,
                                        strike_corridor_guard_shortage=amount,
                                        strike_corridor_guard_staged=False)
            return move
        needed = max(1, amount - stage_force)
        if self.available(src) < needed:
            return None
        remaining = self.cells[src][2] - needed
        target = task.get('target')
        if self.counter(src, excluded=(staging, target)) > remaining:
            return None
        move = self.action(src, staging, needed, 'supply',
                           'continue staged King-strike bridge guard',
                           advance=False)
        if move:
            self.last_report.update(strike_corridor_guard=True,
                                    strike_corridor_guard_pos=pos,
                                    strike_corridor_guard_shortage=amount,
                                    strike_corridor_guard_staged=True,
                                    strike_corridor_guard_stage=staging)
        return move

    def strike_trail_guard(self, src, donors):
        """Protect the second most recent friendly cell on an active King route."""
        task = self.mission
        if (not task or task.get('kind') != 'assault' or len(donors) < 2
                or len(task.get('trail', [])) < 2):
            return None
        trail = task['trail']
        pos, staging = trail[-2], trail[-1]
        owned = lambda p: p in self.cells and self.cells[p][1] == self.army
        if (pos == src or not owned(pos) or not owned(staging)
                or hex_distance(src, staging) != 1
                or hex_distance(staging, pos) != 1):
            return None
        target = task['target']
        if target is not None and hex_distance(pos, target) <= 1:
            return None
        reachable = self.bfs(src, lambda p: p != pos and owned(p))
        lost_force = sum(self.available(d) for d in donors if d not in reachable)
        if lost_force < 32:
            return None
        reserve = max(5, self.fort_reserves.get(pos, 1))
        shortage = reserve - self.cells[pos][2]
        if shortage <= 0:
            return None
        from_staging = self.available(staging)
        if from_staging >= shortage:
            move = self.action(staging, pos, shortage, 'supply',
                               'reinforce recent King-route cutpoint', advance=False)
            if move:
                self.last_report.update(strike_trail_guard=True,
                                        strike_trail_guard_pos=pos,
                                        strike_trail_guard_lost_force=lost_force,
                                        strike_trail_guard_shortage=shortage,
                                        strike_trail_guard_staged=False)
                self.remember_strike_guard(pos)
                for key in ('strike_guard_pending', 'strike_guard_stage',
                            'strike_guard_lost_force'):
                    task.pop(key, None)
                return move
            return None
        needed = max(1, shortage - from_staging)
        if self.available(src) < needed:
            return None
        remaining = self.cells[src][2] - needed
        if self.counter(src, excluded=(staging, target)) > remaining:
            return None
        move = self.action(src, staging, needed, 'supply',
                           'stage reserve for recent King-route cutpoint',
                           advance=False)
        if move:
            self.last_report.update(strike_trail_guard=True,
                                    strike_trail_guard_pos=pos,
                                    strike_trail_guard_lost_force=lost_force,
                                    strike_trail_guard_shortage=shortage,
                                    strike_trail_guard_staged=True,
                                    strike_trail_guard_stage=staging)
            task.update(strike_guard_pending=pos,
                        strike_guard_stage=staging,
                        strike_guard_lost_force=lost_force)
            return move
        return None

    def strike_corridor_guard(self, src, donors):
        """Secure threatened or high-value cuts in the King support corridor."""
        if not donors or src not in self.owned:
            return None
        move = self.strike_trail_guard(src, donors)
        if move:
            return move
        owned = lambda p: p in self.cells and self.cells[p][1] == self.army
        distance = self.bfs(src, owned)
        corridor = set()
        for donor in donors:
            if donor not in distance:
                continue
            stack, seen = [donor], set()
            while stack:
                p = stack.pop()
                if p == src or p in seen:
                    continue
                seen.add(p)
                corridor.add(p)
                for n in self.neighbors[p]:
                    if distance.get(n) == distance[p] - 1:
                        stack.append(n)
        target = self.mission['target'] if self.mission else None
        protected = self.protected()
        direct = []
        staged = []
        for p in corridor:
            if p == src or not owned(p):
                continue
            king_distance = hex_distance(p, target) if target is not None else 99
            if target is not None and king_distance <= 1:
                continue
            threat = self.counter(p)
            near_king = target is not None and king_distance <= 4
            if threat <= 0 and (not near_king or len(donors) < 2):
                continue
            reachable = self.bfs(src, lambda n: n != p and owned(n))
            cut_donors = [d for d in donors if d not in reachable]
            lost_force = sum(self.available(d) for d in cut_donors)
            if lost_force <= 0 or (threat <= 0 and lost_force < 32):
                continue
            reserve = max(1, self.fort_reserves.get(p, 1), threat + 1,
                          5 if near_king else 1)
            shortage = reserve - self.cells[p][2]
            if shortage <= 0:
                continue
            priority = (0 if threat > 0 else 1, -lost_force,
                        -distance[p] if threat <= 0 else distance[p], p)
            adjacent = [n for n in self.neighbors[p]
                        if owned(n) and n not in protected
                        and self.available(n) >= shortage]
            if adjacent:
                direct.append((priority, p, shortage, threat, lost_force, adjacent))
                continue
            if not near_king or len(donors) < 2:
                continue
            for staging_cell in self.neighbors[p]:
                if not owned(staging_cell) or staging_cell in protected:
                    continue
                needed = max(1, shortage - self.available(staging_cell))
                for origin in self.neighbors[staging_cell]:
                    if origin not in distance or origin == staging_cell:
                        continue
                    if origin in (self.home, self.scout_rear):
                        continue
                    if origin in protected and origin != src:
                        continue
                    if self.available(origin) < needed:
                        continue
                    remaining = self.cells[origin][2] - needed
                    if self.counter(origin, excluded=(staging_cell, target)) > remaining:
                        continue
                    staged.append((priority, p, shortage, threat, lost_force,
                                   origin, staging_cell, needed))
        for _, p, shortage, threat, lost_force, adjacent in sorted(direct):
            donor = max(adjacent, key=lambda n: (self.available(n), n))
            move = self.action(donor, p, shortage, 'supply',
                               'reinforce critical King-strike bridge', advance=False)
            if move:
                self.last_report.update(strike_corridor_guard=True,
                                        strike_corridor_guard_pos=p,
                                        strike_corridor_guard_shortage=shortage,
                                        strike_corridor_guard_threat=threat,
                                        strike_corridor_guard_lost_force=lost_force,
                                        strike_corridor_guard_staged=False)
                self.remember_strike_guard(p)
                return move
        for _, p, shortage, threat, lost_force, origin, staging_cell, needed in sorted(staged):
            move = self.action(origin, staging_cell, needed, 'supply',
                               'stage reserve for King-strike bridge', advance=False)
            if move:
                self.last_report.update(strike_corridor_guard=True,
                                        strike_corridor_guard_pos=p,
                                        strike_corridor_guard_shortage=shortage,
                                        strike_corridor_guard_threat=threat,
                                        strike_corridor_guard_lost_force=lost_force,
                                        strike_corridor_guard_staged=True,
                                        strike_corridor_guard_stage=staging_cell)
                self.mission.update(strike_guard_pending=p,
                                    strike_guard_stage=staging_cell,
                                    strike_guard_lost_force=lost_force)
                return move
        return None

    def reopen_strike_cut(self, src):
        """Reclaim a visible enemy cell separating the assault from support."""
        task = self.mission
        if not task or task.get('kind') != 'assault' or src not in self.owned:
            return None
        owned = lambda p: p in self.cells and self.cells[p][1] == self.army
        source_distance = self.bfs(src, owned)
        source_component = set(source_distance)
        protected = self.protected()
        bridges = []
        target = task['target']
        for pos in self.enemies:
            if pos not in self.cells or self.cells[pos][1] == self.army:
                continue
            kind, owner, guards = self.cells[pos]
            if owner <= 0 or kind == KING or hex_distance(pos, target) <= 1:
                continue
            source_side = [n for n in self.neighbors[pos]
                           if n in source_component]
            remote_side = [n for n in self.neighbors[pos]
                           if owned(n) and n not in source_component]
            if not source_side or not remote_side:
                continue
            remote_force = 0
            for n in remote_side:
                component = self.bfs(n, owned)
                force = sum(self.available(p) for p in component
                            if p not in protected and p not in source_component)
                remote_force = max(remote_force, force)
            required = guards + self.counter(pos, excluded=(pos,)) + 2
            # Only reconnect a cut when the remote force can repay the cost and
            # provide a meaningful support reserve after capture.
            if remote_force < max(32, required * 2):
                continue
            bridges.append((-remote_force, pos, required, source_side))

        direct = []
        for negative_force, pos, required, source_side in bridges:
            for src_cell in source_side:
                if self.available(src_cell) < required:
                    continue
                remaining = self.cells[src_cell][2] - required
                if self.counter(src_cell, excluded=(pos,)) > remaining:
                    continue
                direct.append((negative_force, source_distance[src_cell], pos,
                               src_cell, required))
        for negative_force, _, pos, src_cell, required in sorted(direct):
            move = self.action(src_cell, pos, required, 'supply',
                               'reopen disconnected King-strike supply route')
            if move:
                self.last_report.update(strike_bridge_reopen=True,
                                        strike_bridge_pos=pos,
                                        strike_bridge_from=src_cell,
                                        strike_bridge_required=required,
                                        strike_bridge_remote_force=-negative_force,
                                        strike_bridge_staged=False)
                return move

        stages = []
        for negative_force, pos, required, source_side in bridges:
            for staging_cell in source_side:
                shortage = max(1, required - self.available(staging_cell))
                for origin in source_component:
                    if (origin == staging_cell or origin == self.home
                            or origin == self.scout_rear
                            or (origin in protected and origin != src)
                            or self.available(origin) < shortage):
                        continue
                    parent, distance = self.routes(origin)
                    route = self.path(parent, staging_cell)
                    if not route or len(route) != 2:
                        continue
                    remaining = self.cells[origin][2] - shortage
                    if self.counter(origin, excluded=(staging_cell,)) > remaining:
                        continue
                    stages.append((negative_force, distance[staging_cell], pos,
                                   origin, staging_cell, shortage, required))
        for negative_force, _, pos, origin, staging_cell, count, required in sorted(stages):
            move = self.action(origin, staging_cell, count, 'supply',
                               'stage force to reopen King-strike supply route')
            if move:
                self.last_report.update(strike_bridge_reopen=True,
                                        strike_bridge_pos=pos,
                                        strike_bridge_from=origin,
                                        strike_bridge_staging=staging_cell,
                                        strike_bridge_required=required,
                                        strike_bridge_remote_force=-negative_force,
                                        strike_bridge_staged=True)
                return move
        return None

    def restage_assault(self, exclude_current=False):
        """Choose a safe King origin fully supportable within its budget."""
        task = self.mission
        if not task or task['kind'] != 'assault':
            return False
        target = task['target']
        model = next((m for m in self.kings.values()
                      if m['pos'] == target and self.tick - m['seen'] <= self.KING_MAX_AGE), None)
        if not model:
            return False
        available = {p: self.available(p) for p in self.owned if p != self.scout_rear}
        useful = [p for p in self.owned if available.get(p, 0) > 0]
        strongest = sorted(useful, key=lambda p: (-available[p], hex_distance(p, target)))[:6]
        nearest = sorted(useful, key=lambda p: (hex_distance(p, target), -available[p]))[:6]
        origins = set(strongest + nearest)
        if self.home in useful:
            origins.add(self.home)
        choices, best_partial = [], None
        for origin in origins:
            if exclude_current and origin == task['pos']:
                continue
            plan = self.best_plan(origin, target)
            if (not plan or len(plan['route']) < 2
                    or plan['steps'] > self.king_route_limit()):
                continue
            next_pos = plan['route'][1]
            if next_pos not in self.cells:
                continue
            total_have = available.get(origin, 0)
            have = total_have
            if origin == self.home:
                launch_guard = self.reserve_home(min(self.LAUNCH_GUARD_WINDOW,
                                                      plan['steps'] + self.LAUNCH_GUARD_LEAD))
                launch_guard += self.LAUNCH_GUARD_MARGIN
                have = min(have, max(0, self.cells[origin][2] - launch_guard))
            next_guard = self.cells[next_pos][2] if self.cells[next_pos][1] != self.army else 0
            next_counter = self.counter(next_pos, excluded=(next_pos,))
            required = max(plan['needed'], next_guard + next_counter + 2)
            required += max(0, total_have - have)
            donors, commands, delivered, ready = self.strike_support_plan(
                origin, plan, required=required)
            if not ready and delivered <= 0:
                continue
            threat = self.counter(origin, excluded=(origin,))
            reserve = max(1, self.fort_reserves.get(origin, 1))
            if threat and self.cells[origin][2] - reserve <= threat:
                continue
            remaining = max(0, required - total_have - delivered)
            route_score = (plan['steps'] * 12 + max(0, required - have) * 0.05
                           + threat * 0.5 - min(have, 1000) * 0.02)
            if ready:
                choices.append((commands, route_score, -have, origin))
            else:
                partial = (remaining, commands, route_score, -have, origin)
                if best_partial is None or partial < best_partial:
                    best_partial = partial
        if not choices:
            if best_partial:
                gap, commands, _, _, origin = best_partial
                self.last_report.update(assault_restage_ready=False,
                                        assault_restage_best_partial_origin=origin,
                                        assault_restage_best_partial_gap=gap,
                                        assault_restage_commands=commands)
            return False
        commands, _, _, origin = min(choices)
        self.last_report.update(assault_restage_origin=origin,
                                assault_restage_ready=True,
                                assault_restage_support_gap=0,
                                assault_restage_commands=commands)
        task.update(pos=origin, progress=self.tick, trail=[origin])
        for key in ('strike_guard_pending', 'strike_guard_stage',
                    'strike_guard_lost_force', 'strike_guard_kept'):
            task.pop(key, None)
        task.pop('best_deficit', None)
        task.pop('funding_since', None)
        task.pop('strike_funding_patience', None)
        task.pop('strike_funding_patience_since', None)
        return True

    def mission_action(self):
        if not self.mission:
            return self.launch()
        task = self.mission
        src, target = task['pos'], task['target']
        start_plan = task.pop('start_plan', None)
        target_changed = False
        # Keep a valid committed target. New king choices respect failure cooldown
        # and prefer affordable strikes, rather than the first opponent ID.
        if task['kind'] != 'assault':
            king_choices = []
            for owner, model in sorted(self.kings.items()):
                if (not self.EVERY_STEP and self.tick - self.failures.get(model['pos'], -999) < 24):
                    continue
                king_plan = self.best_plan(src, model['pos'])
                if (king_plan and king_plan['steps'] <= self.king_route_limit()
                        and self.king_assault_start_ready(src, king_plan)):
                    shortage = max(0, king_plan['needed'] - self.available(src))
                    king_choices.append((shortage > 0, king_plan['steps'] + shortage * 0.1,
                                         model['pos'], king_plan))
            if king_choices:
                chosen = min(king_choices, key=lambda item: item[:3])
                target, start_plan = chosen[2], chosen[3]
                self.king_assault_start_ready(src, start_plan)
                if target != task['target']:
                    target_changed = True
                    for key in ('strike_guard_pending', 'strike_guard_stage',
                                'strike_guard_lost_force', 'strike_guard_kept'):
                        task.pop(key, None)
                task.update(target=target, kind='assault', progress=self.tick)
                task.pop('best_deficit', None)
                task.pop('funding_since', None)
                task.pop('strike_funding_patience', None)
                task.pop('strike_funding_patience_since', None)
        if task['kind'] == 'recon':
            refreshed = next((m for m in self.kings.values()
                              if m['pos'] == target and self.tick - m['seen'] <= self.KING_MAX_AGE), None)
            if refreshed:
                plan = self.best_plan(src, target)
                if plan and not self.strike_support_possible(src, plan):
                    self.last_report['abort'] = 'refreshed king cannot be reached inside intelligence window'
                    return None
        stale_model = next((m for m in self.kings.values()
                            if m['pos'] == target and self.tick - m['seen'] > self.KING_MAX_AGE), None)
        if task['kind'] in ('assault', 'recon') and stale_model:
            if task['kind'] != 'recon':
                task.update(kind='recon', recon_since=self.tick)
            move = self.refresh_stale_king(src, target)
            if not move:
                move = self.advance_king_scout(target)
            if move:
                return move
            if self.tick - task.get('recon_since', self.tick) >= self.RECON_TIMEOUT:
                self.failures[target] = self.tick
                self.mission = None
                self.last_report['abort'] = 'stale king area could not be refreshed'
            return None
        if task['kind'] == 'assault' and task.get('strike_guard_pending'):
            move = self.resume_strike_guard(src)
            if move:
                task['progress'] = self.tick
                return move
            if task.get('strike_guard_pending'):
                self.last_report.update(strike_guard_waiting=True,
                                        strike_guard_pending=task['strike_guard_pending'],
                                        strike_guard_stage=task.get('strike_guard_stage'))
                return None
        data = self.cells.get(target)
        complete = src == target or (data and data[1] == self.army)
        exhausted = task['kind'] == 'frontier' and not self.new_sight(target)
        stale = task['kind'] == 'assault' and not any(
            m['pos'] == target and self.tick - m['seen'] <= self.KING_MAX_AGE for m in self.kings.values())
        if complete or exhausted or stale:
            plan = None
        else:
            plan = start_plan
            if (not plan or not plan.get('route') or plan['route'][0] != src
                    or plan['route'][-1] != target):
                plan = self.best_plan(src, target)
        if (task['kind'] == 'assault' and plan
                and plan['steps'] > self.king_route_limit()):
            self.failures[target] = self.tick
            plan = None
        if plan is None and task['kind'] == 'assault':
            if complete:
                self.mission = None
                return None
            if self.restage_assault():
                src = task['pos']
                plan = self.best_plan(src, target)
                if plan and plan['steps'] > self.king_route_limit():
                    plan = None
            if plan is None:
                # Keep the confirmed king as the campaign focus while its route
                # is temporarily unknown; scout forward instead of retargeting forts.
                move = self.scout_known_king(target)
                if move:
                    task['progress'] = self.tick
                    return move
                move = self.expand()
                task['progress'] = self.tick
                return move
        if plan is None:
            choices = self.objectives(src)
            choices = [choice for choice in choices
                       if choice[2] != 'assault' or self.king_assault_start_ready(src, choice[3])]
            if not choices:
                self.mission = None
                return None
            _, target, kind, plan = choices[0]
            if kind == 'assault':
                start_plan = plan
                self.king_assault_start_ready(src, plan)
            target_changed = target != task.get('target')
            task.update(target=target, kind=kind, progress=self.tick)
            task.pop('best_deficit', None)
            task.pop('funding_since', None)
            task.pop('strike_funding_patience', None)
            task.pop('strike_funding_patience_since', None)
        have = self.available(src)
        route, needed = plan['route'], plan['needed']
        next_pos = route[1]
        trail = task.get('trail', ())
        previous = trail[-1] if trail and trail[-1] != src else None
        if (not target_changed and previous in self.neighbors.get(src, ())
                and target != previous and next_pos == previous):
            alternate = self.best_plan(src, target, forbidden=(previous,))
            if (alternate and len(alternate['route']) > 1
                    and alternate['route'][1] != previous
                    and alternate['steps'] <= plan['steps'] + 1
                    and (alternate['needed'] <= plan['needed'] + 2
                         or alternate['needed'] <= have)):
                original_steps = plan['steps']
                plan = alternate
                route, needed = plan['route'], plan['needed']
                next_pos = route[1]
                self.last_report.update(mission_backtrack_planned=True,
                                        mission_backtrack_from=previous,
                                        mission_backtrack_to=next_pos,
                                        mission_backtrack_extra_steps=plan['steps'] - original_steps)
            else:
                self.last_report['mission_backtrack_kept'] = True
        if next_pos not in self.cells:
            self.failures[target] = self.tick
            self.mission = None
            return None
        guards = self.cells[next_pos][2] if self.cells[next_pos][1] != self.army else 0
        counter = self.counter(next_pos, excluded=(next_pos,))
        contested = self.cells[next_pos][1] != self.army
        resident = 0 if contested else self.cells[next_pos][2]
        risky = have + resident <= guards + counter + 1
        if have < needed or risky:
            deficit = max(needed - have, guards + counter + 2 - have)
            if ('best_deficit' not in task or deficit <= task['best_deficit'] - 2):
                task.update(best_deficit=deficit, funding_since=self.tick, progress=self.tick)
            # Issuing tiny supply orders is not evidence that a growing enemy
            # becomes beatable. A King convoy gets time proportional to its
            # projected route commands, with a hard cap to avoid endless funding.
            strike_support = None
            funding_patience = self.FUNDING_PATIENCE
            if task['kind'] == 'assault':
                strike_support = self.strike_support_plan(
                    src, plan, required=have + deficit)
                projected_patience = min(
                    self.STRIKE_FUNDING_PATIENCE_MAX,
                    max(self.FUNDING_PATIENCE,
                        strike_support[1] + self.STRIKE_FUNDING_PATIENCE_MARGIN))
                if task.get('strike_funding_patience_since') != task['funding_since']:
                    task.update(strike_funding_patience=projected_patience,
                                strike_funding_patience_since=task['funding_since'])
                else:
                    task['strike_funding_patience'] = min(
                        self.STRIKE_FUNDING_PATIENCE_MAX,
                        max(task['strike_funding_patience'], projected_patience))
                funding_patience = task['strike_funding_patience']
                self.last_report['strike_funding_patience'] = funding_patience
            if self.tick - task['funding_since'] >= funding_patience:
                if task['kind'] == 'assault':
                    move = self.reopen_strike_cut(src)
                    if move:
                        task['progress'] = self.tick
                        return move
                    if self.restage_assault(exclude_current=True):
                        self.last_report.update(assault_restage=True,
                                                abort='King support stalled; restaged origin')
                        return None
                self.failures[target] = self.tick
                self.mission = None
                self.last_report['abort'] = 'funding deficit failed to improve'
                return None
            if task['kind'] == 'assault':
                donors, commands, delivered, strike_ready = strike_support
                self.last_report.update(strike_support_donors=len(donors),
                                        strike_support_commands=commands,
                                        strike_support_delivered=delivered,
                                        strike_support_ready=strike_ready)
                if donors:
                    move = self.strike_corridor_guard(src, donors)
                    if move:
                        task['progress'] = self.tick
                        return move
                move = self.reopen_strike_cut(src)
                if move:
                    task['progress'] = self.tick
                    return move
                if not donors and not strike_ready:
                    last_restage = task.get('last_restage_attempt', -self.STRIKE_RESTAGE_INTERVAL)
                    if self.tick - last_restage >= self.STRIKE_RESTAGE_INTERVAL:
                        task['last_restage_attempt'] = self.tick
                        # A captured bridge can strand a large convoy outside the
                        # owned component rooted at the old assault origin.
                        if self.restage_assault():
                            self.last_report.update(assault_restage=True,
                                                    abort='disconnected strike support; restaged origin')
                            return None
                king_model = next((m for m in self.kings.values()
                                   if m['pos'] == target), None)
                if king_model:
                    king_age = self.tick - king_model['seen']
                    remaining_intel = (self.KING_MAX_AGE - king_age
                                       - plan['steps'] - 2)
                    refresh_window = max(0, self.STRIKE_COMMAND_BUDGET
                                         - self.STRIKE_KING_REFRESH_BUFFER)
                    refresh_due = remaining_intel <= refresh_window
                else:
                    king_age, refresh_due = 0, False
                if (refresh_due
                        and self.tick - task.get('last_king_scout',
                                                 -self.STRIKE_KING_REFRESH_INTERVAL)
                        >= self.STRIKE_KING_REFRESH_INTERVAL):
                    task['last_king_scout'] = self.tick
                    move = self.scout_known_king(target)
                    if move:
                        self.last_report['assault_king_refresh_age'] = king_age
                        self.last_report['assault_king_refresh_budget'] = remaining_intel
                        task['progress'] = self.tick
                        return move
                excluded = set(self.owned) - set(donors)
                move = self.gather(src, 'reinforce king strike within intel budget', 'supply',
                                   deficit, exclude=excluded,
                                   max_distance=self.STRIKE_SUPPORT_RADIUS) if donors else None
                if not strike_ready:
                    self.last_report['abort'] = 'local king-strike convoy exceeds intel or command budget'
            else:
                # Keep the economy and map coverage growing while the main force is
                # waiting for reinforcements. Cap this detour so the field mission
                # still receives most of the scarce one-command-per-update budget.
                if (task['kind'] in ('frontier', 'fort') and
                        self.tick - task.get('last_expand', task['started']) >= self.CAMPAIGN_EXPAND_INTERVAL):
                    move = self.expand()
                    if move:
                        task['last_expand'] = self.tick
                        return move
                move = self.gather(src, 'reinforce persistent forward army', 'supply', deficit)
            if move:
                task['progress'] = self.tick
                return move
            if (task['kind'] == 'assault'
                    and self.tick - task.get('funding_since', self.tick) >= 8):
                move = self.scout_known_king(target)
                if move:
                    task['progress'] = self.tick
                    return move
            # Do not advance a knowingly underfunded king strike.
            if task['kind'] == 'assault' or risky:
                if task['kind'] == 'assault':
                    self.last_report['abort'] = 'king strike waits for force or refreshed intelligence'
                if risky and (self.EVERY_STEP or self.tick - self.probe_last >= 12):
                    count = min(48, have // 3)
                    if count > guards + 1 and self.new_sight(next_pos):
                        move = self.action(src, next_pos, count, 'scout', 'one-third probe; main army holds position')
                        if move:
                            self.scout_rear, self.rear_until = src, self.tick + 12
                            self.probe_last = self.tick
                            return move
                if self.tick - task['progress'] >= self.MISSION_PATIENCE:
                    self.failures[target] = self.tick
                    self.mission = None
                return None
        # A safe segment towards a fort can be occupied before final force is ready.
        if have <= guards:
            return None
        role = 'assault' if task['kind'] == 'assault' else 'campaign'
        move = self.action(src, next_pos, have, role,
                           'advance confirmed field army; replan every step', advance=True)
        if (move and self.last_report.get('mission_backtrack_planned')
                and move[1] == self.last_report.get('mission_backtrack_to')):
            self.last_report['mission_backtrack_avoided'] = True
        return move
