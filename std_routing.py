"""Routing methods preserved from the frozen BFS hunter."""
from collections import deque
from std_geometry import KING, MARSH, BLOCKED


class Routing:
    def bfs(self, start, allowed, limit=None):
        distance, queue = {start: 0}, deque([start])
        while queue:
            p = queue.popleft()
            if limit is not None and distance[p] >= limit:
                continue
            for n in self.neighbors[p]:
                if n not in distance and allowed(n):
                    distance[n] = distance[p] + 1
                    queue.append(n)
        return distance

    @staticmethod
    def path(parent, target):
        if target not in parent:
            return None
        route = []
        while target is not None:
            route.append(target)
            target = parent[target]
        return list(reversed(route))

    def routes(self, start, owned_only=False, ceiling=None, forbidden=()):
        """BFS shortest commands; ties prefer lower observed attrition.

        A second, strength-filtered BFS can find a longer bypass. Neither graph
        treats never-observed BLANK or HILL silhouettes as traversable terrain.
        """
        forbidden = frozenset(forbidden or ())
        key = (start, owned_only, ceiling, forbidden)
        if key in self.path_cache:
            return self.path_cache[key]
        parent, distance, loss = {start: None}, {start: 0}, {start: 0}
        frontier = [start]
        while frontier:
            nxt_level = []
            for p in frontier:
                if distance[p] >= self.MAX_ROUTE:
                    continue
                for n in self.neighbors[p]:
                    if n in forbidden:
                        continue
                    data = self.estimate_cell(n)
                    if data is None or data[0] in BLOCKED:
                        continue
                    kind, owner, units = data
                    if owned_only and (n not in self.cells or owner != self.army):
                        continue
                    if ceiling is not None and owner != self.army and units > ceiling:
                        continue
                    cost = (units + 1 if owner != self.army else
                            max(0, self.fort_reserves.get(n, 1) - units))
                    cost += 2 if kind == MARSH else 0
                    depth, spent = distance[p] + 1, loss[p] + cost
                    if n not in distance:
                        distance[n], parent[n], loss[n] = depth, p, spent
                        nxt_level.append(n)
                    elif distance[n] == depth and spent < loss[n]:
                        parent[n], loss[n] = p, spent
            frontier = nxt_level
        result = parent, distance
        self.path_cache[key] = result
        return result

    def route_plan(self, src, target, ceiling=None, forbidden=()):
        parent, _ = self.routes(src, ceiling=ceiling, forbidden=forbidden)
        route = self.path(parent, target)
        if not route or len(route) < 2:
            return None
        loss = 0
        for i, p in enumerate(route[1:], 1):
            kind, owner, units = self.estimate_cell(p, i)
            if kind == KING and owner in self.kings:
                prediction = self.predict_king(owner, i + 1, excluded=route[1:-1])
                if prediction['age'] + i + 1 > self.KING_MAX_AGE:
                    return None
                units = prediction['upper']
            loss += units + 1 if owner != self.army else max(0, self.fort_reserves.get(p, 1) - units)
            if kind == MARSH:
                loss += 2
        flank = max((self.counter(p, excluded=route[1:]) for p in route[1:4]), default=0)
        # King upper already includes its visible reinforcements; don't add again.
        target_data = self.estimate_cell(target)
        if target_data[0] == KING and target_data[1] in self.kings:
            flank = 0
        return dict(route=route, steps=len(route) - 1, loss=loss, flank=flank,
                    needed=loss + flank + 3)

    def best_plan(self, src, target, forbidden=()):
        # Normal shortest route and a weaker-defender bypass, both genuine BFS.
        plans = [self.route_plan(src, target, forbidden=forbidden),
                 self.route_plan(src, target, ceiling=max(2, self.available(src) // 3),
                                 forbidden=forbidden)]
        plans = [p for p in plans if p]
        if not plans:
            return None
        power = max(1, self.available(src))
        return min(plans, key=lambda p: p['steps'] +
                   self.ROUTE_LOSS_WEIGHT * p['loss'] / float(power) +
                   self.ROUTE_FLANK_WEIGHT * p['flank'] / float(power))
