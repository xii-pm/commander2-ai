"""Defense methods preserved from the frozen BFS hunter."""
import math
from std_geometry import KING, FORT


class Defense:
    def reserve_home(self, horizon, exclude_owner=None):
        threats = {}
        for p in self.enemies:
            kind, owner, units = self.cells[p]
            dist = self.risk_dist.get(p, 999)
            if owner != exclude_owner and dist <= horizon:
                growth = int(math.ceil(max(0, horizon - dist) * 0.52)) if kind in (KING, FORT) else 0
                force = max(0, units - dist) + growth
                threats.setdefault(owner, []).append((max(1, dist), force))
        for p, (kind, owner, units, seen) in self.memory.items():
            age = self.tick - seen
            if (p in self.cells or owner <= 0 or owner in (self.army, exclude_owner)
                    or owner in self.eliminated or age > 8 or units < 4):
                continue
            remaining = max(0, self.risk_dist.get(p, 999) - age)
            if remaining <= horizon:
                # A remembered stack competes for the same per-owner command budget.
                threats.setdefault(owner, []).append((max(1, remaining), max(0, units - remaining)))
        command_budget = max(1, int(horizon))
        by_owner = {}
        for owner, arrivals in threats.items():
            # Each opponent may issue one command per update. Pick the maximum
            # force it can route within this many commands instead of summing
            # mutually exclusive stacks that cannot all reach the King in time.
            best = [0] * (command_budget + 1)
            for distance, force in arrivals:
                cost = max(1, int(distance))
                if cost > command_budget:
                    continue
                for budget in range(command_budget, cost - 1, -1):
                    best[budget] = max(best[budget], best[budget - cost] + force)
            by_owner[owner] = max(best)
        self.last_home_reserve_by_owner = dict(by_owner)
        return max(1 if len(self.owned) < 10 else 2,
                   sum(by_owner.values()) + (2 if by_owner else 0))

    def home_contact_floor(self, force):
        floor = max(self.HOME_CONTACT_GARRISON_MIN, force + 2)
        if force >= self.HOME_CONTACT_GARRISON_TRIGGER:
            floor = max(floor, self.HOME_CONTACT_GARRISON_BASELINE)
        return min(self.HOME_CONTACT_GARRISON_MAX, floor)

    def home_guard_hold(self):
        return min(self.HOME_CONTACT_GARRISON_MAX,
                   sum(self.home_guard_hold_by_owner.values()))

    def nearest_home_threat_eta(self, horizon=4):
        arrivals = []
        for p in self.enemies:
            eta = self.risk_dist.get(p, 999)
            if eta <= horizon:
                arrivals.append(eta)
        for p, (kind, owner, units, seen) in self.memory.items():
            age = self.tick - seen
            if (p in self.cells or owner <= 0 or owner == self.army or
                    owner in self.eliminated or age > 8 or units < 4):
                continue
            eta = max(0, self.risk_dist.get(p, 999) - age)
            if eta <= horizon:
                arrivals.append(eta)
        return min(arrivals) if arrivals else horizon

    def timely_home_support(self, shortage, eta, ignore_reserves=False):
        """Select only the convoy payload that can fit in the remaining turns."""
        distance = self.bfs(self.home, lambda p: p in self.cells and self.cells[p][1] == self.army)
        donors = sorted((distance[p],
                         -(self.cells[p][2] - 1 if ignore_reserves
                           else self.available(p)), p)
                        for p in self.owned
                        if p != self.home and p in distance and distance[p] <= eta
                        and ((self.cells[p][2] > 1) if ignore_reserves
                             else self.available(p) > 0))
        selected, delivered, commands = [], 0, 0
        for steps, negative, src in donors:
            cost = max(1, steps)
            if commands + cost > eta:
                continue
            selected.append(src)
            delivered += -negative
            commands += cost
            if delivered >= shortage:
                break
        return selected, delivered, commands

    def defend(self):
        horizon = self.HOME_DEFENSE_HORIZON
        need = max(self.reserve_home(horizon), self.home_guard_hold())
        if self.cells[self.home][2] < need:
            eta = max(1, self.nearest_home_threat_eta(horizon))
            support_horizon = eta
            if need >= self.HOME_DEFENSE_DEEP_RECALL_THRESHOLD:
                support_horizon = max(support_horizon,
                                      self.HOME_DEFENSE_REINFORCE_HORIZON)
            home_deficit = need - self.cells[self.home][2]
            last_stand = (eta <= 1 and
                          home_deficit <= self.HOME_DEFENSE_LAST_STAND_MAX_DEFICIT)
            shortage = home_deficit + 2
            selected, delivered, commands = self.timely_home_support(
                shortage, support_horizon, ignore_reserves=last_stand)
            self.last_report.update(defense_eta=eta,
                                    defense_support_horizon=support_horizon,
                                    defense_support=delivered,
                                    defense_commands=commands, defense_required=need,
                                    defense_last_stand=last_stand)
            if selected:
                excluded = set(self.owned) - set(selected)
                move = self.gather(self.home, 'recall support within aggregate command budget',
                                   'defend', shortage, exclude=excluded,
                                   max_distance=support_horizon)
                if move:
                    return move
        choices = []
        for dst in self.enemies:
            if self.risk_dist.get(dst, 999) > 3:
                continue
            for src in self.neighbors[dst]:
                count = self.available(src)
                if count > self.cells[dst][2] + self.counter(dst, excluded=(dst,)):
                    choices.append((self.cells[dst][2], src, dst, count))
        for _, src, dst, count in sorted(choices, reverse=True):
            move = self.action(src, dst, count, 'defend', 'intercept near-home threat')
            if move:
                return move
        return None
