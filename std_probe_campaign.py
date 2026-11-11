"""Persistent field army: open a route before requiring a known enemy king.

Uses only the Agent's current observations, remembered terrain and masked hints.
This is a combat formation, separate from small expendable scouting probes.
"""
import math

BLANK, KING, FORT, HILL, OBSTACLE, MARSH = range(1, 7)


class Campaign:
    MIN_FORMATION = 12
    MAX_ROUTE = 36

    def __init__(self):
        self.pos = None
        self.target = None
        self.started = 0
        self.home_reserve = 0
        self.failures = {}
        self.last_progress = 0
        self.last_probe = -100

    def protected(self):
        return {self.pos} if self.pos is not None else set()

    def clear(self):
        self.pos = None
        self.target = None
        self.home_reserve = 0

    def confirmed(self, order, tick):
        if order['src'] != self.pos:
            return
        if order['role'] in ('campaign', 'defend', 'capture'):
            self.pos = order['dst']
            self.last_progress = tick
            if self.pos == self.target:
                self.target = None

    @staticmethod
    def counter(bot, pos, excluded=()):
        """Visible force able to hit this square; sum same-army adjacent stacks."""
        by_owner = {}
        for p in bot.neighbors[pos]:
            if p in excluded or p not in bot.cells:
                continue
            _, owner, units = bot.cells[p]
            if owner > 0 and owner != bot.army:
                by_owner[owner] = by_owner.get(owner, 0) + max(0, units - 1)
        return max(by_owner.values(), default=0)

    def route_plan(self, bot, src, target, parent=None):
        if parent is None:
            _, parent, _ = bot.paths(src)
        route = bot.path(parent, target)
        if not route or len(route) < 2 or len(route) - 1 > self.MAX_ROUTE:
            return None
        loss = 0
        for i, p in enumerate(route[1:], 1):
            kind, owner, units = bot.estimate_cell(p, i)
            if owner != bot.army:
                loss += units + 1
            else:
                loss += max(0, bot.fort_reserves.get(p, 1) - units)
            if kind == MARSH:
                loss += 2
        # Do not count an enemy on the path twice as defender and counterattacker.
        flank = max((self.counter(bot, p, excluded=route[1:]) for p in route[1:]), default=0)
        needed = int(math.ceil(loss + flank + 6))
        return dict(route=route, needed=needed, loss=loss, flank=flank, steps=len(route)-1)

    def choices(self, bot, src, budget):
        _, parent, _ = bot.paths(src)
        focus = bot.search_focus()
        from std_probe_policy import hex_distance
        choices = []
        for target in parent:
            if target == src or bot.tick - self.failures.get(target, -1000) < 20:
                continue
            data = bot.estimate_cell(target)
            kind, owner, units = data
            info = bot.new_sight(target)
            hills = len(info & bot.hill_hints)
            producer = kind == FORT and owner != bot.army
            if kind == KING or (not producer and not info):
                continue
            if not producer and owner == bot.army:
                # A visible owned tile already grants its full neighbourhood.
                continue
            plan = self.route_plan(bot, src, target, parent)
            if plan is None or plan['needed'] > budget:
                continue
            enemy = owner > 0 and owner != bot.army
            progress = hex_distance(src, focus) - hex_distance(target, focus)
            value = (110 if producer else 0) + (45 if producer and enemy else 16 if enemy else 0)
            value += len(info) * 5 + hills * 9 + progress * 3
            value -= plan['steps'] * 2.2 + plan['loss'] * 0.45
            value -= hex_distance(target, focus) * 0.7
            value -= bot.visits.get(target, 0) * 1.5
            choices.append((value, target, plan))
        return sorted(choices, key=lambda x: (x[0], x[1]), reverse=True)

    def _launch(self, bot):
        candidates = []
        sources = sorted(bot.owned, key=lambda p: bot.available(p), reverse=True)[:8]
        for src in sources:
            if bot.available(src) < self.MIN_FORMATION:
                continue
            if bot.assault and src == bot.assault['pos']:
                continue
            budget = bot.available(src)
            for value, target, plan in self.choices(bot, src, budget)[:3]:
                guard = max(6, bot.reserve_home(min(8, plan['steps'] + 2)) + 4)
                if src == bot.home:
                    budget = max(0, bot.cells[src][2] - max(bot.home_keep, guard))
                elif bot.cells.get(bot.home, (0, 0, 0))[2] < guard:
                    continue
                if budget < plan['needed']:
                    continue
                # Keep a real reserve at home, but stop parking the whole economy
                # there until a tiny scout somehow reveals an inaccessible king.
                sent = min(budget, max(plan['needed'] + 6, int(budget * 0.60)))
                candidates.append((value + sent * 0.025, src, target, plan, sent, guard))
        if not candidates:
            return None
        _, src, target, plan, sent, guard = max(candidates, key=lambda item: (item[0], item[1]))
        self.pos, self.target = src, target
        self.started = self.last_progress = bot.tick
        self.home_reserve = guard
        bot.home_keep = max(bot.home_keep, guard)
        if bot.scout == src:
            bot.scout = None
        if bot.scout_rear == src:
            bot.scout_rear = None
        bot.fort = None
        result = bot.step_on(plan['route'], sent, 'campaign', 'launch field army to producer or new frontier')
        if not result:
            self.clear()
        else:
            bot.last_report['campaign'] = dict(target=target, needed=plan['needed'], steps=plan['steps'])
        return result

    def step(self, bot):
        if bot.pending or bot.assault:
            return None
        if self.pos is not None and (self.pos not in bot.cells or bot.cells[self.pos][1] != bot.army):
            if self.target is not None:
                self.failures[self.target] = bot.tick
            self.clear()
        if self.pos is None:
            return self._launch(bot)
        src = self.pos
        have = bot.available(src)
        # A newly revealed king can be assaulted from THIS forward army. If we
        # need more strength, recruit here instead of taking the army back home.
        kings = [bot.assault_plan(src, owner) for owner in bot.kings]
        kings = [plan for plan in kings if plan is not None]
        if kings:
            king_plan = min(kings, key=lambda plan: (plan['steps'], plan['needed']))
            if king_plan['steps'] <= 10 and have < king_plan['needed']:
                move = bot.gather(src, 'reinforce forward army for known king', 'campaign_supply',
                                  limit=king_plan['needed'] - have + 4)
                if move:
                    return move
        if self.target is not None:
            data = bot.cells.get(self.target)
            if data and data[1] == bot.army:
                self.target = None
            elif not bot.new_sight(self.target) and bot.memory.get(self.target, (0,))[0] != FORT:
                self.target = None
        plan = self.route_plan(bot, src, self.target) if self.target is not None else None
        if plan is None:
            choices = self.choices(bot, src, max(have, self.MIN_FORMATION))
            if choices:
                _, self.target, plan = choices[0]
            else:
                # Pool nearby/rear troops before trying a defended frontier again.
                move = bot.gather(src, 'concentrate at forward contact; do not withdraw to home',
                                  'campaign_supply', limit=max(12, have // 2))
                if move:
                    return move
                self.target = None
                return None
        dst = plan['route'][1]
        if dst not in bot.cells:
            self.target = None
            return None
        guards = bot.cells[dst][2] if bot.cells[dst][1] != bot.army else 0
        counter = self.counter(bot, dst, excluded=(dst,))
        remaining = have - guards
        if have <= guards or (bot.cells[dst][1] != bot.army and counter >= remaining):
            needed = max(plan['needed'] - have, guards + counter + 3 - have, 1)
            move = bot.gather(src, 'fund breakthrough at the forward army', 'campaign_supply', limit=needed + 4)
            if move:
                return move
            # A risky information probe must leave the field army in place.
            # It does NOT advance the campaign position or surrender its rear.
            third = have // 3
            if (third > guards + 1 and bot.new_sight(dst)
                    and bot.tick - self.last_probe >= 12):
                move = bot.action(src, dst, third, 'scout', 'one-third probe; main field army holds the rear')
                if move:
                    bot.scout_rear = src
                    self.last_probe = bot.tick
                    return move
            if bot.tick - self.last_progress >= 12:
                self.failures[self.target] = bot.tick
                self.target = None
            return None
        if have < plan['needed'] and bot.cells[dst][1] != bot.army:
            move = bot.gather(src, 'top up forward campaign before the next contested segment',
                              'campaign_supply', limit=plan['needed'] - have)
            if move:
                return move
        if have <= 0:
            return bot.gather(src, 'replenish forward formation', 'campaign_supply', limit=12)
        bot.last_report['campaign'] = dict(target=self.target, needed=plan['needed'], steps=plan['steps'])
        return bot.step_on(plan['route'], have, 'campaign', 'continue persistent forward objective')
