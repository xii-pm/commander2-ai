"""Current funded packets on the shortest owned-distance DAG.

Equal-command alternatives may collect different current movable stocks. Each
prefix must retain a movable soldier; a later pickup cannot pay an empty road
earlier in the route. No forecast growth or unknown terrain enters this tree.
"""
from std_geometry import MARSH


def funded_shortest_tree(neighbors, cells, army, movable, source, distance, limit=17, blocked=(), signed=False):
    """Return parents and maximum packet balances at each shortest depth."""
    if movable.get(source, 0) < 1 or source in blocked:
        return {}, {}
    parent, power = {source: None}, {source: movable[source]}
    for point in sorted(distance, key=lambda p: (distance[p], p)):
        if (point == source or point in blocked or distance[point] > limit or point not in cells
                or cells[point][1] != army or cells[point][0] == MARSH):
            continue
        gain = movable.get(point, 0) if signed else -1 if cells[point][2] == 0 else movable.get(point, 0)
        candidates = [(power[p]+gain, p) for p in neighbors[point]
            if p in power and distance.get(p, -1)+1 == distance[point]
            and power[p]+gain > 0]
        if candidates:
            amount, previous = max(candidates)
            parent[point], power[point] = previous, amount
    return parent, power
