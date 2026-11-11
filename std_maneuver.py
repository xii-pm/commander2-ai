"""Legal-observation road proposals, ported from the reviewed Maneuver candidate.

No MRO overrides, SDK calls or independent command/missions. Paths and scoring
are pure proposals; only the central scheduler may commit an actual order.
"""
from collections import deque
from math import sqrt
from std_geometry import BLANK, KING, FORT, BLOCKED, MARSH, hex_distance


class RoadPlanner:
    def __init__(self, bot, reserves):
        self.bot = bot
        self.reserves = reserves
        self.path_cache = {}
        # This planner lives for one proposal callback. Bind its read-only
        # observation and helpers once, rather than forwarding every inner
        # graph lookup through __getattr__. A new callback binds fresh state.
        self.cells = bot.cells
        self.neighbors = bot.neighbors
        self.owned = bot.owned
        self.owned_set = frozenset(bot.owned)
        self.army = bot.army
        self.home = bot.home
        self.home_keep = bot.home_keep
        self.fort_reserves = bot.fort_reserves
        self.kings = bot.kings
        self.counter = bot.counter
        self.home_guard_hold = bot.home_guard_hold
        self.estimate_cell = bot.estimate_cell
        self.predict_king = bot.predict_king
        self.protected = bot.protected

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def field_spare(self, pos, excluded=()):
        # One signed ledger for source dispatch and every intermediate pickup.
        # A deficit consumes arriving force, even on a nonempty owned road.
        keep = max(1, self.reserves.get(pos, 1), self.fort_reserves.get(pos, 1))
        if pos == self.home:
            keep = max(keep, self.home_keep, self.home_guard_hold())
        # Counter already includes a growth allowance. Only this explicit
        # ordinary-road ablation varies the additional tie margin; actual
        # home, fort and explicit reserves still enter the same signed hold.
        margin = (self.bot.config.get('plain_guard_margin',1)
                  if self.cells[pos][0] == BLANK and pos != self.home else 1)
        return self.cells[pos][2] - max(keep, self.counter(pos, excluded=excluded)+margin)

    def field_spares(self):
        """Signed balance after all existing holds and visible source threats.

        Negative balances are charged to an incoming army before it can leave
        that road. A zero-unit road cannot create a free soldier.
        """
        key = ('field_spares',)
        if key not in self.path_cache:
            self.path_cache[key] = {
                p: self.field_spare(p) for p in self.owned}
        return self.path_cache[key]


    def pickup_paths(self, start, allowed, spare):
        """Maximum pickup on each shortest path in the current owned graph."""
        key = ('pickup_paths', start)
        if key in self.path_cache:
            return self.path_cache[key]
        if self.bot.config.get('indexed_pickup_paths', False):
            from std_road_graph import pickup_paths as indexed_pickup_paths
            indexed = indexed_pickup_paths(self, start, allowed, spare)
            if indexed is not None:
                return indexed
        distance, queue = {start: 0}, deque([start])
        levels = [[start]]
        while queue:
            p = queue.popleft()
            depth = distance[p] + 1
            if depth > 11:
                continue
            for n in self.neighbors[p]:
                if n not in allowed or n in distance:
                    continue
                distance[n] = depth
                if len(levels) <= depth:
                    levels.append([])
                levels[depth].append(n)
                queue.append(n)
        paths, gains = {start: (start,)}, {start: 0}
        for level in levels[1:]:
            for p in level:
                parents = [n for n in self.neighbors[p]
                           if distance.get(n) == distance[p] - 1 and n in paths
                           and spare[start] + gains[n] + spare[p] > 0]
                if parents:
                    prev = max(parents, key=lambda n: (gains[n], paths[n]))
                    paths[p] = paths[prev] + (p,)
                    gains[p] = gains[prev] + spare[p]
        self.path_cache[key] = paths
        # These are the same signed prefix balances used to admit each path.
        # Cache only within this planner's immutable observation and reserves.
        self.path_cache[('pickup_power', start)] = {
            pos: (spare[start], spare[start] + gains[pos]) for pos in paths}
        return paths


    def field_power(self, path, spare):
        """Return actual departure and arrival movable force, without growth."""
        send = spare.get(path[0], 0)
        if len(path) == 2 and path[1] in self.cells and self.cells[path[1]][1] != self.army:
            # Its defenders disappear on capture; other source threats remain.
            send = self.field_spare(path[0], excluded=(path[1],))
        force = send
        if send <= 0:
            return None
        for p in path[1:-1]:
            if p not in spare:
                return None
            force += spare[p]
            if force <= 0:
                return None
        return send, force


    def field_need(self, target, steps):
        key = ('field_need', target, steps)
        if key in self.path_cache:
            return self.path_cache[key]
        kind, owner, units = self.estimate_cell(target, steps)
        if kind == KING and owner in self.kings:
            units = self.predict_king(owner, steps)['upper']
        needed = units + self.counter(target) + 1 + (2 if kind == MARSH else 0)
        self.path_cache[key] = needed
        return needed


    def search_sources(self, sources, spare):
        """Limit optional road searches only after establishing an advantage.

        All sources retain direct capture checks in field_plans. Active
        carriers and the home depot remain eligible for a full road search.
        """
        budget = self.bot.config.get('maneuver_sources', 0)
        # Broad maneuver planning is a four-way policy. Three distinct
        # legally observed rivals are required before enlarging it.
        producers = sum(self.cells[p][0] in (KING,FORT) for p in self.owned)
        if len(getattr(self.bot,'known_owners',())) < 3 and producers < 4:
            budget = min(24,budget) if budget else 24
        threshold = self.bot.config.get('coverage_drought',0)
        if threshold and self.bot.tick-getattr(self.bot,'_frontier_last_progress',self.bot.tick) < threshold:
            budget = min(24,budget) if budget else 24
        if (not budget or not getattr(self.bot, '_advantage', False)
                or len(sources) <= budget):
            return sources
        selected = set(sources[:budget//2])
        focus = getattr(self.bot, '_information_focus', None)
        if focus:
            near_focus = sorted(sources, key=lambda p: (
                hex_distance(p, focus), -spare[p], p))
            selected.update(near_focus[:budget//4])
        information = []
        for src in sources:
            for target in self.neighbors[src]:
                cell = self.cells.get(target)
                if not cell or cell[1] == self.army or cell[0] in BLOCKED:
                    continue
                sight = len(self.bot.new_sight(target))
                if sight and spare[src] >= cell[2]+self.counter(target)+2:
                    information.append((sight, spare[src], src))
        for _, _, src in sorted(information, reverse=True):
            if len(selected) >= budget:
                break
            selected.add(src)
        for src in sources:
            if len(selected) >= budget:
                break
            selected.add(src)
        # A selected packet must remain eligible after shrinking below
        # another producer's stock. All intermediate pickups stay legal.
        task = getattr(self.bot, '_maneuver', None)
        if task and task['phase'] == 'ready' and task['path'][0] in sources:
            selected.add(task['path'][0])
        if self.home in sources:
            selected.add(self.home)
        return [p for p in sources if p in selected]


    def field_plans(self, opening=False):
        spare = self.field_spares()
        blocked = self.protected()
        allowed = {p for p in self.owned if p not in blocked and self.cells[p][0] != MARSH}
        sources = sorted((p for p in allowed if spare[p] > 0),
                         key=lambda p: (spare[p], p), reverse=True)
        all_sources = sources
        sources = self.search_sources(all_sources, spare)
        budget = self.bot.config.get('maneuver_sources', 0)
        self.bot.last_report['maneuver_source_budget'] = dict(
            limit=budget,departures=len(sources),roads=len(allowed),
            rear_producers_independent=True)
        targets = {}
        for p in sorted(allowed):
            for n in self.neighbors[p]:
                if n not in self.cells:
                    continue
                kind, owner, units = self.cells[n]
                if kind in BLOCKED or owner == self.army:
                    continue
                if opening and (kind != BLANK or owner != 0 or units > 1):
                    continue
                targets.setdefault(n, []).append(p)
        paths = {p: self.pickup_paths(p, allowed, spare) for p in sources}
        # Every source keeps direct captures; selected sources also search roads.
        depots = sorted(sources, key=lambda p: (spare[p], p), reverse=True)[:4]
        target_roads = sorted(targets.items())
        # Target requirements depend only on this observation and travel depth.
        # All sources share the same twelve entries instead of repeating a
        # method/cache lookup for every source, gate and candidate route.
        needs = {target: [None]+[self.field_need(target, depth)
                                for depth in range(1, 13)]
                 for target, _ in target_roads}
        best = {}
        # A road-search budget must not suppress any directly funded capture.
        # These six-edge local checks need no source-wide pickup tree.
        for src in all_sources:
            if src in paths:
                continue
            for target in self.neighbors[src]:
                if target not in needs:
                    continue
                route = (src,target)
                power = self.field_power(route,spare)
                if not power or power[1] < needs[target][1]:
                    continue
                bucket = best.setdefault(target,{})
                rank = power[1],route
                if 1 not in bucket or rank > bucket[1][0]:
                    bucket[1] = (rank,dict(path=route,target=target,
                        steps=1,send=power[0],arrival=power[1]))
        for src in sources:
            source_paths = paths[src]
            prefix_power = self.path_cache.get(('pickup_power', src), {})
            for target, roads in target_roads:
                required = needs[target]
                for road in roads:
                    direct = source_paths.get(road)
                    if not direct:
                        continue
                    # A multi-hop direct path has already paid every signed
                    # intermediate hold in pickup_paths. Its cached balance is
                    # exactly field_power's sum. Adjacent captures still need
                    # their target-excluded source counter, so use the original
                    # calculation for that case and for custom path providers.
                    direct_power = (prefix_power[road] if len(direct) > 1 and road in prefix_power
                                    else self.field_power(direct+(target,), spare))
                    steps = len(direct)
                    if direct_power and steps <= 12 and direct_power[1] >= required[steps]:
                        bucket = best.setdefault(target, {})
                        route = direct+(target,)
                        rank = direct_power[1], route
                        if steps not in bucket or rank > bucket[steps][0]:
                            bucket[steps] = (rank, dict(path=route, target=target,
                                steps=steps, send=direct_power[0], arrival=direct_power[1]))
                        continue
                    for depot in depots:
                        prefix = source_paths.get(depot)
                        suffix = paths[depot].get(road)
                        if not prefix or not suffix or depot in (src, road):
                            continue
                        route = prefix + suffix[1:] + (target,)
                        if len(route) > min(13, len(direct) + 3) or len(set(route)) != len(route):
                            continue
                        steps = len(route) - 1
                        if steps > 12:
                            continue
                        power = self.field_power(route, spare)
                        if not power or power[1] < required[steps]:
                            continue
                        bucket = best.setdefault(target, {})
                        rank = (power[1], route)
                        if steps not in bucket or rank > bucket[steps][0]:
                            bucket[steps] = (rank, dict(path=route, target=target,
                                steps=steps, send=power[0], arrival=power[1]))
        plans = []
        for target, bucket in sorted(best.items()):
            maximum = -1
            for steps, (rank, plan) in sorted(bucket.items()):
                if plan['arrival'] > maximum:
                    plans.append(plan)
                    maximum = plan['arrival']
        return plans


    def claim_capacity(self, target):
        """Bounded visible continuation estimate, not a promise of eight claims."""
        key = ('claim_capacity', target)
        if key not in self.path_cache:
            seen, queue = {target}, deque([target])
            while queue and len(seen) < 8:
                pos = queue.popleft()
                for n in self.neighbors[pos]:
                    data = self.cells.get(n)
                    if data and data[0:2] == (BLANK, 0) and data[2] <= 1 and n not in seen:
                        seen.add(n)
                        queue.append(n)
                        if len(seen) == 8:
                            break
            self.path_cache[key] = len(seen)
        return self.path_cache[key]


    def claim_rate(self, plan):
        guards = self.cells[plan['target']][2]
        capacity = self.claim_capacity(plan['target'])
        # Charge two troops per continuation if any visible candidate has a
        # defender; this avoids treating defended plains as free zeroes.
        defended = any(self.cells.get(n, (0, 0, 0))[0:2] == (BLANK, 0)
                       and self.cells[n][2] for n in self.neighbors[plan['target']])
        claims = min(capacity, 1 + max(0, plan['arrival'] - guards - 1) // (2 if defended else 1))
        return claims / float(plan['steps'] + claims - 1)



def same_order(task, order):
    return bool(order and all(task.get(k) == order.get(k) for k in ('src','dst','sent','role')))


def observe(bot):
    task = getattr(bot, '_maneuver', None)
    if not task:
        return
    if bot.kings or bot.calls > task['expires']:
        bot._maneuver = None
        return
    if task['phase'] == 'pending':
        if same_order(task, getattr(bot, '_observed_pending', None)) and bot._last_order_confirmed:
            task['path'] = task['path'][1:]
            if len(task['path']) < 2:
                bot._maneuver = None
                return
            task.update(phase='ready',expires=bot.calls+3)
        elif not same_order(task, bot.pending):
            bot._maneuver = None


def safe_plan(planner, plan):
    bot, path = planner.bot, plan['path']
    protected = bot.protected()
    if (len(path) < 2 or len(path) > 13 or len(set(path)) != len(path)
            or any(p not in bot.cells or bot.cells[p][1] != bot.army
                   or p in protected or bot.cells[p][0] == MARSH for p in path[:-1])
            or path[-1] not in bot.cells or bot.cells[path[-1]][1] == bot.army
            or bot.cells[path[-1]][0] in BLOCKED):
        return None
    power = planner.field_power(path,planner.field_spares())
    if not power or power[1] < planner.field_need(path[-1],len(path)-1):
        return None
    src,dst = path[:2]
    if dst in planner.owned_set and bot.cells[dst][2]+power[0] <= bot.counter(dst):
        return None
    return dict(plan,send=power[0],arrival=power[1],steps=len(path)-1,target=path[-1])


def propose(bot, choices, reserves, opening_override=None):
    bot._maneuver_candidates = {}
    opening = bool(bot.config.get('opening_area_steps',0) >= bot.calls and not bot.kings)
    if opening_override is not None:
        opening = bool(opening_override and not bot.kings)
    active = not bot.kings and (bot.config.get('mobilize',False) or opening)
    if not active:
        return False
    planner = RoadPlanner(bot,reserves)
    confirmed = any(cell[0] == FORT for cell in bot.memory.values())
    interval = bot.config.get('recon_interval',0)
    due = bool(interval and bot.calls-getattr(bot,'_maneuver_recon_last',0) >= interval)
    plans = planner.field_plans(opening=opening)
    task = getattr(bot,'_maneuver',None)
    continuation = None
    if task and task['phase'] == 'ready':
        continuation = safe_plan(planner,dict(path=tuple(task['path'])))
        if continuation:
            plans.append(continuation)
        else:
            bot._maneuver = None
    focus = getattr(bot,'_information_focus',None) or bot.focus()
    close_threat = any(bot.risk_dist.get(p,999) <= 6 for p in bot.enemies)
    urgent = any(h <= 6 for h,_ in bot.last_report.get('defense_shortages',[]))
    bot.last_report['maneuver'] = dict(opening=opening,confirmed_fort=confirmed,
        recon_due=due,plans=len(plans),replaces='continuous_frontier',urgent=urgent)
    if not plans:
        return False
    if urgent:
        return True
    proposals = {}
    command_order = []
    for raw in plans:
        plan = safe_plan(planner,raw)
        if not plan:
            continue
        target = plan['target'];src,dst=plan['path'][:2]
        kind,owner,units = bot.cells[target]
        sight=bot.new_sight(target)
        recon=bool(due and sight)
        continuing=bool(continuation and plan['path'] == continuation['path'])
        if opening:
            score=(350 if close_threat else 800)+100*planner.claim_rate(plan)
            score+=min(30,sqrt(plan['arrival']))/float(plan['steps'])
            score+=.01*len(sight)+(.01*len(sight & bot.hill_hints) if not confirmed else 0)
        else:
            value=bot.config.get('production_value',600) if kind == FORT else 58
            value+=(8 if recon else 4)*len(sight)
            value+=0 if confirmed else 12*len(sight & bot.hill_hints)
            toward=hex_distance(bot.home,focus)-hex_distance(target,focus)
            value+=(6 if recon else 2)*max(-12,min(12,toward))
            value+=12 if owner > 0 else 0
            surplus=max(0,plan['arrival']-planner.field_need(target,plan['steps']))
            carry=1.0+min(8,surplus)/8.0
            score=value*carry/((plan['steps']+1)*(1.0+units/float(max(1,plan['arrival']))))
            # An overdue reconnaissance opportunity competes below an ordinary
            # interception (500) and never preempts timed king survival.
            if recon:
                score=320+min(150,score)
        if continuing:
            score*=1.05
        mode='road_opening' if opening else 'road_recon' if recon else 'road_mobilize'
        proposal=(score,src,dst,plan['send'],mode,target)
        key=proposal[1:]
        previous=proposals.get(key)
        # Future paths can share one executable command. Keep its best score
        # and that exact path together; equal scores retain the first path.
        if previous is None:
            command_order.append(key)
        if previous is None or score > previous[0]:
            proposals[key]=proposal
            bot._maneuver_candidates[key]=dict(plan,proposal_score=score,
                opening=opening,recon=recon,continuing=continuing)
    choices.extend(proposals[key] for key in command_order)
    # A single frontier generator owns this callback; no duplicate merge/scout
    # action system is appended. King and defense proposals still compete.
    return True


def committed(bot,src,dst,amount,mode,target):
    plan=getattr(bot,'_maneuver_candidates',{}).get((src,dst,amount,mode,target))
    if not plan or not same_order(dict(src=src,dst=dst,sent=amount,role=mode),bot.pending):
        bot._maneuver=None
        return
    bot._maneuver=dict(path=plan['path'],phase='pending',expires=bot.calls+4,
        **{k:bot.pending[k] for k in ('src','dst','sent','role')})
    if plan['recon']:
        bot._maneuver_recon_last=bot.calls
    bot.last_report.update(field_path=plan['path'],field_steps=plan['steps'],
        field_arrival=plan['arrival'],field_send=plan['send'],
        field_continuing=plan['continuing'],field_recon=plan['recon'])
