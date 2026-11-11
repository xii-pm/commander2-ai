"""Bounded FIFO defense schedules, adapted from 易如反掌/yr_mobilization.py.

The model uses current friendly roads and static troops. It preserves every
arrival deadline under one command per step; future enemy road cuts remain an
uncertainty. This module does not import an opponent or native authority state.
"""
from collections import deque


def arrival_curve(moves, target, horizon):
    total, curve = 0, [0]
    for _, dst, amount in moves:
        if dst == target:
            total += amount
        curve.append(total)
    return tuple(curve+[total]*max(0, horizon+1-len(curve)))


def frontier(sequences, target, horizon):
    unique = {}
    for moves in sequences:
        key = len(moves), arrival_curve(moves, target, horizon)
        if key not in unique or moves < unique[key]:
            unique[key] = moves
    selected = []
    for (cost, curve), moves in sorted(unique.items(),
            key=lambda item: (item[0][0], tuple(-n for n in item[0][1]), item[1])):
        if not any(len(prior) <= cost and all(a >= b for a,b in zip(earlier, curve))
                   for prior,earlier in selected):
            selected.append((moves,curve))
    return [moves for moves,_ in selected]


def interleavings(left, right):
    if not left:
        yield right
    elif not right:
        yield left
    else:
        for tail in interleavings(left[1:], right):
            yield (left[0],)+tail
        for tail in interleavings(left, right[1:]):
            yield (right[0],)+tail


def forwardings(moves, src, dst, balance, limit, prefix=()):
    if not moves:
        yield prefix
    if len(prefix) >= limit:
        return
    if moves:
        move = moves[0]
        gain = move[2] if move[1] == src else 0
        for result in forwardings(moves[1:], src, dst, balance+gain, limit, prefix+(move,)):
            yield result
    if balance > 0:
        for result in forwardings(moves, src, dst, 0, limit, prefix+((src,dst,balance),)):
            yield result


def schedules(neighbors, cells, army, home, horizon=5):
    """Nondominated arrival curves on one observed friendly BFS tree."""
    parent, distance = {home: None}, {home: 0}
    queue = deque([home])
    while queue:
        p = queue.popleft()
        if distance[p] >= horizon:
            continue
        for n in neighbors[p]:
            if n not in distance and n in cells and cells[n][1] == army:
                parent[n], distance[n] = p, distance[p]+1
                queue.append(n)
    children = {p: [] for p in distance}
    for p in distance:
        if p != home:
            children[parent[p]].append(p)
    tables = {}
    for p in sorted(distance, key=lambda p: (-distance[p],p)):
        limit = horizon-distance[p]+1 if p != home else horizon
        inputs = [()]
        for child in sorted(children[p]):
            combinations = []
            for left in inputs:
                for right in tables[child]:
                    if len(left)+len(right) <= limit-int(p != home):
                        combinations.extend(interleavings(left,right))
            inputs = frontier(combinations,p,horizon)
        if p == home:
            tables[p] = inputs
        else:
            outputs = []
            for moves in inputs:
                outputs.extend(forwardings(moves,p,parent[p],cells[p][2]-1,limit))
            tables[p] = frontier(outputs,parent[p],horizon)
    return tables[home]


def prefix_slack(neighbors, cells, army, home, first, suffix, threat):
    """Return worst deadline balance, or None for an unfunded suffix."""
    units = {p:d[2] for p,d in cells.items() if d[1] == army}
    horizon, balances = len(threat)-1, []
    moves = (first,)+suffix
    for step in range(1,horizon+1):
        move = moves[step-1] if step <= len(moves) else None
        if move:
            src,dst,amount = move
            if (src not in units or dst not in neighbors[src] or amount <= 0
                    or amount > units[src]-1):
                return None
            units[src] -= amount
            if dst in units:
                units[dst] += amount
            elif dst in cells and amount > cells[dst][2]:
                units[dst] = amount-cells[dst][2]
            else:
                return None
        balances.append(units[home]+step//2-threat[step])
    return min(balances)


def funded_mobilization(plans, home, shortage, horizon):
    """Pick one useful concrete convoy instead of mobilizing without a cap."""
    if shortage <= 0:
        return []
    options = [(plan,arrival_curve(plan,home,horizon)[-1]) for plan in plans if plan]
    funded = [(plan,force) for plan,force in options if force >= shortage]
    if funded:
        plan,_ = min(funded,key=lambda item:(len(item[0]),-item[1],item[0]))
    elif options:
        plan,_ = max(options,key=lambda item:(min(shortage,item[1])/float(len(item[0])),
                                             item[1],-len(item[0]),item[0]))
    else:
        return []
    return [plan]


def arbitrate(bot, choices, threat, horizon=5):
    """Check one action plus a concrete joint rescue, not five separate maxima."""
    threat = threat[:horizon+1]
    plans = schedules(bot.neighbors,bot.cells,bot.army,bot.home,horizon)
    by_move = {}
    for choice in sorted(choices,reverse=True)[:32]:
        move = None if choice[4] in ('bank','skirmish_wait') else tuple(choice[1:4])
        by_move.setdefault(move,choice)
    threatened = any(bot.cells[bot.home][2]+h//2 < force
                     for h,force in enumerate(threat) if h)
    proactive = bot.config.get('contact_mobilization',False)
    buffer = bot.config.get('mobilization_buffer',0)
    proposed_plans = plans if threatened or proactive else []
    target = None
    if proactive and buffer and not threatened:
        target = max(bot.home_keep,max(threat)+buffer)
        proposed_plans = funded_mobilization(plans,bot.home,
            target-bot.cells[bot.home][2],horizon)
    if proposed_plans:
        # The alternative anticipatory-contact ablation can mobilize before
        # a shortfall; the default branch checks only actual deadlines.
        for plan in proposed_plans:
            if plan:
                src,dst,amount = plan[0]
                by_move.setdefault(plan[0],(12400,src,dst,amount,'defend',bot.home))
    by_move.setdefault(None,(0,bot.home,bot.home,0,'security_wait',bot.home))
    evaluated = []
    for first,choice in by_move.items():
        from std_adjacent_threat_relief import remaining_curve
        choice_threat=remaining_curve(bot,choice,horizon,threat)
        best = None
        for plan in plans:
            # A matching first transfer consumes the current command once.
            suffix = plan[1:] if plan and plan[0] == first else plan
            if len(suffix) > horizon-1:
                continue
            slack = prefix_slack(bot.neighbors,bot.cells,bot.army,bot.home,first,suffix,choice_threat)
            if slack is not None and (best is None or slack > best):
                best = slack
        if best is not None:
            evaluated.append((best,choice))
    safe = [choice for slack,choice in evaluated if slack >= 0 or choice[4] == 'finish_king']
    if safe:
        result = safe
    elif evaluated:
        maximum = max(slack for slack,_ in evaluated)
        result = [choice for slack,choice in evaluated if slack == maximum]
    else:
        result = choices
    bot.last_report['deadline_security'] = dict(plans=len(plans), actions=len(evaluated),
        safe=len(safe), best_slack=max([s for s,_ in evaluated] or [0]),
        horizon=horizon, threat=threat,mobilization_target=target)
    return result
