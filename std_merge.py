"""Pure shared-command collection; child branches merge before forwarding."""
from collections import deque


def merge_schedule(neighbors, cells, army, root, reserves, budget=6):
    distance, parent = {root: 0}, {root: None}
    queue = deque([root])
    while queue:
        p = queue.popleft()
        if distance[p] >= budget:
            continue
        for n in neighbors[p]:
            if n not in distance and n in cells and cells[n][1] == army:
                distance[n], parent[n] = distance[p]+1, p
                queue.append(n)
    children = {p: [] for p in distance}
    for p in distance:
        if p != root:
            children[parent[p]].append(p)
    tables = {}
    for p in sorted(distance, key=lambda n: (-distance[n], n)):
        base = cells[p][2] - reserves.get(p, 1) if p != root else 0
        table = {0: (base, ())}
        for child in sorted(children[p]):
            new = dict(table)
            for used, (power, moves) in table.items():
                for cost, (payload, sequence) in tables[child].items():
                    commands = used+cost+1
                    if commands > budget or payload <= 0:
                        continue
                    candidate = power+payload, moves+sequence+((child, p, payload),)
                    if commands not in new or candidate[0] > new[commands][0]:
                        new[commands] = candidate
            table = new
        tables[p] = table
    return [(force, cost, moves) for cost, (force, moves) in tables[root].items()
            if cost and force > 0]
