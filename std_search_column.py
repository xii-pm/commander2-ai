"""Fund a route to genuinely unseen frontier cells from public stock.

Refreshing an old enemy border is not search progress. A superior economy can
pay a short column through known territory to open the next unseen boundary.
Every continuation requires the actual previous order to be witnessed.
"""
from std_recon import first_contact_search_active
from collections import deque
from heapq import heappop, heappush
from math import ceil
from std_geometry import BLANK, FORT, hex_distance
from std_recon import search_memory

COMMAND_LIMIT = 12
PROGRESS_WINDOW = 64
HOME_BUFFER = 32


def source_hold(bot, pos, reserves, cache):
    """Use the same current reserve at departure and intermediate road cells."""
    if pos not in cache:
        keep = max(1, reserves.get(pos, 1), bot.fort_reserves.get(pos, 1))
        if bot.cells[pos][0] == FORT:
            keep = max(keep, bot.counter(pos)+1)
        if pos == bot.home:
            keep = max(keep, bot.home_keep, bot.home_guard_hold(),
                       max(bot.last_report.get('threat_curve') or [0])+HOME_BUFFER)
        cache[pos] = keep
    return cache[pos]


def search_terrain(bot, remembered):
    """Return current terrain or conservative estimates of observed history."""
    if not remembered:
        return bot.cells
    terrain = {}
    for pos, old in bot.memory.items():
        cell = bot.estimate_cell(pos)
        if cell is None:
            continue
        kind, owner, units = cell
        if pos not in bot.cells and owner == 0:
            # A historically neutral cell may have been claimed in the fog.
            units += 2+int(ceil(max(0,bot.tick-old[3])*.12))
        terrain[pos] = kind,owner,units
    return terrain


