"""Isolated, ablatable ideas from BFS teaching, YRFZ and campaign agents.

All decisions use current visible cells, historical observations and public hill
silhouettes. No map identifiers, static spawn coordinates or king hints.
"""
from heapq import heappop, heappush
from std_geometry import BLANK, KING, FORT, BLOCKED, MARSH, hex_distance
from std_supply import tree_supply


class Enhancements:
    def decide(self, cells, hill_hints=None):
        expired = None
        task = self.mission
        if self.config['bridge_patience'] and task and task.get('strike_guard_pending'):
            signature = (task['target'], task.get('strike_guard_pending'), task.get('strike_guard_stage'))
            watch = getattr(self, '_bridge_watch', None)
            if watch is None or watch[0] != signature:
                self._bridge_watch = signature, self.tick
            elif self.tick - watch[1] >= self.config['bridge_patience']:
                expired = dict(target=task['target'], waited=self.tick-watch[1])
                self.failures[task['target']] = self.tick
                self.mission = None
                self._bridge_watch = None
        else:
            self._bridge_watch = None
        move = super().decide(cells, hill_hints)
        if expired:
            self.last_report['expired_bridge'] = expired
        return move

    def scout_known_king(self, target=None):
        if self.config['adaptive_pressure'] and self.config['stack_mode'] and not self.assault:
            move = self.stack_action()
            if move:
                self.last_report['unfunded_king_development'] = True
                return move
        return super().scout_known_king(target)

    def routes(self, start, owned_only=False, ceiling=None, forbidden=()):
        if owned_only or not self.config['cost_routes']:
            return super().routes(start, owned_only, ceiling, forbidden)
        # ProbeFort: account for combat losses and marsh attrition in route cost.
        key = ('cost', start, ceiling, frozenset(forbidden))
        if key in self.path_cache:
            return self.path_cache[key]
        parent, distance, costs = {start: None}, {start: 0}, {start: 0.0}
        queue = [(0.0, start)]
        while queue:
            cost, p = heappop(queue)
            if cost != costs[p] or distance[p] >= self.MAX_ROUTE:
                continue
            for n in self.neighbors[p]:
                data = self.estimate_cell(n)
                if n in forbidden or data is None or data[0] in BLOCKED:
                    continue
                kind, owner, units = data
                if ceiling is not None and owner != self.army and units > ceiling:
                    continue
                edge = 1.0 + (units * .13 + (.7 if owner > 0 else 0) if owner != self.army else 0)
                edge += .7 if n not in self.cells else 0
                edge += 3 if kind == MARSH else 0
                new = cost + edge
                if new < costs.get(n, float('inf')):
                    costs[n], parent[n], distance[n] = new, p, distance[p] + 1
                    heappush(queue, (new, n))
        self.path_cache[key] = parent, distance
        return parent, distance

    def gather(self, goal, reason, role='supply', limit=None, exclude=(), max_distance=None):
        if self.config['command_merge'] and role == 'supply':
            plan = tree_supply(self, goal, 6, exclude, max_distance)
            if plan:
                src, dst, amount = plan[0]
                move = self.action(src, dst, amount, role, 'merge branch before forwarding shared road')
                if move:
                    self.last_report.update(merge_goal=goal, merge_commands=len(plan),
                                            merge_planned_moves=plan)
                    return move
        return super().gather(goal, reason, role, limit, exclude, max_distance)

    def action(self, src, dst, count, role, reason, advance=False):
        cap = self.config['packet_cap']
        if (cap and role == 'expand' and src in self.cells and dst in self.cells
                and self.cells[dst][0:2] == (BLANK, 0)):
            # YRFZ: carry a field packet rather than stranding every new tile at 1.
            safe = max(0, self.cells[src][2] - max(1, self.counter(src) + 1))
            have = min(self.available(src), safe)
            amount = min(have, cap) if self.cells[src][0] in (KING, FORT) else have
            count = max(count, amount)
        return super().action(src, dst, count, role, reason, advance)

    def route_plan(self, src, target, ceiling=None, forbidden=()):
        plan = super().route_plan(src, target, ceiling, forbidden)
        if not plan or not self.config['pickup_routes']:
            return plan
        # YRFZ/Campaign: the moving stack collects only movable road garrisons.
        # Prefix deficits prevent troops beyond a defended gate funding that gate.
        spent, peak, pickup = 0, 0, 0
        for i, p in enumerate(plan['route'][1:], 1):
            kind, owner, units = self.estimate_cell(p, i)
            if p in self.cells and owner == self.army:
                gain = self.cells[p][2] - max(1, self.fort_reserves.get(p, 1))
                if p == self.home:
                    gain = self.available(p)
                spent -= gain
                pickup += max(0, gain)
            else:
                if kind == KING and owner in self.kings:
                    units = self.predict_king(owner, i + 1,
                                              excluded=plan['route'][1:-1])['upper']
                spent += units + 1 + (2 if kind == MARSH else 0)
            peak = max(peak, spent)
        plan = dict(plan, needed=max(3, peak + plan['flank'] + 3), pickup=pickup)
        return plan

    def stack_action(self):
        """Largest funded stack, shortest visible route, execute one edge.

        Generalized teaching BFS with reserve accounting and a target preference
        for production, fresh vision and progress. Every edge is observed.
        """
        focus = self.focus()
        sources = sorted(self.owned, key=lambda p: (self.available(p), p), reverse=True)[:6]
        choices = []
        for src in sources:
            have = self.available(src)
            if have < 2 or src in self.protected():
                continue
            parent, distance = self.routes(src, owned_only=True)
            for road in sorted(parent):
                for target in self.neighbors[road]:
                    if target not in self.cells or target in parent:
                        continue
                    kind, owner, units = self.cells[target]
                    if kind in BLOCKED or owner == self.army:
                        continue
                    path = self.path(parent, road) + [target]
                    steps = len(path) - 1
                    if steps > 12:
                        continue
                    # Count only current, spendable units on the actual path.
                    power = have + sum(self.available(p) for p in path[1:-1])
                    if power <= units + self.counter(target) + 2:
                        continue
                    if self.counter(src) >= self.cells[src][2] - have:
                        continue
                    progress = hex_distance(src, focus) - hex_distance(target, focus)
                    sight = self.new_sight(target)
                    value = (10000 if kind == KING and owner else 85 if kind == FORT else 8)
                    value += len(sight) * 4 + len(sight & self.hill_hints) * 12
                    value += progress * 8 - units * .3
                    score = value / float(steps + 1)
                    choices.append((score, -steps, power, src, path[1], target))
        for _, _, _, src, dst, target in sorted(choices, reverse=True):
            move = self.action(src, dst, self.available(src), 'stack',
                               'largest funded stack on visible BFS road')
            if move:
                self.last_report['stack_target'] = target
                return move
        return None

    def launch(self, king_only=False):
        if not king_only and (self.config['stack_mode'] or self.calls <= self.config['opening_steps']):
            return self.stack_action()
        return super().launch(king_only)

    def hunt_probe(self):
        if self.config['stack_mode'] or self.calls <= self.config['opening_steps']:
            return None
        return super().hunt_probe()
