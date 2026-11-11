"""Receding-horizon pressure on a currently visible enemy king.

March funding ends at a neighboring hex. It never includes the king's stock
or hypothetical later reinforcements. The actual strike is checked again on
the next observation. Only the first order is issued, from current surplus.
"""
from heapq import heappop, heappush
from math import ceil, sqrt

from std_geometry import BLANK, KING, FORT, MARSH, BLOCKED


def approach_tree(bot, target, limit=18):
    """Known roads towards any king neighbor; home is an endpoint only."""
    parent, costs, steps = {}, {}, {}
    queue = []
    for pos in bot.neighbors[target]:
        data = bot.cells.get(pos)
        if data and data[0] not in BLOCKED+(KING, MARSH):
            parent[pos], costs[pos], steps[pos] = None, 0.0, 0
            heappush(queue, (0.0, pos))
    while queue:
        cost, pos = heappop(queue)
        if costs[pos] != cost or steps[pos] >= limit or pos == bot.home:
            continue
        kind, owner, units = bot.cells[pos]
        edge = 1.0+(units*.10+.6 if owner != bot.army else 0.0)
        for prev in bot.neighbors[pos]:
            data = bot.cells.get(prev)
            if (not data or prev == target or data[0] in BLOCKED+(MARSH,)
                    or data[0] == KING and prev != bot.home):
                continue
            value = cost+edge
            if value < costs.get(prev, float('inf')):
                parent[prev], costs[prev], steps[prev] = pos, value, steps[pos]+1
                heappush(queue, (value, prev))
    return parent, steps


def funded_approach(bot, route, movable, reserves=None):
    """Every prefix is paid now; later friendly pickups cannot fund a gate."""
    if reserves is None and bot.config.get('frontier_signed_ledger', False):
        reserves = getattr(bot, '_active_reserves', {})
    power = movable.get(route[0], 0)
    minimum = (1 if bot.config.get('king_small_collection', False)
               and bot.cells[route[0]][0] == BLANK else 3)
    if power < minimum:
        return None
    for depth, pos in enumerate(route[1:], 1):
        kind, owner, units = bot.cells[pos]
        if owner == bot.army:
            if reserves is None:
                power += -1 if units == 0 else movable.get(pos, 0)
            else:
                power += units-max(1, reserves.get(pos, 1))
        else:
            growth = int(ceil(depth*(.52 if kind == FORT else .02))) if owner > 0 else 0
            power -= units+growth+1
        if power <= 0:
            return None
    return power


def first_hop_surplus(bot, src, dst, amount):
    """Current arriving stock, with one growth margin on hostile terrain."""
    _, owner, units = bot.cells[dst]
    return amount+units if owner == bot.army else amount-units-(1 if owner > 0 else 0)


def propose_idle_field(bot, choices, movable):
    """Use a waiting command to approach from an independent field stack.

    Ordinary attack/defense and productive orders retain their ranking. This
    optional ablation changes only a currently winning wait proposal, before
    the existing safety arbitration. It cannot release a king/fort reserve.
    """
    if not bot.config.get('king_idle_field_approach', False) or not choices:
        return
    selected=max(choices)
    if selected[4] not in ('skirmish_wait','tactical_wait','bank'):
        return
    if any(h<=6 for h,_ in bot.last_report.get('defense_shortages',())):
        return
    limit=bot.config.get('king_idle_field_steps',3)
    records=[]
    for target in bot.enemies:
        if bot.cells[target][0]!=KING:
            continue
        parent,steps=approach_tree(bot,target,limit)
        eligible=[p for p in bot.owned if bot.cells[p][0] not in (KING,FORT,MARSH)
            and bot.risk_dist.get(p,0)>2 and 0<steps.get(p,0)<=limit]
        sources=set(sorted(eligible,key=lambda p:(movable.get(p,0),p),reverse=True)[:8])
        sources.update(sorted(eligible,key=lambda p:(steps[p],-movable.get(p,0),p))[:8])
        for src in sorted(sources):
            amount=min(movable.get(src,0),bot.cells[src][2]-bot.counter(src)-1)
            if amount<3:
                continue
            route=[src]
            while parent[route[-1]] is not None:
                route.append(parent[route[-1]])
            current=dict(movable)
            current[src]=amount
            power=funded_approach(bot,route,current)
            if power is None:
                continue
            dst=route[1]
            residual=first_hop_surplus(bot,src,dst,amount)
            counter=bot.counter(dst,excluded=(target,))
            if residual<=counter:
                continue
            score=selected[0]+1+100.0/(len(route)-1)+sqrt(power)*.01
            choices.append((score,src,dst,amount,'king_advance',target))
            records.append(dict(source=src,target=target,route=route,dispatch=amount,
                replaced_wait=selected[4],current_stage_surplus=power,
                first_hop_stock=residual,visible_nonking_counter=counter,
                source_held=bot.cells[src][2]-amount,source_counter=bot.counter(src),
                king_stock=bot.cells[target][2],strike_funded=False))
    bot.last_report['king_idle_field_approach']=dict(approaches=records,
        replaced_wait=selected[4],command_limit=limit,
        authority='ordinary surplus; existing safety arbitration applies')


