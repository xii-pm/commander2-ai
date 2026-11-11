"""Shared-order tree DP adapted from YRFZ's reinforcement schedule principle.

No future growth is credited. A branch must merge before its shared edge is
forwarded. Only the first order is executed, and the next observation replans.
"""
from collections import deque


def tree_supply(bot, target, horizon=6, exclude=(), max_distance=None):
    if target not in bot.owned:
        return None
    blocked = set(exclude) | (bot.protected() - {target})
    radius = min(horizon, max_distance) if max_distance is not None else horizon
    distance, parent, queue = {target: 0}, {target: None}, deque([target])
    while queue:
        p = queue.popleft()
        if distance[p] >= radius:
            continue
        for n in bot.neighbors[p]:
            if n in bot.owned and n not in distance:
                distance[n], parent[n] = distance[p] + 1, p
                queue.append(n)
    children = {p: [] for p in distance}
    for p in distance:
        if p != target:
            children[parent[p]].append(p)
    tables = {}
    for p in sorted(distance, key=lambda n: (-distance[n], n)):
        reserve = max(bot.cells[p][2] - bot.available(p), bot.counter(p) + 1)
        if p in blocked:
            reserve = max(reserve, bot.cells[p][2])
        base = bot.cells[p][2] - reserve if p != target else 0
        table = {0: (base, ())}
        for child in sorted(children[p]):
            combined = dict(table)
            for used, (force, moves) in table.items():
                for cost, (delivered, child_moves) in tables[child].items():
                    commands = used + cost + 1
                    if commands > horizon or delivered <= 0:
                        continue
                    proposal = force + delivered, moves + child_moves + ((child, p, delivered),)
                    if commands not in combined or proposal[0] > combined[commands][0]:
                        combined[commands] = proposal
            table = combined
        tables[p] = table
    options = [(force / float(cost), force, -cost, moves)
               for cost, (force, moves) in tables[target].items() if cost and force > 0]
    return max(options)[-1] if options else None
