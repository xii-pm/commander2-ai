"""Per-observation indexed graph for the unchanged signed pickup recurrence."""
from collections import deque


def pickup_paths(planner, start, allowed, spare):
    """Keep shortest depths, signed prefix tests and lexicographic ties exact."""
    key = ('indexed_pickup_graph',)
    graph = planner.path_cache.get(key)
    if graph is None or graph[0] is not allowed or graph[1] is not spare:
        # Ownership and protected roads often remain unchanged over multiple
        # observations. Only topology may persist: troop balances and paths
        # are always rebuilt from this observation's signed reserve ledger.
        topology = getattr(planner.bot, '_pickup_topology', None)
        signature = frozenset(allowed)
        if (topology is None or topology[0] != signature
                or topology[1] is not planner.neighbors):
            points = tuple(allowed)
            index = {point: i for i, point in enumerate(points)}
            adjacency = tuple(tuple(index[n] for n in planner.neighbors[point] if n in index)
                              for point in points)
            topology = signature, planner.neighbors, points, index, adjacency, {}
            planner.bot._pickup_topology = topology
        _, _, points, index, adjacency, trees = topology
        balances = tuple(spare[point] for point in points)
        graph = allowed, spare, points, index, adjacency, balances, trees
        planner.path_cache[key] = graph
    _, _, points, index, adjacency, balances, trees = graph
    if start not in index:
        # The public legacy method can start outside allowed. Keep its exact
        # implementation for that case; real field sources are always allowed.
        return None
    root = index[start]
    tree = trees.get(root)
    if tree is None:
        distance = [-1]*len(points)
        distance[root] = 0
        levels, queue = [[root]], deque([root])
        while queue:
            point = queue.popleft()
            depth = distance[point]+1
            if depth > 11:
                continue
            for nxt in adjacency[point]:
                if distance[nxt] >= 0:
                    continue
                distance[nxt] = depth
                if len(levels) <= depth:
                    levels.append([])
                levels[depth].append(nxt)
                queue.append(nxt)
        incoming = tuple(tuple(n for n in adjacency[p] if distance[n] == distance[p]-1)
                         for p in range(len(points)))
        tree = levels, incoming
        trees[root] = tree
    levels, incoming = tree
    paths, gains = [None]*len(points), [0]*len(points)
    paths[root] = (start,)
    departure = balances[root]
    result = {start: (start,)}
    powers = {start: (departure, departure)}
    for level in levels[1:]:
        for point in level:
            balance = balances[point]
            # Compare signed pickup against one prefix threshold per point.
            # Keep the chosen path/gain together to avoid repeated lookups.
            threshold = -departure-balance
            best_path = None
            best_gain = 0
            for prior in incoming[point]:
                prior_path = paths[prior]
                gain = gains[prior]
                if prior_path is None or gain <= threshold:
                    continue
                if (best_path is None or gain > best_gain
                        or gain == best_gain and prior_path > best_path):
                    best_path, best_gain = prior_path, gain
            if best_path is not None:
                pos = points[point]
                path = best_path+(pos,)
                gain = best_gain+balance
                paths[point], gains[point] = path, gain
                result[pos] = path
                powers[pos] = departure, departure+gain
    planner.path_cache[('pickup_paths', start)] = result
    planner.path_cache[('pickup_power', start)] = powers
    return result
