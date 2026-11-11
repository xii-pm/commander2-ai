"""Price an unfunded collection detour from a currently visible king.

The comparison uses current owned stock and exact command costs. It creates
no mission or future order and is only a heuristic for proposal eligibility;
enemy replies and income can change the outcome on the next observation.
"""
from collections import deque
from math import ceil

from std_geometry import KING


def owned_return(bot, start, finish):
    """A shortest currently owned return route, without unseen terrain."""
    parent = {start: None}
    queue = deque([start])
    while queue:
        pos = queue.popleft()
        if pos == finish:
            route = [pos]
            while parent[route[-1]] is not None:
                route.append(parent[route[-1]])
            return list(reversed(route))
        for nxt in bot.neighbors[pos]:
            if nxt not in parent and nxt in bot.cells and bot.cells[nxt][1] == bot.army:
                parent[nxt] = pos
                queue.append(nxt)
    return None


def collection_departure_allowed(bot, target, root, moves, reserves, fully_funded):
    """Keep productive moves; reject a detour that fails to improve king gap.

    A funded current objective remains an independent reason to redeploy. An
    unfunded plan moving away from a king must gain more returning surplus
    than that visible king's estimated growth during all collection and return
    commands. All intermediate garrisons are charged before later pickups.
    """
    if (not bot.config.get('king_stage_opportunity', False)
            or not bot.config.get('continuous', False)
            or not bot.config.get('king_forward_pressure', False) or not moves or fully_funded):
        return True
    source, destination, amount = moves[0]
    kings = [p for p in bot.enemies if bot.cells[p][0] == KING
             and source in bot.neighbors[p] and destination not in bot.neighbors[p]]
    if source == bot.home or not kings:
        return True
    route = owned_return(bot, root, source)
    if route is None:
        return True
    stocks = {p:bot.cells[p][2] for p in bot.owned}
    keep = {p:max(1, reserves.get(p, 1)) for p in bot.owned}
    before = stocks[source]-keep[source]
    valid = True
    for src, dst, packet in moves:
        if (src not in stocks or dst not in stocks or dst not in bot.neighbors[src]
                or packet <= 0 or packet > stocks[src]-keep[src]):
            valid = False
            break
        stocks[src] -= packet
        stocks[dst] += packet
    if valid:
        for src, dst in zip(route, route[1:]):
            packet = stocks[src]-keep[src]
            if packet <= 0:
                valid = False
                break
            stocks[src] -= packet
            stocks[dst] += packet
    commands = len(moves)+len(route)-1
    gain = stocks[source]-keep[source]-before if valid else None
    growth = int(ceil(commands*.52))
    enlarged = bool(bot.config.get('king_stage_relative_gain', False) and valid
                    and gain > 0 and gain >= before)
    allowed = valid and (gain > growth or enlarged)
    records = bot.last_report.setdefault('stage_collection_value', dict(checked=0, rejected=0, examples=[]))
    records['checked'] += 1
    records['rejected'] += int(not allowed)
    if len(records['examples']) < 24:
        records['examples'].append(dict(source=source, destination=destination, dispatch=amount,
            target=target, root=root, visible_kings=kings, current_stage_surplus=before,
            return_route=route, collection_commands=len(moves), total_commands=commands,
            current_stock_return_gain=gain, visible_king_growth=growth,
            every_prefix_funded=valid, allowed=allowed, objective_funded=False,
            materially_enlarged_packet=enlarged))
    return allowed
