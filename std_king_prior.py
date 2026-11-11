"""Approximate four-player king regions, refined by public observations.

Reflected centers are search hints, not actual spawn coordinates. A witnessed
non-king or public hill/fort outline excludes a hex, not its entire region.
"""
from itertools import combinations
from std_geometry import KING, OFFSETS, hex_distance

CORE_RADIUS = 3
OUTER_RADIUS = 5


class KingPrior:
    def __init__(self, army, rows, cols):
        self.army, self.rows, self.cols = army, rows, cols
        self.home = None
        self.slots = set()
        self.confirmed = {}
        self.resolved = set()
        self.rejected = None
        self.calls = 0
        self.excluded = False
        self.radius = CORE_RADIUS
        self.expanded_at = None
        self.ruled_out = set()
        self.assignments = []
        self._region_cache = {}
        self._focus_slot = None
        self._focus_pos = None

    def reject(self, reason, pos=None):
        if self.rejected is None:
            self.rejected = dict(reason=reason, position=pos, observation=self.calls)

    def regions(self):
        if self.radius not in self._region_cache:
            self._region_cache[self.radius] = {
                center: {p for p in ((r,c) for r in range(self.rows) for c in range(self.cols))
                         if p != self.home and hex_distance(center,p) <= self.radius}
                for center in self.slots}
        return self._region_cache[self.radius]

    @staticmethod
    def distinct_unseen_possible(domains):
        # Hall's condition is exact for at most three remaining king regions.
        for count in range(1,len(domains)+1):
            for subset in combinations(domains,count):
                if len(set().union(*subset)) < count:
                    return False
        return True

    def compatible_assignments(self):
        regions = self.regions()
        centers = sorted(regions)
        witnessed = sorted(self.confirmed)
        unseen = {center: region-self.ruled_out-set(witnessed)
                  for center,region in regions.items()}
        feasible = []

        def visit(index,used):
            if index == len(witnessed):
                missing = [unseen[c] for c in centers if c not in used]
                if self.distinct_unseen_possible(missing):
                    feasible.append(frozenset(used))
                return
            pos = witnessed[index]
            for center in centers:
                if center not in used and pos in regions[center]:
                    visit(index+1,used|{center})

        if len(witnessed) <= 3:
            visit(0,set())
        return sorted(set(feasible),key=lambda s:tuple(sorted(s)))

    def observe(self, cells, hints=(), map314=False):
        self.calls += 1
        self.excluded = bool(map314)
        if map314 or self.rejected:
            return
        if self.home is None:
            own = [p for p,d in cells.items() if d[0] == KING and d[1] == self.army]
            if len(own) != 1:
                return
            self.home = own[0]
            r,c = self.home
            self.slots = {(r,self.cols-1-c),(self.rows-1-r,c),
                          (self.rows-1-r,self.cols-1-c)}-{self.home}
            if len(self.slots) != 3:
                self.reject('degenerate_four_region_reflection')
                return
        owners = {d[1] for d in cells.values() if d[0] and d[1] > 0}
        if len(owners|{self.army}) > 4:
            self.reject('more_than_four_observed_owners')
            return
        for pos,data in cells.items():
            kind,owner,_ = data
            if kind == 0 or owner < 0:
                continue
            if kind == KING and owner > 0 and owner != self.army:
                self.confirmed[pos] = owner
                self.ruled_out.discard(pos)
            elif kind != KING:
                self.ruled_out.add(pos)
        for pos in hints:
            pos = tuple(pos)
            if (pos not in cells or cells[pos][0] == 0 or cells[pos][1] < 0):
                self.ruled_out.add(pos)
        self.assignments = self.compatible_assignments()
        if not self.assignments and self.radius < OUTER_RADIUS:
            self.radius = OUTER_RADIUS
            self.expanded_at = self.calls
            self.assignments = self.compatible_assignments()
        if not self.assignments:
            self.reject('approximate_regions_exhausted_or_incompatible_with_witnessed_kings')
            return
        self.resolved = set.intersection(*(set(s) for s in self.assignments))

    def candidates(self):
        if not self.assignments:
            return {}
        # A region with an ambiguous witnessed king remains a possible missing
        # region. Known kings still outrank this prior in focus().
        return {center:region-self.ruled_out-set(self.confirmed)
                for center,region in self.regions().items()
                if any(center not in used for used in self.assignments)}

    def focus(self, bot):
        if self.excluded or self.rejected or self.home is None or bot.kings:
            return None
        candidates = self.candidates()
        if not candidates:
            return None
        owned = bot.owned or [self.home]
        best_uncertainty = min(any(center in used for used in self.assignments)
                               for center in candidates)
        if (self._focus_slot in candidates
                and self._focus_pos in candidates[self._focus_slot]
                and any(self._focus_slot in used for used in self.assignments) == best_uncertainty):
            return self._focus_pos
        options = []
        for center,region in candidates.items():
            if not region:
                continue
            # Prefer a definitely missing region over one that may already
            # contain a witnessed king; no calibrated probability is implied.
            uncertain = any(center in used for used in self.assignments)
            for pos in region:
                near = min(hex_distance(p,pos) for p in owned)
                neighborhood = {pos}|{(pos[0]+dr,pos[1]+dc) for dr,dc in OFFSETS[pos[0]&1]}
                coverage = len(neighborhood & region)
                cost = near+.35*hex_distance(center,pos)-.15*coverage
                options.append((uncertain,cost,hex_distance(center,pos),center,pos))
        if not options:
            return None
        _,_,_,self._focus_slot,self._focus_pos = min(options)
        return self._focus_pos

    def report(self):
        status = ('excluded_314' if self.excluded else 'rejected' if self.rejected
                  else 'waiting_for_own_king' if self.home is None
                  else 'complete' if len(self.confirmed) == 3 else 'active')
        regions = self.regions() if self.home is not None and not self.excluded else {}
        return dict(status=status, assumed_players=4,
            hypothesis='approximate_reflected_regions',radius=self.radius,
            core_radius=CORE_RADIUS,outer_radius=OUTER_RADIUS,expanded_at=self.expanded_at,
            slots=sorted(self.slots),confirmed=sorted(self.confirmed),resolved=sorted(self.resolved),
            regions=[dict(center=c,possible_unseen=len(r-self.ruled_out-set(self.confirmed)),
                          witnessed=[p for p in sorted(self.confirmed) if p in r])
                     for c,r in sorted(regions.items())],
            compatible_region_assignments=len(self.assignments),rejection=self.rejected,
            source='own king, dimensions and public exclusions; no hidden board',
            injected_hidden_cells=0)
