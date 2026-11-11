"""314 three-player policy. Static geometry is public map knowledge.

Owners, units and events are learned exclusively from the supplied observation.
Opening commands advance on visible confirmation, never callback modulo 50.
One explicit adjacent order per observation; shared after inheritance.
"""
from collections import deque
import heapq
import os
import random
from std_geometry import BLANK, KING, FORT, BLOCKED, OFFSETS
from std_map314_profile import TERRAIN, SPAWNS

IMPLEMENTATION = '314-rush-v3'
DIVIDER_FORTS = frozenset(((6,4),(6,19),(9,8),(9,14),(11,11),(15,11),(21,11)))
EARLY_FORT_UNTIL = 300
MAX_FORT_DISCOUNT = .2


def border_fort_discount(elapsed):
    """Ramp the penalty up before step 300, then restore the full weight."""
    if elapsed >= EARLY_FORT_UNTIL:
        return 0.0
    return MAX_FORT_DISCOUNT * max(0.0, float(elapsed)) / EARLY_FORT_UNTIL


def border_fort_factor(cells, neighbors, army, target, elapsed):
    """Discount only public-map divider forts in the opening window."""
    data = cells.get(target)
    if (target not in DIVIDER_FORTS
            or not data or data[0]!=FORT or data[1]!=0):
        return 1.0
    return 1.0-border_fort_discount(elapsed)


def weight_border_forts(bot, choices):
    """314-only soft preference; preserve emergencies and capital captures."""
    result,changed = [],0
    for score,src,dst,amount,mode,target in choices:
        factor = border_fort_factor(bot.cells,bot.neighbors,bot.army,target,bot.tick)
        if factor<1 and mode not in ('defend','intercept','finish_king','guard') and score<1000000:
            score -= abs(score)*(1-factor)
            changed += 1
        result.append((score,src,dst,amount,mode,target))
    if changed:
        bot.last_report['map314_border_forts'] = dict(discount=border_fort_discount(bot.tick),proposals=changed,until=EARLY_FORT_UNTIL,ramp='increasing')
    return result


def rotate(p, turns):
    r, c = p
    q, r = c - (r - (r & 1)) // 2 - 6, r - 11
    for _ in range(turns):
        q, r = -q-r, q
    r += 11
    return r, q + 6 + (r - (r & 1)) // 2


