"""Bounded missing-force scenarios from legal public observations.

Visible gains do not identify a previously missing packet. The scenario is
retained while any hypothesized location is fogged, until expiry/elimination.
Observation calls are not logical ticks; this is not a reachability guarantee.
"""
from std_geometry import BLOCKED, KING, FORT

MIN_PACKET = 24
WINDOW = 32
RADIUS = 6
MAX_PER_OWNER = 4


class RivalPressure:
    def __init__(self):
        self.at = None
        self.records = []

    @staticmethod
    def hidden(bot, region):
        return {p for p in region if p not in bot.cells
                and bot.memory.get(p, (0,))[0] not in BLOCKED}

    def observe(self, bot):
        if self.at == bot.calls:
            return
        self.at = bot.calls
        live = []
        for record in self.records:
            if record['owner'] in bot.eliminated or bot.calls-record['born'] > WINDOW:
                continue
            expanded = set(record['region'])
            for pos in record['region']:
                expanded.update(bot.neighbors[pos])
            region = self.hidden(bot, expanded)
            if region:
                live.append(dict(record, region=region))
        pending = getattr(bot, '_observed_pending', None)
        for pos, old in sorted(bot.previous.items()):
            kind, owner, units = old
            if (owner <= 0 or owner == bot.army or owner in bot.eliminated
                    or units < MIN_PACKET or bot.risk_dist.get(pos,999) > RADIUS):
                continue
            now = bot.cells.get(pos)
            # Loss of visibility alone is not evidence of departure here.
            if now is None:
                continue
            loss = units-(now[2] if now[1] == owner else 0)
            explained = pending['sent'] if pending and pending['dst'] == pos else 0
            missing = max(0, loss-explained)
            region = self.hidden(bot, bot.neighbors[pos])
            if missing >= MIN_PACKET and region:
                live.append(dict(owner=owner, origin=pos, units=missing,
                    born=bot.calls, region=region, observed_loss=loss,
                    own_attack_explanation=explained))
        selected = []
        for owner in sorted({r['owner'] for r in live}):
            rows = sorted((r for r in live if r['owner'] == owner),
                key=lambda r:(r['units'],r['born'],r['origin']),reverse=True)
            selected.extend(rows[:MAX_PER_OWNER])
        self.records = selected

    def project(self, bot, horizon, excluded=()):
        self.observe(bot)
        by_owner, active = {}, []
        for record in self.records:
            # Capturing an origin remnant does not erase a packet which may
            # already have left it. Only public resolution/expiry removes it.
            eta = max(1,min([bot.risk_dist.get(p,999) for p in record['region']] or [999]))
            force = max(0,record['units']-eta)
            if eta > horizon or not force:
                continue
            owner_curve = by_owner.setdefault(record['owner'],[0]*(horizon+1))
            for h in range(eta,horizon+1):
                owner_curve[h] = max(owner_curve[h],force)
            active.append(dict(owner=record['owner'],origin=record['origin'],units=record['units'],
                age=bot.calls-record['born'],eta=eta,hidden_options=len(record['region'])))
        return by_owner, active


def visible_curves(bot, horizon, excluded=()):
    """Current visible stacks share each owner's one-command scenario budget."""
    excluded = set(excluded)
    arrivals = {}
    for pos, (kind,owner,units) in bot.cells.items():
        if owner <= 0 or owner == bot.army or owner in bot.eliminated or pos in excluded:
            continue
        distance = max(1,bot.risk_dist.get(pos,999))
        if distance <= horizon:
            arrivals.setdefault(owner,[]).append((distance,units,kind))
    result = {}
    for owner, stacks in arrivals.items():
        curve = [0]
        for h in range(1,horizon+1):
            budget = [0]*(h+1)
            for distance,units,kind in stacks:
                if distance > h:
                    continue
                force = max(0,units-distance)+((h+1)//2 if kind in (KING,FORT) else 0)
                for cost in range(h,distance-1,-1):
                    budget[cost] = max(budget[cost],budget[cost-distance]+force)
            curve.append(max(budget))
        result[owner] = curve
    return result


def augment(bot, curve, horizon, excluded=(), zero_uncertainty=True):
    if not hasattr(bot,'_rival_pressure'):
        bot._rival_pressure = RivalPressure()
    missing, records = bot._rival_pressure.project(bot,horizon,excluded)
    owners = {d[1] for p,d in bot.cells.items() if d[1]>0 and d[1]!=bot.army
              and d[1] not in bot.eliminated and bot.risk_dist.get(p,999)<=RADIUS}
    scoped = (len(owners)>=2 and len(set(bot.known_owners)-set(bot.eliminated))>=2
              and not getattr(bot,'map314',0))
    visible = visible_curves(bot,horizon,excluded) if scoped and records else {}
    scenario = [0]*(horizon+1)
    for owner in set(visible)|set(missing):
        a,b = visible.get(owner,[0]*(horizon+1)),missing.get(owner,[0]*(horizon+1))
        for h in range(1,horizon+1):
            scenario[h] += max(a[h],b[h])
    margin = bot.config.get('threat_margin',2)
    scenario = [n+(margin if n else 0) for n in scenario]
    combined = [max(a,b) for a,b in zip(curve,scenario)] if scoped else list(curve)
    # Record the full default curve only; target-exclusion queries must not
    # overwrite the diagnostic for the current board.
    if not excluded and horizon == 12:
        bot.last_report['rival_pressure'] = dict(scoped=scoped, records=records,
            baseline=list(curve), scenario=scenario, combined=combined,
            applied=combined!=list(curve), window_calls=WINDOW,
            model='bounded ambiguous missing-force scenario; no packet identity or clock guarantee')
    return combined