def propose_merge(bot, choices, movable):
    """Redirect the selected field merge, keeping its source and packet.

    Closing on the king does not require funding its eventual capture. Current
    source stock, each march prefix and nonking first-hop counters still gate
    the new direction. A currently active transferred policy retains ownership.
    """
    if not bot.config.get('king_merge_approach', False) or not choices:
        return
    selected = max(choices)
    _, src, old_dst, amount, mode, _ = selected
    coordinator = getattr(bot, '_opening_coordinator', None)
    if (mode != 'merge' or src not in bot.cells
            or bot.cells[src][0] in (KING, MARSH)
            or bot.risk_dist.get(src, 0) <= 2
            or not 3 <= amount <= movable.get(src, 0)
            or any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ()))
            or coordinator and coordinator.started is not None and not coordinator.finished):
        return
    records = []
    for target in bot.enemies:
        if bot.cells[target][0] != KING:
            continue
        if bot.cells[src][2]-amount <= bot.counter(src, excluded=(target,)):
            continue
        parent, steps = approach_tree(bot, target, 3)
        if not 0 < steps.get(src, 0) <= 3:
            continue
        route = [src]
        while parent[route[-1]] is not None:
            route.append(parent[route[-1]])
        if route[1] == old_dst:
            continue
        old_steps = steps.get(old_dst)
        new_steps = steps[route[1]]
        if old_steps is not None and new_steps >= old_steps:
            continue
        current = dict(movable)
        current[src] = amount
        power = funded_approach(bot, route, current,
            reserves=getattr(bot, '_active_reserves', {}))
        if power is None:
            continue
        dst = route[1]
        residual = first_hop_surplus(bot, src, dst, amount)
        counter = bot.counter(dst, excluded=(target,))
        if residual <= counter:
            continue
        score = selected[0]+1+100.0/(len(route)-1)+sqrt(power)*.01
        choices.append((score, src, dst, amount, 'king_advance', target))
        records.append(dict(source=src, previous_destination=old_dst,
            target=target, route=route, dispatch=amount, current_stage_surplus=power,
            first_hop_stock=residual, visible_nonking_counter=counter,
            king_stock=bot.cells[target][2], strike_funded=False,
            old_remaining_steps_within_limit=old_steps, new_remaining_steps=new_steps))
    if records:
        bot.last_report['king_merge_approach'] = dict(approaches=records,
            source_and_dispatch_unchanged=True, command_limit=3,
            authority='selected merge source and current ordinary surplus; existing safety arbitration applies')