class Controller:
    def __init__(self, bot):
        self.army = bot.army
        self.home = bot.home
        self.turns = next(i for i in range(3) if rotate((15, 5), i) == self.home)
        self.local_keys = {p:rotate(p,(1-self.turns)%3) for p in bot.neighbors}
        fixed_seed = os.environ.get('COMMANDER_MAP314_SEED')
        self.seed = int(fixed_seed)+self.army*104729 if fixed_seed is not None else random.SystemRandom().randrange(2**32)
        rng = random.Random(self.seed)
        self.target_bias = {p:rng.uniform(-8,8) for p in sorted(SPAWNS,key=self.key) if p != self.home}
        self.graph = {p: tuple(n for n in bot.neighbors[p]
                              if int(TERRAIN[n[0]][n[1]]) not in BLOCKED)
                      for p in bot.neighbors if int(TERRAIN[p[0]][p[1]]) not in BLOCKED}
        self.graph = {p:tuple(sorted(ns,key=self.key)) for p,ns in self.graph.items()}
        self.fields = {}
        self.previous = {}
        self.pending = None
        self.index = 0
        self.started = False
        self.opening_done = False
        self.pulse = False
        self.elapsed = 0
        self.pulse_age = None
        self.growth_next = None
        self.target = None
        self.commit = []
        self.harvest = False
        self.directed = False
        self.home_keep = 1
        self.history = {}
        self.pressure_checked = -999
        self.capital_entry = None
        self.assault_target = None
        self.assault_stage = None
        self.assault_phase = None
        self.assault_deadline = 0
        self.assault_probe_count = 0
        self.assault_retry = {}
        self.opening = self.make_opening()

    def make_opening(self):
        stem = [(15,5),(14,6),(13,6),(12,7),(11,7),(11,8),(11,9),(11,10)]
        commands = [(a,b,10 if i == 0 else 0) for i,(a,b) in enumerate(zip(stem,stem[1:]))]
        commands += [((11,10),(12,11),2), ((11,10),(10,11),1), ((12,11),(12,12),1)]
        commands += [(a,b,5 if i == 0 else 0) for i,(a,b) in enumerate(zip(stem,stem[1:]))]
        commands += [((11,10),(10,11),2), ((10,11),(9,10),0), ((9,10),(8,11),0),
                     ((11,10),(12,11),0), ((12,11),(12,12),0),
                     ((12,12),(13,12),0), ((13,12),(13,13),0), ((13,13),(14,14),0),
                     ((15,5),(14,5),1)]
        return [(rotate(a,self.turns),rotate(b,self.turns),n) for a,b,n in commands]

    def key(self, p):
        """Resolve equal choices in the same frame for all physical spawns."""
        return self.local_keys[p]

    def distances(self, p):
        if p not in self.fields:
            d = {p:0}
            queue = deque([p])
            while queue:
                x = queue.popleft()
                for y in self.graph.get(x,()):
                    if y not in d:
                        d[y] = d[x]+1
                        queue.append(y)
            self.fields[p] = d
        return self.fields[p]

    def observe(self, cells, previous=None, touched=()):
        self.cells = cells
        self.owned = {p for p,d in cells.items() if d[1] == self.army}
        self.enemies = {p for p,d in cells.items() if d[1] > 0 and d[1] != self.army}
        changed = cells != self.previous
        if changed:
            self.elapsed += 1
            if self.pulse_age is not None:
                self.pulse_age += 1
        touched = set(touched) | (set(self.pending[:2]) if self.pending else set())
        prior_growth = self.previous if previous is None else previous
        self.calibrate_growth(prior_growth,cells,touched,carry=prior_growth==self.previous)
        witnesses = [p for p,d in cells.items() if d[0] == BLANK and d[1] == self.army
                     and p not in touched and p in self.previous
                     and self.previous[p][1] == self.army and d[2]-self.previous[p][2] == 1]
        if len(witnesses) >= 3:
            self.pulse, self.pulse_age = True, 0
            self.growth_next = False
            self.elapsed = max(self.elapsed,50)
        # Before enemy contact, total soldiers is a witnessed producer clock.
        if not self.pulse and not self.enemies and not self.opening_done:
            self.elapsed = max(self.elapsed,2*sum(cells[p][2] for p in self.owned))
        for p,d in cells.items():
            self.history[p] = (d,self.elapsed)
        confirmed = False
        if self.pending:
            src,dst,sent,before_src,before_dst,opening = self.pending
            old = before_src[2]
            now = cells.get(src)
            moved = now is not None and (now[1] != self.army or now[2] < old)
            arrived = cells.get(dst) != before_dst
            if moved or arrived:
                confirmed = True
                if opening:
                    self.index += 1
                self.pending = None
            elif not changed:
                self.previous = dict(cells)
                return False
            else:
                # A source can grow while its move is in transit. Do not issue a
                # second command against an unconfirmed source/destination.
                self.previous = dict(cells)
                return False
        self.previous = dict(cells)
        return True

    def calibrate_growth(self, previous, cells, touched=(), carry=False):
        """Use untouched public producers; a gap cannot supply a parity clock."""
        gains = set()
        if cells != previous:
            for p,d in cells.items():
                old = previous.get(p)
                if (p in touched or not old or d[0] not in (KING,FORT)
                        or old[:2]!=d[:2] or d[1]!=self.army):
                    continue
                if any(cells.get(n,(0,0,0))[1] not in (0,self.army)
                       or previous.get(n,(0,0,0))[1] not in (0,self.army)
                       for n in self.graph[p]):
                    continue
                gains.add(d[2]-old[2])
        old_phase = self.growth_next
        if len(gains)==1 and gains<={0,1}:
            self.growth_next = next(iter(gains))==0
        elif carry and not gains and cells!=previous and old_phase is not None:
            self.growth_next = not old_phase
        else:
            self.growth_next = None

    def data(self, p):
        if p in self.cells:
            return self.cells[p]
        kind = int(TERRAIN[p[0]][p[1]])
        if p in self.history:
            d,t = self.history[p]
            if d[1] == self.army:
                return kind,-1,0
            return kind,d[1],d[2]+((self.elapsed-t+1)//2 if kind in (KING,FORT) and d[1]>0 else 0)
        return kind,-1,(max(3,self.elapsed//2-14) if kind == KING else 30 if kind == FORT else 0)

    def path(self, start, goal, friendly=False):
        todo = [(0,self.key(start),start)]
        cost,parent = {start:0},{start:None}
        while todo:
            value,_,p = heapq.heappop(todo)
            if value != cost[p]:
                continue
            if p == goal:
                result = [p]
                while parent[result[-1]] is not None:
                    result.append(parent[result[-1]])
                return result[::-1]
            for n in self.graph.get(p,()):
                if friendly and n not in self.owned:
                    continue
                if n in SPAWNS and n not in (start,goal,self.home) and n not in self.owned:
                    continue
                d = self.data(n)
                weight = 1 + (0 if d[1] == self.army else d[2]*0.16)
                new = value+weight
                if new < cost.get(n,1e9):
                    cost[n],parent[n] = new,p
                    heapq.heappush(todo,(new,self.key(n),n))
        return None

    def order(self, src, dst, amount, mode, opening=False):
        d = self.cells.get(src)
        if d is None or d[1] != self.army or dst not in self.graph.get(src,()):
            return None
        # The live SDK needs a visible destination. Own neighbours are visible.
        if dst not in self.cells:
            return None
        sent = min(int(amount),d[2]-(self.home_keep if src == self.home else 1))
        if sent <= 0:
            return None
        self.pending = (src,dst,sent,d,self.cells.get(dst),opening)
        self.report.update(mode=mode, src=src,dst=dst,sent=sent)
        return src,dst,sent

    def incoming(self, home, horizon=8):
        field = self.distances(home)
        rows = []
        for p in self.enemies:
            d = self.cells[p]
            distance = field.get(p,999)
            if distance <= horizon:
                # Bound one advancing packet; do not invent cooperation.
                force = d[2]-distance
                if force > 0:
                    rows.append((distance,force,p,d[1]))
        return sorted(rows,key=lambda x:(x[0],x[1],self.key(x[2]),x[3]))

    def collection(self, root, radius):
        parent,depth = {root:None},{root:0}
        queue = deque([root])
        while queue:
            p = queue.popleft()
            if depth[p] >= radius:
                continue
            for n in self.graph.get(p,()):
                if n in self.owned and n not in parent:
                    parent[n],depth[n] = p,depth[p]+1
                    queue.append(n)
        needed = {root}
        for p in parent:
            if self.cells[p][2] > 1:
                q = p
                while q is not None and q not in needed:
                    needed.add(q)
                    q = parent[q]
        return [(p,parent[p]) for p in sorted(needed,key=lambda x:(-depth[x],self.key(x))) if p != root]

    def forecast(self, edges, route):
        positions = set(route)
        for a,b in edges:
            positions.update((a,b))
        local = {p:list(self.data(p)) for p in positions}
        moves = []
        for t,(src,dst) in enumerate(edges+list(zip(route,route[1:])),1):
            # Producer growth upper estimate for opponents, lower for ours.
            for p,d in local.items():
                phase = (((t%2==1)==self.growth_next) if self.growth_next is not None
                         else t%2 == (0 if d[1] == self.army else 1))
                if (d[0] in (KING,FORT) and (d[1]>0 or (d[1]<0 and p in SPAWNS)) and phase):
                    d[2] += 1
            s,d = local[src],local[dst]
            if s[1] != self.army or s[2] <= 1:
                return None
            keep = self.home_keep if src == self.home else 1
            sent = s[2]-keep
            if sent <= 0:
                return None
            moves.append((src,dst,sent))
            s[2] = keep
            if d[1] == self.army:
                d[2] += sent
            elif sent > d[2]:
                d[1],d[2] = self.army,sent-d[2]
            else:
                if dst == route[-1]:
                    return dict(moves=moves,margin=sent-d[2]-1,steps=t)
                return None
        return dict(moves=moves,margin=local[route[-1]][2]-1,steps=len(moves))

    def packet_collections(self, root, budget=20):
        """Offer sparse donor trees, charging each shared edge only once.

        A mature empire's radius tree includes scores of low-value commands.
        Keep up to four useful prefixes ordered by marginal soldiers per order.
        Routing and donations use current owned cells only.
        """
        parent,depth = {root:None},{root:0}
        queue = deque([root])
        while queue:
            p = queue.popleft()
            if depth[p] >= budget:
                continue
            for n in self.graph.get(p,()):
                if n in self.owned and n not in parent:
                    parent[n],depth[n] = p,depth[p]+1
                    queue.append(n)
        needed = {root}
        donors = sorted((p for p in parent if p != root and self.cells[p][2]>1),
                        key=lambda p:(-self.cells[p][2],self.key(p)))[:12]
        result = []
        for _ in range(4):
            best = None
            for donor in donors:
                branch = []
                p = donor
                while p not in needed:
                    branch.append(p)
                    p = parent[p]
                if not branch or len(needed)-1+len(branch)>budget:
                    continue
                gain = sum(max(0,self.cells[p][2]-(self.home_keep if p==self.home else 1)) for p in branch)
                if gain <= len(branch):
                    continue
                key = (gain/float(len(branch)),gain,-len(branch),self.key(donor))
                if best is None or key>best[0]:
                    best = key,branch
            if best is None:
                break
            needed.update(best[1])
            result.append([(p,parent[p]) for p in sorted(needed,key=lambda p:(-depth[p],self.key(p))) if p!=root])
        return result

    def harvest_action(self):
        choices = []
        field = self.distances(self.home)
        for src in sorted(self.owned,key=self.key):
            n = self.cells[src][2]-1
            if n <= 0:
                continue
            for dst in self.graph[src]:
                if dst not in self.cells or self.cells[dst][:2] != (BLANK,0):
                    continue
                # Compact local leaves need fewer post-refresh collection moves.
                value = -field.get(dst,999)*3+sum(x in self.owned for x in self.graph[dst])
                choices.append((value,src,dst,n))
        if choices:
            _,src,dst,n = max(choices,key=lambda x:(x[0],self.key(x[1]),self.key(x[2])))
            # Keep surplus on the branch tip if the producer's adjacent fan is full.
            sent = n if any(self.data(p)[:2] == (BLANK,-1) or
                            self.cells.get(p,(0,0,0))[:2] == (BLANK,0)
                            for p in self.graph[dst] if p not in self.owned) else 1
            return self.order(src,dst,sent,'opening_compact_harvest')
        # A one-unit fan can strand new producer growth. Feed a nearby branch
        # with unclaimed space instead of idling through the first refresh.
        supply = []
        for src in sorted(self.owned,key=self.key):
            n = self.cells[src][2]-1
            if n <= 1:
                continue
            for tip in sorted(self.owned,key=self.key):
                if not any(self.cells.get(x,(0,0,0))[:2] == (BLANK,0) for x in self.graph[tip]):
                    continue
                road = self.path(src,tip,friendly=True)
                if road and len(road)>1:
                    supply.append((len(road)-1+field.get(tip,999)*0.1,src,road[1],n))
        if supply:
            _,src,dst,n = min(supply,key=lambda x:(x[0],self.key(x[1]),self.key(x[2])))
            return self.order(src,dst,n,'opening_branch_supply')
        self.report['mode'] = 'await_witnessed_refresh'
        return None

    def continue_attack(self):
        if not self.commit or self.target is None or self.data(self.target)[1] == self.army:
            self.commit = []
            return None
        src,dst,_ = self.commit[0]
        d = self.cells.get(src)
        guard = self.cells.get(dst)
        if not d or d[1] != self.army or d[2] <= 1 or not guard:
            self.commit = []
            return None
        # The opening prior is not a bound on a mature enemy's returned army.
        # Reveal an unseen capital with a small packet before exposing the main
        # force on its adjacent tile. Keep the original route for repricing.
        if (self.elapsed>=150 and self.target in SPAWNS and self.target not in self.cells
                and self.distances(self.target).get(dst)==1
                and self.distances(self.target).get(src)==2):
            scout = 1 if guard[1]==self.army else guard[2]+1
            if scout<=max(4,(d[2]-1)//10) and d[2]-scout>1:
                self.report.update(target=self.target,recon_cost=scout)
                return self.order(src,dst,scout,'capital_probe')
            self.report['commit_abort'] = 'unseen_capital_requires_recon'
            self.commit = []
            return None
        # Reprice the remaining committed schedule with newly revealed troops.
        # Keep its ordering; do not restart collection for every newborn soldier.
        remaining = (self.forecast([(a,b) for a,b,_ in self.commit],[self.target])
                     if self.commit[-1][1] == self.target else None)
        if self.commit[-1][1] == self.target and (not remaining or remaining['margin'] < 0):
            self.report['commit_abort'] = 'remaining_attack_unfunded'
            self.report['remaining_margin'] = remaining['margin'] if remaining else None
            self.commit = []
            return None
        sent = d[2]-(self.home_keep if src == self.home else 1)
        if guard[1] != self.army and sent <= guard[2]+int(guard[0] in (KING,FORT) and guard[1]>0):
            self.commit = []
            return None
        landing = sent+(guard[2] if guard[1] == self.army else -guard[2])
        for enemy in self.graph[dst]:
            threat = self.cells.get(enemy)
            if (threat and threat[1]>0 and threat[1] != self.army
                    and threat[2]-1+int(threat[0] in (KING,FORT)) >= landing
                    and not (guard[0] == KING and guard[1] == threat[1])):
                self.report['commit_abort'] = 'visible_landing_counterattack'
                self.commit = []
                return None
        self.commit.pop(0)
        self.report.update(target=self.target,objective='capital' if self.target in SPAWNS else 'production')
        return self.order(src,dst,sent,'committed_attack')

    def immediate_king(self):
        finishes = []
        for king in sorted(self.enemies,key=self.key):
            d = self.cells[king]
            if d[0]!=KING:
                continue
            for src in self.graph[king]:
                own = self.cells.get(src)
                keep = self.home_keep if src==self.home else 1
                if own and own[1]==self.army and own[2]-keep>d[2]+1:
                    finishes.append((own[2]-d[2],src,king))
        if finishes:
            _,src,dst = max(finishes,key=lambda x:(x[0],self.key(x[1]),self.key(x[2])))
            self.commit = []
            self.target = dst
            return self.order(src,dst,self.cells[src][2]-1,'immediate_king')
        return None

    def opening_pressure(self):
        """Reconsider both capitals while the scout script is obstructed."""
        if self.commit and self.target in SPAWNS:
            move = self.continue_attack()
            if move:
                return move
        if self.elapsed-self.pressure_checked<3:
            return None
        self.pressure_checked = self.elapsed
        roots = sorted(self.owned,key=lambda p:(-self.cells[p][2],self.key(p)))[:6]
        choices = []
        for target in SPAWNS:
            if target==self.home or self.data(target)[1]==self.army:
                continue
            for root in roots:
                road = self.path(root,target)
                if not road or len(road)>23:
                    continue
                options = [[],self.collection(root,3)]+self.packet_collections(root,12)
                for edges in options:
                    if len(edges)+len(road)-1>24:
                        continue
                    plan = self.forecast(edges,road)
                    if plan and plan['moves'] and plan['margin']>=(1 if target in self.cells else 3):
                        choices.append((plan['steps'],-plan['margin'],self.key(target),target,plan))
        for _,_,_,target,plan in sorted(choices,key=lambda p:p[:3]):
            self.target,self.commit = target,list(plan['moves'])
            move = self.continue_attack()
            if move:
                self.report['opening_pressure'] = dict(target=target,steps=plan['steps'],margin=plan['margin'])
                return move
        return None

    def capital_plans(self, budget=40):
        """Prove a complete capital schedule, including dispersed donors."""
        choices = []
        roots = sorted(self.owned,key=lambda p:(-self.cells[p][2],self.key(p)))[:6]
        for target in SPAWNS:
            if target==self.home or self.data(target)[1]==self.army or self.data(target)[0]!=KING:
                continue
            field = self.distances(target)
            forward = sorted(self.owned,key=lambda p:(field.get(p,999),-self.cells[p][2],self.key(p)))[:2]
            for root in sorted(set(roots+forward),key=self.key):
                road = self.path(root,target)
                if not road or len(road)-1>budget:
                    continue
                options = [self.collection(root,r) for r in (0,2,5,12,20)]
                options += self.packet_collections(root,budget-len(road)+1)
                for edges in options:
                    if len(edges)+len(road)-1>budget:
                        continue
                    plan = self.forecast(edges,road)
                    if plan and plan['moves'] and plan['margin'] >= (0 if target in self.cells else 3):
                        choices.append((plan['steps'],-plan['margin'],self.key(target),target,plan))
        return sorted(choices,key=lambda p:p[:3])

    def early_capital_interrupt(self):
        """An economic commitment must yield to a newly payable elimination."""
        if not self.pulse or self.elapsed>=150 or self.elapsed-self.pressure_checked<3:
            return None
        self.pressure_checked = self.elapsed
        choices = self.capital_plans()
        self.report['capital_recheck'] = dict(funded=len(choices),budget=40,
            source='current legal view and public 314 geometry')
        old_target,old_commit = self.target,list(self.commit)
        for _,_,_,target,plan in choices:
            self.target,self.commit = target,list(plan['moves'])
            move = self.continue_attack()
            if move:
                self.report['early_capital_interrupt'] = dict(previous_target=old_target,
                    target=target,steps=plan['steps'],margin=plan['margin'])
                return move
        self.target,self.commit = old_target,old_commit
        return None

    def assault_plans(self):
        """Pay to reach a useful launch tile; buy king vision separately."""
        plans = []
        strong = sorted(self.owned,key=lambda p:(-self.cells[p][2],self.key(p)))[:8]
        for target in SPAWNS:
            if (target==self.home or target in self.cells
                    or self.data(target)[0]!=KING or self.data(target)[1]==self.army
                    or self.elapsed<self.assault_retry.get(target,0)):
                continue
            field = self.distances(target)
            front = sorted(self.owned,key=lambda p:(field.get(p,999),-self.cells[p][2],self.key(p)))[:3]
            for root in sorted(set(strong+front),key=self.key):
                road = self.path(root,target)
                if not road or len(road)<3 or len(road)>23:
                    continue
                approach = road[:-2]
                stage = approach[-1]
                if field.get(stage)!=2:
                    continue
                options = [self.collection(root,r) for r in (0,2,5,12,20)]
                options += self.packet_collections(root,max(0,36-len(approach)+1))
                for edges in options:
                    if len(edges)+len(approach)-1>36:
                        continue
                    plan = self.forecast(edges,approach)
                    if not plan or plan['margin']<14:
                        continue
                    score = plan['steps']-min(36,plan['margin'])*.4
                    plans.append((score,plan['steps'],-plan['margin'],self.key(target),target,stage,plan))
        return sorted(plans,key=lambda p:p[:4])

    def opening_assault(self):
        """First pulse: forward collection, cheap revelation, then a real strike."""
        if not self.pulse:
            return None
        if self.elapsed>=110:
            if self.assault_target and self.assault_phase!='strike':
                self.commit = []
            self.assault_target = None
            return None
        # Retain a funded king schedule inherited from the pre-pulse planner
        # or campaign reentry. New donors must not restart its collection.
        if not self.assault_target and self.commit and self.target in SPAWNS:
            move = self.continue_attack()
            if move:
                return move
        if self.assault_target:
            target = self.assault_target
            if self.data(target)[1]==self.army:
                self.assault_target = None
                self.commit = []
                self.report['opening_assault_capture'] = target
            elif self.elapsed>self.assault_deadline:
                self.assault_retry[target] = self.elapsed+12
                self.assault_target = None
                self.commit = []
                self.report['opening_assault_abort'] = 'approach_deadline'
            elif self.commit:
                move = self.continue_attack()
                if move:
                    if self.assault_phase=='approach':
                        self.report['mode'] = ('opening_assault_collect' if self.cells[move[1]][1]==self.army
                                               else 'opening_assault_advance')
                        self.report['objective'] = 'capital_recon'
                    return move
                self.assault_target = None
                self.assault_retry[target] = self.elapsed+6
            else:
                stage = self.assault_stage
                own = self.cells.get(stage)
                if own and own[1]==self.army and own[2]>2:
                    if target in self.cells:
                        road = self.path(stage,target)
                        choices = [self.forecast(edges,road) for edges in
                                   [[],self.collection(stage,2)]] if road else []
                        choices = [p for p in choices if p and p['margin']>=0 and p['steps']<=6]
                        if choices:
                            plan = min(choices,key=lambda p:(p['steps'],-p['margin']))
                            self.target,self.commit = target,list(plan['moves'])
                            self.assault_phase = 'strike'
                            move = self.continue_attack()
                            if move:
                                self.report['opening_assault_strike'] = dict(target=target,
                                    steps=plan['steps'],margin=plan['margin'],observed_guard=self.cells[target][2])
                                return move
                        self.report['opening_assault_abort'] = 'observed_king_unfunded'
                    elif self.assault_probe_count==0:
                        entries = []
                        for entry in self.graph[stage]:
                            if entry not in self.graph[target] or entry not in self.cells:
                                continue
                            d = self.cells[entry]
                            cost = 1 if d[1]==self.army else d[2]+1
                            if cost<=4 and own[2]-cost>1:
                                entries.append((cost,self.key(entry),entry))
                        if entries:
                            cost,_,entry = min(entries)
                            self.assault_probe_count += 1
                            self.report.update(target=target,objective='capital_recon',recon_cost=cost)
                            return self.order(stage,entry,cost,'opening_capital_probe')
                        self.report['opening_assault_abort'] = 'probe_exceeds_four_units'
                    else:
                        self.report['opening_assault_abort'] = 'probe_did_not_hold_vision'
                self.assault_retry[target] = self.elapsed+12
                self.assault_target = None
                self.commit = []
        # A visible, actually payable king takes precedence over new scouting.
        for _,_,_,target,plan in self.capital_plans(18):
            if target not in self.cells or self.cells[target][0]!=KING:
                continue
            self.assault_target,self.target = target,target
            self.assault_stage = plan['moves'][0][0]
            self.assault_phase = 'strike'
            self.assault_deadline = self.elapsed+20
            self.commit = list(plan['moves'])
            move = self.continue_attack()
            if move:
                self.report['opening_assault_strike'] = dict(target=target,steps=plan['steps'],margin=plan['margin'])
                return move
            self.assault_target = None
        for _,_,_,_,target,stage,plan in self.assault_plans():
            self.assault_target,self.target = target,target
            self.assault_stage,self.assault_phase = stage,'approach'
            self.assault_probe_count = 0
            self.assault_deadline = self.elapsed+42
            self.commit = list(plan['moves'])
            self.report['opening_assault'] = dict(target=target,stage=stage,
                steps=plan['steps'],landing=plan['margin']+1,vision_required=True)
            if self.commit:
                move = self.continue_attack()
                if move:
                    self.report['mode'] = ('opening_assault_collect' if self.cells[move[1]][1]==self.army
                                           else 'opening_assault_advance')
                    self.report['objective'] = 'capital_recon'
                    return move
                self.assault_target = None
            else:
                return self.opening_assault()
        return None

    def late_opportunity(self, bot, cells):
        """A bounded capital attack option for a developed positional game.

Normal play keeps its own proposal arbitration until this option is funded.
History comes from bot.memory (past legal views), never an authority snapshot.
"""
        early = bot.calls<150
        visible_finish = any(d[0]==KING and d[1]>0 and d[1]!=self.army
            and any(cells.get(p,(0,0,0))[1]==self.army
                    and cells[p][2]-1>=d[2]+2 for p in self.graph[target])
            for target,d in cells.items() if target in self.graph)
        if not visible_finish and (bot.calls < 48 or bot.calls % (3 if early else 8)):
            return False
        owned = [p for p,d in cells.items() if d[1] == self.army]
        if not owned or (not any(cells[p][2]>1 for p in owned) if early or visible_finish
                         else max(cells[p][2] for p in owned)<80):
            return False
        self.pending = None
        self.elapsed = max(self.elapsed,bot.tick)
        for p,d in bot.memory.items():
            self.history[p] = (d[:3],d[3])
        prior_touched = {bot.pending['src'],bot.pending['dst']} if bot.pending else set()
        self.observe(cells,previous=bot.cells,touched=prior_touched)
        threats = {}
        for distance,force,p,owner in self.incoming(self.home,8 if early else 12):
            threats[owner] = max(threats.get(owner,0),force)
        self.home_keep = max(1,sum(threats.values())+4)
        if early or visible_finish:
            plans = self.capital_plans(40 if early else 2)
            if not plans:
                if early and self.pulse and self.elapsed<110 and self.assault_plans():
                    bot._map314_late_active = True
                    bot._map314_late_started = bot.calls
                    return True
                self.home_keep = 1
                return False
            _,_,_,self.target,plan = plans[0]
            self.commit = list(plan['moves'])
            bot._map314_late_active = True
            bot._map314_late_started = bot.calls
            self.capital_entry = dict(steps=plan['steps'],margin=plan['margin'],
                bypassed_stack_gate=True,visible_finish=visible_finish)
            return True
        best = None
        roots = sorted(self.owned,key=lambda p:(-cells[p][2],self.key(p)))[:4]
        for target in SPAWNS:
            if target == self.home or self.data(target)[1] == self.army:
                continue
            for root in roots:
                road = self.path(root,target)
                if not road or len(road)>29:
                    continue
                options = [self.collection(root,radius) for radius in (0,3,8)]
                options += self.packet_collections(root,28-(len(road)-1))
                for edges in options:
                    if len(edges)+len(road)-1>28:
                        continue
                    plan = self.forecast(edges,road)
                    if not plan or plan['steps']>28:
                        continue
                    required = (1 if target in cells else 6) if early else (12 if target in cells else 40)
                    if plan['margin'] < required:
                        continue
                    key = (plan['steps'],-plan['margin'],self.key(target))
                    if best is None or key < best[0]:
                        best = key,target,plan
        if best is None:
            self.home_keep = 1
            return False
        _,self.target,plan = best
        self.commit = list(plan['moves'])
        bot._map314_late_active = True
        bot._map314_late_started = bot.calls
        return True

    def tactics(self):
        if self.target and self.target not in SPAWNS and self.data(self.target)[1] == self.army:
            self.report['production_bridge_complete'] = True
        # Enemy departures and inheritance can create a one-command win while
        # an older collection schedule is still running. Recheck every view.
        move = self.immediate_king()
        if move:
            return move
        incoming = self.incoming(self.home)
        # A complete rescue must fit the same single-command budget as offense.
        # Moving a one-unit donor during a forced loss merely delays our race.
        serious = [x for x in incoming if x[1]+1 >= self.cells[self.home][2]+max(0,(x[0]-1)//2)]
        if serious:
            deadline,force,src,owner = serious[0]
            returns = []
            for p in sorted(self.owned,key=self.key):
                if p == self.home or self.cells[p][2]<=1:
                    continue
                road = self.path(p,self.home,friendly=True)
                if not road or len(road)-1>deadline:
                    continue
                reinforcement = self.cells[p][2]-1+sum(self.cells[q][2]-1 for q in road[1:-1])
                final_guard = self.cells[self.home][2]+max(0,(deadline-1)//2)+reinforcement
                if final_guard>force:
                    returns.append((len(road)-1,-reinforcement,p,road[1]))
            if returns:
                _,_,p,q = min(returns,key=lambda x:(x[0],x[1],self.key(x[2]),self.key(x[3])))
                self.commit = []
                return self.order(p,q,self.cells[p][2]-1,'packet_return_defense')
            rescue = self.collection(self.home,deadline)
            if rescue and len(rescue) <= deadline:
                projected = self.forecast(rescue,[self.home])
                if projected and projected['margin']+1+max(0,(deadline-len(rescue))//2)>force:
                    self.commit = []
                    p,q = rescue[0]
                    return self.order(p,q,self.cells[p][2]-1,'complete_return_defense')
            self.report['unfunded_defense'] = dict(deadline=deadline,force=force)
        threats = {}
        for distance,force,p,owner in incoming:
            threats[owner] = max(threats.get(owner,0),force)
        if self.pulse and self.elapsed<110:
            self.home_keep = max(self.home_keep,1,sum(threats.values())+4 if threats else 1)
            move = self.opening_assault()
            if move:
                return move
        if self.commit and self.target not in SPAWNS:
            move = self.early_capital_interrupt()
            if move:
                return move
        move = self.continue_attack()
        if move:
            return move
        targets = [p for p in SPAWNS if p != self.home and self.data(p)[1] != self.army]
        roots = sorted(self.owned,key=lambda p:(-self.cells[p][2],self.key(p)))[:6]
        roots += [p for p in self.owned if any(n not in self.owned for n in self.graph[p]) and self.cells[p][2]>1]
        if len(self.owned)>50:
            roots = sorted(set(roots),key=lambda p:(-self.cells[p][2],self.key(p)))[:12]
        roots = sorted(set(roots),key=self.key)
        collections = {}
        plans = []
        for target in targets:
            for root in roots:
                route = self.path(root,target)
                if not route:
                    continue
                options = []
                for radius in (0,2,5,12,30):
                    key = root,radius
                    if key not in collections:
                        collections[key] = self.collection(root,radius)
                    options.append(collections[key])
                if self.pulse:
                    key = root,'packets'
                    if key not in collections:
                        collections[key] = self.packet_collections(root)
                    options += collections[key]
                for edges in options:
                    if len(self.owned)>50 and len(edges)+len(route)-1>60:
                        continue
                    plan = self.forecast(edges,route)
                    if plan and plan['moves']:
                        # Positive margin permits capture against stationary observed guard.
                        score = (1000-plan['steps']*5+min(30,plan['margin']) if plan['margin']>=0
                                 else plan['margin']*3-plan['steps']*2)
                        if target == self.target:
                            score += 2
                        # Private per-game tie preference breaks a three-way
                        # symmetry only among similarly valued attack options.
                        # It never inserts random waiting or overrides legality.
                        score += self.target_bias[target]
                        plans.append((score,target,plan))
        plans.sort(key=lambda x:(-x[0],self.key(x[1]),x[2]['steps']))
        self.report['incoming'] = incoming
        if plans:
            score,target,best = plans[0]
            self.report.update(target=target,attack_margin=best['margin'],attack_steps=best['steps'])
        for _,target,best in plans:
            if best['margin'] < 0:
                continue
            self.target = target
            self.commit = list(best['moves'])
            move = self.continue_attack()
            if move:
                return move
        # A failed capital forecast must not discard the corridor investment.
        # Reuse the same single-order collection model to fund a nearby neutral
        # producer, including home growth earned while distant donors return.
        production = []
        home_field = self.distances(self.home)
        local_forts = sorted((p for p,d in self.cells.items() if d[0] == FORT and d[1] == 0),
                             key=lambda p:(home_field.get(p,999),self.key(p)))[:4]
        production_roots = [self.home]+sorted((p for p in roots if p != self.home),
            key=lambda p:(-self.cells[p][2],home_field.get(p,999),self.key(p)))[:3]
        for target in local_forts:
            for root in production_roots:
                route = self.path(root,target)
                if not route or len(route)>9:
                    continue
                for radius in (0,5,12,30):
                    key = root,radius
                    if key not in collections:
                        collections[key] = self.collection(root,radius)
                    edges = collections[key]
                    if len(edges)+len(route)-1>30:
                        continue
                    plan = self.forecast(edges,route)
                    if plan and plan['margin']>=0:
                        penalty = 3*(1-border_fort_factor(self.cells,self.graph,self.army,target,self.elapsed))/MAX_FORT_DISCOUNT
                        production.append((plan['steps']+penalty, -plan['margin'],target,plan))
        for _,_,target,plan in sorted(production,key=lambda x:(x[0],x[1],self.key(x[2]))):
            self.target = target
            self.commit = list(plan['moves'])
            move = self.continue_attack()
            if move:
                self.report['production_bridge'] = target
                return move
        self.report['no_funded_attack'] = True
        # Cheap expansion earns the next refresh; inherited producers join the
        # same action budget. Prefer production only with a useful surplus.
        choices = []
        for src in sorted(self.owned,key=self.key):
            n = self.cells[src][2]-1
            if n <= 0:
                continue
            for dst in self.graph[src]:
                if dst not in self.cells or dst in self.owned:
                    continue
                d = self.cells[dst]
                if n <= d[2]+(4 if d[0] == FORT else 0):
                    continue
                value = (20*border_fort_factor(self.cells,self.graph,self.army,dst,self.elapsed) if d[0] == FORT else 1)-d[2]*0.3
                choices.append((value,src,dst,d[2]+1 if d[0] != FORT else n))
        if choices:
            _,src,dst,n = max(choices,key=lambda x:(x[0],self.key(x[1]),self.key(x[2])))
            return self.order(src,dst,n,'economy')
        self.report['mode'] = 'wait_for_force'
        return None

    def decide(self):
        self.report = dict(mode='opening_wait',opening_index=self.index,
                           pulse=self.pulse,clock_estimate=self.elapsed,
                           producer_phase_age=self.pulse_age,
                           producer_growth_next=self.growth_next,
                           tie_seed=self.seed,
                           owned=len(self.owned),units=sum(self.cells[p][2] for p in self.owned))
        if self.capital_entry:
            self.report['early_capital_reentry'] = self.capital_entry
            self.capital_entry = None
        if self.home not in self.owned:
            self.report['mode'] = 'eliminated'
            return None
        move = self.immediate_king()
        if move:
            return move
        if not self.opening_done and not self.pulse:
            if self.harvest or self.index>=10:
                move = self.opening_pressure()
                if move:
                    return move
            if self.index == 17 and not self.directed:
                self.directed = True
                hub = rotate((11,10),self.turns)
                roads = [(self.path(hub,target),target) for target in SPAWNS if target != self.home]
                roads = [(road,target) for road,target in roads if road]
                if roads:
                    road,self.target = min(roads,key=lambda x:(
                        len(x[0])+sum(self.data(p)[2]*0.16 for p in x[0][1:-1]
                                      if self.data(p)[1] != self.army)-self.target_bias[x[1]]*0.15,
                        self.key(x[1])))
                    self.opening = self.opening[:17]+[(a,b,0) for a,b in zip(road[:-3],road[1:-2])]
                    self.report['opening_direction'] = self.target
            if self.harvest:
                return self.harvest_action()
            if self.index >= len(self.opening):
                return self.harvest_action()
            src,dst,fixed = self.opening[self.index]
            d = self.cells.get(src)
            if d is None or d[1] != self.army:
                self.opening_done = True
                self.report['opening_abort'] = 'lost_route'
            elif self.incoming(self.home,5):
                self.opening_done = True
                self.report['opening_abort'] = 'home_threat'
            else:
                amount = fixed or d[2]-1
                dest = self.cells.get(dst)
                if dest and dest[1] not in (0,self.army) and amount <= dest[2]:
                    self.harvest = True
                    self.report['opening_abort'] = 'contested_scout_to_replan'
                    move = self.opening_pressure()
                    if move:
                        return move
                    return self.harvest_action()
                elif d[2] > amount > 0:
                    return self.order(src,dst,amount,'opening_corridor',opening=True)
                else:
                    return None
        self.opening_done = True
        return self.tactics()


def decide(bot, cells, hill_hints=None):
    previous = bot.cells
    touched = {bot.pending['src'],bot.pending['dst']} if bot.pending else set()
    existing = getattr(bot,'_map314_controller',None)
    if existing and existing.pending:
        touched.update(existing.pending[:2])
    bot.update(cells,hill_hints)
    if not hasattr(bot,'_map314_controller'):
        bot._map314_controller = Controller(bot)
    controller = bot._map314_controller
    if controller.observe(cells,previous=previous,touched=touched):
        move = controller.decide()
    else:
        controller.report = dict(mode='await_confirmation',opening_index=controller.index,pulse=controller.pulse)
        move = None
    bot.last_report = controller.report
    if getattr(bot,'_map314_late_active',False):
        bot.last_report['strategy_phase'] = '314_funded_capital_breakout'
        bot.last_report['capital_breakout_keep'] = controller.home_keep
        # Reassess after the bounded schedule instead of making an indefinite
        # second policy. A capture can continue through inherited assets.
        if bot.calls-getattr(bot,'_map314_late_started',bot.calls)>40:
            bot._map314_late_active = False
            controller.home_keep = 1
    # The first pulse/rush is a specialized option, not an obligation to use a
    # short-horizon passive-guard model throughout a developed positional game.
    # Keep current orders reconcilable when the mature campaign takes over.
    if (controller.pulse and bot.home
            and not (controller.target in SPAWNS and (controller.commit
                or controller.report.get('objective')=='capital'
                or controller.report.get('mode')=='immediate_king'))
            and (controller.report.get('production_bridge_complete') or
            ((controller.elapsed >= 110 or controller.report.get('no_funded_attack'))
             and sum(cells[p][0] in (KING,FORT) for p in bot.owned) == 1))):
        bot._map314_handoff = True
        if move:
            src,dst,sent = move
            bot.pending = dict(src=src,dst=dst,sent=sent,role='advance',tick=bot.tick,
                               before_src=cells[src],before_dst=cells.get(dst),advance=True)
        bot.last_report['campaign_handoff'] = ('first-wave production bridge captured' if controller.report.get('production_bridge_complete') else
            'no funded first-wave attack' if controller.report.get('no_funded_attack') else 'first wave expired without inheritance or new production')
    return move
