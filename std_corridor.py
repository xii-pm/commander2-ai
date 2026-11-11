"""Deliver a funded column home through a short observed corridor.

Normal owned roads may be disconnected or much longer than a paid crossing.
Each callback confirms the actual previous transfer and recomputes the route.
Current road stock is an estimate, not a guarantee against enemy responses.
"""
from collections import deque
from std_geometry import KING, FORT, BLOCKED, MARSH
from std_recall_goal import target as recall_target
from std_objectives import investment_guard_active


def propose(bot, choices):
    cells, army, home = bot.cells, bot.army, bot.home
    task = getattr(bot, '_corridor_task', None)
    observed = getattr(bot, '_observed_pending', None)
    current = None
    if (task and observed and bot._last_order_confirmed
            and all(observed[k] == task[k] for k in ('src', 'dst', 'sent', 'role'))
            and task['dst'] != home and task['dst'] in bot.owned):
        current = task['dst']
    bot._corridor_task = None
    bot._corridor_options = {}
    if len(bot.owned) < 12:
        return
    goal = bot.home_keep
    limited = (getattr(bot, 'config', {}).get('corridor_recall_goal', False)
               and not investment_guard_active(bot))
    shortages = bot.last_report.get('defense_shortages', ())
    urgent = any(h <= 6 for h, _ in shortages)
    if limited and not urgent:
        goal = recall_target(bot, goal)
    deficit = goal-cells[home][2]
    threatened = getattr(bot, '_contact_seen', False) and deficit >= 8
    # A broken road is not itself a reason to recall a field army.
    # Recheck the home shortage even for a confirmed moving carrier.
    if not threatened:
        return
    _, connected = bot.owned_tree(home)
    disconnected = sum(p not in connected and cells[p][0] == FORT
                       for p in bot.owned)
    parent, distance, loss = {home:None}, {home:0}, {home:0}
    queue = deque([home])
    while queue:
        pos = queue.popleft()
        if distance[pos] >= 6:
            continue
        penalty = cells[pos][2]+1 if cells[pos][1] != army else 0
        for src in bot.neighbors[pos]:
            data = cells.get(src)
            if not data or data[0] in BLOCKED+(KING,MARSH):
                continue
            depth, cost = distance[pos]+1, loss[pos]+penalty
            if src not in distance or depth == distance[src] and cost < loss[src]:
                parent[src], distance[src], loss[src] = pos, depth, cost
                queue.append(src)
    records = []
    for src in bot.owned:
        if src == home or src not in distance or cells[src][2] < (9 if src == current else 32):
            continue
        shortcut = (threatened and connected.get(src, 999) >= distance[src]+3)
        if src != current and src in connected and not shortcut:
            continue
        route = [src]
        while route[-1] != home:
            route.append(parent[route[-1]])
        sent = min(cells[src][2]-1, bot.available(src))
        if limited and not urgent:
            road_loss = sum(cells[p][2]+1 if cells[p][1] != army else 1
                            for p in route[1:-1])
            sent = min(sent,deficit+road_loss)
        power = sent
        for pos in route[1:-1]:
            data = cells[pos]
            power += data[2]-1 if data[1] == army else -data[2]-1
            if power <= 0:
                break
        if power < 8:
            continue
        steps = len(route)-1
        due = [(h, gap) for h, gap in shortages if h >= steps]
        if urgent and due:
            h, gap = due[0]
            score = 12000+1000.0/(h+1)+min(gap,power)/float(steps)
        else:
            score = 18000+power/float(steps)
        mode = 'defend' if urgent else 'guard_supply'
        choice = (score, src, route[1], sent, mode, home)
        choices.append(choice)
        bot._corridor_options[choice[1:]]=dict(src=src,dst=route[1],sent=sent,role=mode,goal=goal)
        records.append(dict(route=route,dispatch=sent,arrival=power,continuing=src==current,
                            disconnected_producers=disconnected))
    if records:
        bot.last_report['corridor_delivery']=records


def committed(bot, src, dst, amount, mode, target):
    bot._corridor_task = getattr(bot, '_corridor_options', {}).get(
        (src, dst, amount, mode, target))
    if (bot._corridor_task and getattr(bot, 'config', {}).get('corridor_recall_goal', False)
            and dst == bot.home and mode == 'guard_supply' and bot.pending):
        bot.pending['recall_goal'] = bot._corridor_task['goal']