def approach_score(bot, target, route, power, dispatch=None):
    commands = len(route)-1
    if (not bot.config.get('king_pressure_throughput', False)
            or not bot.config.get('frontier_signed_ledger', False)):
        return 650000.0+6000.0/commands+sqrt(power)
    stage = route[-1]
    kind, owner, units = bot.cells[stage]
    holds = getattr(bot, '_active_reserves', {})
    staged = max(0, units-max(1, holds.get(stage, 1))) if owner == bot.army else 0
    # The existing stage army is present before this donor moves. Counting it
    # again would make every tiny packet appear to transport the whole stack.
    marginal = max(0, power-staged)
    if dispatch is not None and bot.config.get('king_marginal_contribution', False):
        # A tiny donor may join a large intermediate army, but must not claim
        # that army's whole throughput as its own useful first departure.
        marginal = min(marginal, dispatch)
    # Value only a useful contribution to the visible capture gap. King income
    # is a timing margin; no unobserved reinforcement is invented here.
    king = target
    deficit = max(0, bot.cells[king][2]+1+int(ceil(.52*commands))-staged)
    rate = min(marginal, deficit)/float(commands)
    if (bot.config.get('king_contact_throughput', False)
            and getattr(bot, 'last_report', {}).get('objective_state', {}).get('owned_producers', 1) <= 1
            and getattr(bot, 'risk_dist', {}).get(king, 999) <= 6
            and marginal < max(1 if commands == 1 else 8, deficit*.15) and power < bot.cells[king][2]+2):
        return 100.0+40.0*rate+sqrt(power)
    # With several known rivals, a token delivery toward one unfunded
    # king must compete with production and other fronts on throughput.
    # A currently funded capture retains the existing strike priority.
    if (len(getattr(bot,'known_owners',())) >= 2 and power < bot.cells[king][2]+2
            and bot.cells[king][2]+2+int(ceil(.52*commands))-power > max(8,bot.cells[king][2]*.15)
            and marginal < max(4 if commands == 1 else 16, deficit*.15)):
        return 100.0+40.0*rate+sqrt(power)
    # Keep the original pressure tier below repriced, completely funded assault.
    return 650000.0+6000.0*rate/(1.0+rate)+sqrt(power)


def propose(bot, choices, movable):
    if not bot.config.get('king_forward_pressure', False):
        return
    # Existing timed defense remains ahead when an observed deadline is short.
    if any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', ())):
        bot.last_report['king_pressure'] = dict(blocked='current six-step defense shortage')
        return
    # An executable, completely funded king route must also beat economic or
    # local-search waiting. Immediate elimination and the isolated bridge keep
    # their higher priorities. This is an attack preference, not a minimax proof.
    repriced = 0
    for index, proposal in enumerate(choices):
        score, src, dst, amount, mode, target = proposal
        if (mode == 'assault' and target in bot.cells
                and bot.cells[target][0] == KING
                and bot.cells[target][1] not in (0, bot.army)):
            choices[index] = (max(score, 700000.0+score), src, dst, amount, mode, target)
            repriced += 1
    records = []
    for target in bot.enemies:
        if bot.cells[target][0] != KING:
            continue
        parent, steps = approach_tree(bot, target)
        eligible = [p for p in bot.owned if steps.get(p, 0) > 0
            and movable.get(p, 0) >= (1 if bot.config.get('king_small_collection', False)
                and bot.cells[p][0] == BLANK else 3)]
        sources = set(sorted(eligible, key=lambda p: (movable[p], p), reverse=True)[:8])
        sources.update(sorted(eligible, key=lambda p: (steps[p], -movable[p], p))[:8])
        for src in sorted(sources):
            route = [src]
            while parent[route[-1]] is not None:
                route.append(parent[route[-1]])
            power = funded_approach(bot, route, movable)
            if power is None:
                continue
            dst, amount = route[1], movable[src]
            residual = first_hop_surplus(bot, src, dst, amount)
            # The king's own possible sortie is not a reserve that must be
            # amassed before approaching. Other currently visible local stacks
            # still constrain the first hop; no distant stock is invented.
            counter = bot.counter(dst, excluded=(target,))
            if residual <= counter:
                continue
            commands = len(route)-1
            score = approach_score(bot, target, route, power, amount)
            choices.append((score, src, dst, amount, 'king_advance', target))
            records.append(dict(source=src, stage=route[-1], target=target,
                commands=commands, route=route, dispatch=amount,
                current_stage_surplus=power, first_hop_stock=residual,
                visible_nonking_counter=counter, king_stock=bot.cells[target][2],
                strike_funded=False))
    bot.last_report['king_pressure'] = dict(funded_routes_repriced=repriced, approaches=records)