def propose(bot, choices, reserves):
    bot._search_column_options = {}
    if not bot.config.get('funded_search_column', False):
        return
    # Long approaches become affordable only after the observed economy
    # matures. Task progress still requires an actually confirmed order.
    state = bot.last_report.get('objective_state', {})
    duel = bool(getattr(bot,'_single_capital_fortress',False) and bot.eliminated
        and len(set(bot.known_owners)-set(bot.eliminated))==1)
    bot.last_report['duel_search'] = dict(active=duel,owned_producers=state.get('owned_producers',0),
        home=bot.cells[bot.home][2],required_home=max(bot.last_report.get('threat_curve') or [0])+HOME_BUFFER)
    sustained = (bot.config.get('sustained_search', False) and bot.calls >= 600
        and state.get('owned_producers', 0) >= (4 if duel else 20)
        and bot.cells[bot.home][2] >= max(bot.last_report.get('threat_curve') or [0])+HOME_BUFFER)
    command_limit = 32 if sustained else COMMAND_LIMIT
    task = getattr(bot, '_search_column', None)
    observed = getattr(bot, '_observed_pending', None)
    current = None
    if task:
        if task.get('pending'):
            if (observed and bot._last_order_confirmed
                    and all(observed[k] == task[k] for k in ('src','dst','sent','role'))):
                task.update(current=task['dst'],pending=False,expires=bot.calls+COMMAND_LIMIT)
            else:
                task = None
        if task and task['commands'] >= command_limit:
            bot._search_column_after = bot.calls+COMMAND_LIMIT
            task = None
        if task and (bot.calls > task['expires'] or task['current'] not in bot.owned
                     or observed and observed['src'] == task['current']
                        and observed['role'] != 'search_column'):
            task = None
        if task:
            current = task['current']
    bot._search_column = task
    state = bot.last_report.get('objective_state', {})
    progress = getattr(bot, '_search_progress_samples', None)
    if progress is None:
        progress = bot._search_progress_samples = deque()
    progress.append((bot.calls, len(bot.memory)))
    while len(progress) > 1 and progress[1][0] <= bot.calls-PROGRESS_WINDOW:
        progress.popleft()
    slow_coverage = (bot.calls >= 600 and state.get('owned_producers', 0) >= 20
        and bot.calls-progress[0][0] >= PROGRESS_WINDOW
        and len(bot.memory)-progress[0][1] < 24)

    # Search must not spend the command needed to establish the next defense
    # line. Six-step solvency alone can hide a barely funded approaching raid.
    # Leave a current-stock buffer beyond the full observed twelve-step curve;
    # proportional insurance and timed rescue still retain their own policies.
    search_home_keep = max(bot.last_report.get('threat_curve') or [0])+HOME_BUFFER
    if (bot.calls < getattr(bot, '_search_column_after', 0)
            or bot.cells[bot.home][2] < search_home_keep
            or any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ()))
            or any(bot.tick-m['seen'] <= bot.KING_MAX_AGE for m in bot.kings.values())
            or not getattr(bot, '_advantage', False)
            or state.get('owned_producers', 0) < 6
            or state.get('visible_friendly_units', 0) < (1.25 if duel else 2)*state.get('visible_enemy_units', 0)
            or not duel and current is None and not slow_coverage
               and bot.tick-getattr(bot, '_frontier_last_progress', bot.tick) < PROGRESS_WINDOW):
        return
    # Only observed history may extend the planning graph. The next order
    # still requires current visibility and every observation replans it.
    remembered = (bot.config.get('memory_search_approach', False)
        and bot.calls >= 600 and state.get('owned_producers', 0) >= (4 if duel else 20))
    terrain = search_terrain(bot, remembered)
    allowed = {p for p,c in terrain.items() if c[0] in (BLANK,FORT)
               or p == bot.home}
    owned = set(bot.owned)
    enemy_front = [p for p,c in search_memory(bot).items()
                   if c[1] not in (0,bot.army) and c[1] not in bot.eliminated
                   and (first_contact_search_active(bot) or bot.tick-c[3] <= 100)]
    goals = {}
    for pos in allowed-owned:
        gain = len(bot.new_sight(pos))
        if gain and ((terrain[pos][1] > 0 if not first_contact_search_active(bot)
                      else search_memory(bot).get(pos,(0,0))[1] not in (0,bot.army)
                      and search_memory(bot)[pos][1] not in bot.eliminated)
                     or any(hex_distance(pos, p) <= 3 for p in enemy_front)):
            goals[pos] = gain
    if not goals:
        return
    parent, distance, endpoint = {}, {}, {}
    holds = {}
    queue = []
    for p,gain in goals.items():
        distance[p], parent[p], endpoint[p] = 0, None, p
        heappush(queue,(0,-gain,p))
    while queue:
        cost, _, pos = heappop(queue)
        if cost != distance[pos] or pos == bot.home:
            continue
        data = terrain[pos]
        loss = (data[2]+1 if data[1] != bot.army else
                max(0,source_hold(bot,pos,reserves,holds)-data[2]))
        for src in bot.neighbors[pos]:
            if src not in allowed:
                continue
            trial = cost+8+loss
            if trial < distance.get(src, float('inf')):
                distance[src], parent[src], endpoint[src] = trial, pos, endpoint[pos]
                heappush(queue,(trial,-goals[endpoint[src]],src))
    candidates = []
    waiting = bool(choices and max(choices)[4] in ('skirmish_wait','tactical_wait','bank'))
    for src in bot.owned:
        if src not in parent or parent[src] is None:
            continue
        keep = source_hold(bot, src, reserves, holds)
        cap = min(bot.available(src),bot.cells[src][2]-keep)
        if cap < (8 if src == current else 32):
            continue
        route = [src]
        while parent[route[-1]] is not None and len(route) <= command_limit:
            route.append(parent[route[-1]])
        if parent[route[-1]] is not None:
            continue
        if route[1] not in bot.cells:
            continue
        steps = len(route)-1
        # A continuation must reach its next information gain within the
        # remaining command allowance. A different source starts a new
        # column; it cannot inherit an almost exhausted mission counter.
        continuing = src == current
        if task and (not continuing or steps > command_limit-task['commands']):
            continue
        # Do not borrow intermediate friendly stocks or future income. Include
        # visible producer growth over the march and a surviving field packet.
        spent, required = 0, 32
        for pos in route[1:]:
            kind,owner,units = terrain[pos]
            if owner != bot.army:
                spent += units+1+(steps if kind == FORT else 0)
            else:
                # A protected road with insufficient stock absorbs part of
                # the column. That deficit is a cost, never an assumed pickup.
                spent += max(1,source_hold(bot,pos,reserves,holds)-units)
            required = max(required,spent+bot.counter(pos)+16)
        if sustained:
            # Pick up only currently observed friendly stock. Leave every road
            # cell its current protection; never borrow projected production.
            power = cap
            feasible = True
            for pos in route[1:]:
                kind, owner, units = terrain[pos]
                if owner == bot.army and pos in bot.cells:
                    power += units-source_hold(bot,pos,reserves,holds)
                elif owner != bot.army:
                    power -= units+1+(steps if kind == FORT else 0)
                else:
                    power -= 1
                if power < bot.counter(pos)+16:
                    feasible = False
                    break
            if not feasible:
                continue
        elif cap < required:
            continue
        full_field = (bot.config.get('large_field_columns', False)
                      and bot.cells[src][0] == BLANK)
        amount = cap if sustained or src == current or full_field else min(cap,max(192,required+128))
        goal = route[-1]
        score = 1400.0+20*goals[goal]/float(steps)-required/float(amount+1)
        if src == current:
            score += 200
        if waiting:
            score = max(score,500200.0+goals[goal])
        if duel:score+=200000
        choice = (score,src,route[1],amount,'search_column',goal)
        candidates.append(choice)
        bot._search_column_options[choice[1:]] = dict(src=src,dst=route[1],sent=amount,
            role='search_column',route=route,required=required,gain=goals[goal],
            remembered_route=any(p not in bot.cells for p in route),
            sustained=bool(sustained),command_limit=command_limit,
            commands=task['commands']+1 if continuing else 1)
    if candidates:
        best = max(candidates)
        choices.append(best)
        bot.last_report['search_column'] = bot._search_column_options[best[1:]]


def committed(bot, src, dst, amount, mode, target):
    selected = getattr(bot, '_search_column_options', {}).get((src,dst,amount,mode,target))
    if selected:
        bot._search_column = dict(selected,pending=True)
