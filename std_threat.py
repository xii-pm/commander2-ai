"""Shared-road projection of visible hostile stacks on one shortest-path tree.

It ignores resistance and allows producer growth, but fixes one route per cell.
Thus it supplements the independent-route model; it is not an all-path or fog
guarantee. No map truth, opponent code, or unobserved armies are consumed.
"""
from std_geometry import KING, FORT


def shared_curve(neighbors, cells, home, army, distance, horizon=12, exclude=()):
    nodes = [p for p in distance if distance[p] <= horizon]
    children = {p: [] for p in nodes}
    for p in nodes:
        if p != home:
            parents = [n for n in neighbors[p] if distance.get(n) == distance[p]-1]
            children[min(parents)].append(p)
    result = [0]
    for deadline in range(1,horizon+1):
        tables = {}
        for p in sorted((p for p in nodes if distance[p] <= deadline),
                        key=lambda p: (-distance[p],p)):
            kind,owner,units = cells.get(p,(0,0,0))
            enemy = owner > 0 and owner != army and p not in exclude
            base = units-1 if enemy else -1
            if enemy and kind in (KING,FORT):
                base += (deadline+1)//2
            table = {0: 0 if p == home else base}
            for child in sorted(children[p]):
                if child not in tables:
                    continue
                updated = dict(table)
                for used,force in table.items():
                    for spent,payload in tables[child].items():
                        commands = used+spent+1
                        if commands <= deadline and payload > 0:
                            updated[commands] = max(updated.get(commands,-1),force+payload)
                table = updated
            tables[p] = table
        result.append(max(tables[home].values()))
    return result
