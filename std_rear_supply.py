"""Confirmed rear convoys on one shared owned-road tree.

A rear fort dispatch is followed through its intermediate field cells. New
producer trickles cannot repeatedly displace the packet already on the road.
"""
from collections import deque
from math import sqrt
from std_geometry import KING, FORT, BLOCKED, MARSH


def bulk_search(bot):
    """A stalled superior army needs a column to cross already-known ground."""
    return (bot.config.get('bulk_rear_search', False)
        and getattr(bot, '_advantage', False)
        and bot.tick-getattr(bot, '_frontier_last_progress', bot.tick) >= 20
        and not any(bot.tick-model['seen'] <= bot.KING_MAX_AGE
                    for model in bot.kings.values()))


def observe(bot):
    task = getattr(bot, '_rear_convoy', None)
    if not task:
        return
    order = getattr(bot, '_observed_pending', None)
    if task['phase'] == 'pending':
        same = order and all(task[k] == order[k] for k in ('src','dst','sent','role'))
        if same and bot._last_order_confirmed:
            if task['dst'] == task['frontline']:
                # A delivered packet hands commands back to the front. A new
                # convoy cannot continuously outrank the attack it just paid.
                bot._rear_supply_after = bot.calls + max(3, task['commands'])
                bot._rear_convoy = None
            else:
                task.update(current=task['dst'], phase='ready', expires=bot.calls+6)
        elif not bot.pending or not same:
            bot._rear_convoy = None
    elif (bot.calls > task['expires'] or task['current'] not in bot.owned
          or order and order['src'] == task['current'] and order['role'] != 'rear_supply'):
        bot._rear_convoy = None


def frontline(bot, allowed, reserves):
    kings = {m['pos'] for m in bot.kings.values()
             if bot.tick-m['seen'] <= bot.KING_MAX_AGE}
    demands, king_fronts = {}, set()
    for pos in sorted(allowed):
        if pos == bot.home:
            continue
        gaps = []
        funded = False
        for target in bot.neighbors[pos]:
            data = bot.cells.get(target)
            if not data or data[0] in BLOCKED or data[1] == bot.army:
                continue
            if data[1] == 0 and data[0] != FORT:
                continue
            if (getattr(bot,'_advantage',False) and data[0] == FORT
                    and target in getattr(bot,'_contested_forts',{})):
                continue
            keep = max(1,reserves.get(pos,1),bot.fort_reserves.get(pos,1),
                       bot.counter(pos,excluded=(target,))+1)
            have = max(0,bot.cells[pos][2]-keep)
            needed = (data[2]+2 if target in kings else
                      data[2]+bot.counter(target)+2)
            gap = needed-have
            if gap <= 0:
                funded = True
            else:
                gaps.append(gap)
                if target in kings:
                    king_fronts.add(pos)
        # An army with a paid breakthrough should execute it. If every gate
        # is blocked, fund the cheapest opening rather than the largest enemy.
        if gaps and not funded:
            demands[pos] = min(gaps)
        else:
            king_fronts.discard(pos)
    if king_fronts:
        return sorted(king_fronts), True, demands
    return sorted(demands), False, demands


def propose(bot, choices, reserves):
    bot._rear_candidates = {}
    if not bot.config.get('rear_producer_supply', False):
        return
    if bot.calls < getattr(bot,'_rear_supply_after',0):
        return
    if any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ())):
        return
    allowed = {p for p in bot.owned if bot.cells[p][0] != MARSH}
    fronts, king_front, demands = frontline(bot, allowed, reserves)
    task = getattr(bot, '_rear_convoy', None)
    bulk = bulk_search(bot) or bool(task and task.get('bulk'))
    current = task['current'] if task and task['phase'] == 'ready' else None
    if current is not None:
        if task['frontline'] in fronts:
            fronts = [task['frontline']]
        else:
            # The funded front can act now. Feeding it further would steal
            # the very attack command that this convoy was meant to enable.
            bot._rear_convoy = None
            bot._rear_supply_after = bot.calls+max(3,task['commands'])
            return
    if current is None:
        # A long transport schedule must solve a material force deficit.
        # Tiny border trades are paid by nearby growth and ordinary expansion.
        fronts = [p for p in fronts if demands[p] >= 24]
    if not fronts:
        return
    parent, distance = {p: None for p in fronts}, {p: 0 for p in fronts}
    queue = deque(fronts)
    while queue:
        pos = queue.popleft()
        for nxt in bot.neighbors[pos]:
            if nxt in allowed and nxt not in distance:
                distance[nxt], parent[nxt] = distance[pos]+1, pos
                queue.append(nxt)
    records = []
    proposals = []
    for src in bot.owned:
        continuing = src == current
        steps = distance.get(src, 0)
        depot = (bot.cells[src][0] == FORT or
                 bulk and bot.cells[src][0] == KING and not bot.home_contact_risk)
        if not steps or not continuing and (not depot or steps < 3):
            continue
        keep = max(1, reserves.get(src, 1), bot.fort_reserves.get(src, 1), bot.counter(src)+1)
        if bulk and src == bot.home:
            # Safe king surplus is a depot too. Cover the full currently
            # visible twelve-command threat without borrowing future income.
            keep = max(keep, bot.home_keep, bot.home_guard_hold(),
                       max(bot.last_report.get('threat_curve') or [0]))
        amount = bot.cells[src][2]-keep
        if amount < (8 if continuing else max(24, 4*steps)):
            continue
        route = [src]
        while parent[route[-1]] is not None:
            route.append(parent[route[-1]])
        if not continuing and not bulk:
            amount = min(amount, demands[route[-1]]+steps)
        power = amount
        for pos in route[1:]:
            power += bot.cells[pos][2]-max(1, reserves.get(pos, 1), bot.counter(pos)+1)
            if power <= 0:
                break
        if power <= 0:
            continue
        dst = route[1]
        if bot.cells[dst][2]+amount <= bot.counter(dst):
            continue
        rate = amount/float(steps)
        score = min(500.0, 200.0+3*sqrt(amount)+2*rate)
        if continuing:
            score += 80.0
        if king_front:
            score += 610000.0
        choice = (score, src, dst, amount, 'rear_supply', route[-1])
        proposals.append(choice)
        plan = dict(source=src, destination=dst, frontline=route[-1], distance=steps,
                    dispatch=amount, source_keep=keep, continuing=continuing,
                    arrival_gap=demands[route[-1]],bulk=bool(bulk))
        bot._rear_candidates[choice[1:]] = plan
        records.append(plan)
    if records:
        bot.last_report['rear_supply'] = records
        best = max(p[0] for p in proposals)
        for choice in proposals:
            if choice[1] == current:
                choice = (max(choice[0],best+1),)+choice[1:]
            choices.append(choice)


def committed(bot, src, dst, amount, mode, target):
    if mode != 'rear_supply':
        return
    plan = bot._rear_candidates.get((src,dst,amount,mode,target))
    if not plan:
        return
    bot._rear_convoy = dict(src=src,dst=dst,sent=amount,role=mode,
                            phase='pending',current=src,expires=bot.calls+6,
                            frontline=plan['frontline'],
                            bulk=plan.get('bulk',False),
                            commands=(bot._rear_convoy['commands']+1
                                      if plan['continuing'] else 1))
    bot.last_report['rear_convoy_selected'] = plan
