"""Carry large observed hostile packets through loss of public visibility.

Reachable hidden cells form a possibility set, not a known enemy location.
Visible gains cannot establish packet identity. The forecast takes a maximum
within each opponent and adds across independently commanded opponents.
Unknown combat and expiry make this a risk model, not a safety certificate.
"""
from std_geometry import BLOCKED

WINDOW = 64
MIN_PACKET = 64


class ForceBelief:
    def __init__(self):
        self.at = None
        self.records = []

    def hidden(self,bot,region):
        return {p for p in region if p not in bot.cells
                and bot.memory.get(p,(0,))[0] not in BLOCKED}

    def observe(self,bot):
        if self.at == bot.calls:
            return
        self.at = bot.calls
        gains = {}
        for pos,data in bot.cells.items():
            if data[1] in (0,bot.army) or data[1] in bot.eliminated:
                continue
            old = bot.previous.get(pos)
            gain = data[2]-(old[2] if old and old[1] == data[1] else 0)
            # Single producer growth is not a reappearing field army.
            if gain >= 8:
                gains[pos] = [data[1],gain]

        def reconcile(owner,region,units):
            # An increase in the reachable region can belong to another
            # independently moving packet. Preserve that ambiguity until
            # observation removes every possible hidden location.
            return units

        live = []
        for record in self.records:
            if (bot.calls-record['born'] > WINDOW
                    or record['owner'] in bot.eliminated):
                continue
            expanded = set(record['region'])
            for pos in record['region']:
                expanded.update(bot.neighbors[pos])
            units = reconcile(record['owner'],expanded,record['units'])
            region = self.hidden(bot,expanded)
            if units >= 8 and region:
                live.append(dict(record,units=units,region=region))
        pending = getattr(bot,'_observed_pending',None)
        for source,old in sorted(bot.previous.items()):
            kind,owner,units = old
            if owner in (0,bot.army) or owner in bot.eliminated or units < MIN_PACKET:
                continue
            now = bot.cells.get(source)
            loss = units-(now[2] if now and now[1] == owner else 0)
            if pending and pending['dst'] == source:
                loss = max(0,loss-pending['sent'])
            vicinity = set(bot.neighbors[source])|{source}
            remaining = reconcile(owner,vicinity,max(0,loss))
            region = self.hidden(bot,vicinity)
            if remaining >= MIN_PACKET and region:
                live.append(dict(owner=owner,origin=source,units=remaining,
                    born=bot.calls,region=region))
        self.records = live

    def curve(self,bot,horizon,margin):
        self.observe(bot)
        by_owner = {}
        active = []
        for record in self.records:
            eta = max(1,min([bot.risk_dist.get(p,999) for p in record['region']] or [999]))
            if eta > horizon:
                continue
            force = max(0,record['units']-eta)
            curve = by_owner.setdefault(record['owner'],[0]*(horizon+1))
            for h in range(eta,horizon+1):
                curve[h] = max(curve[h],force)
            active.append(dict(owner=record['owner'],origin=record['origin'],
                units=record['units'],age=bot.calls-record['born'],eta=eta,
                hidden_options=len(record['region'])))
        result = [sum(c[h] for c in by_owner.values()) for h in range(horizon+1)]
        result = [force+(margin if force else 0) for force in result]
        return result,active


def augment(bot,curve,horizon,margin):
    if not hasattr(bot,'_force_belief'):
        bot._force_belief = ForceBelief()
    projected,active = bot._force_belief.curve(bot,horizon,margin)
    if hasattr(bot,'last_report'):
        bot.last_report['force_belief'] = dict(records=active,window=WINDOW,
            source='public observed large stock; reachable hidden cells')
    if (active and len(getattr(bot,'known_owners',())) >= 2
            and sum(bot.cells[p][0] in (2,3) for p in bot.owned) >= 12):
        bot._empire_force_entered = True
    bot.last_report['empire_force_policy'] = dict(active=getattr(bot,'_empire_force_entered',False),
        producer_entry=12,exit='match end; records expire independently')
    if not getattr(bot,'_empire_force_entered',False):
        return curve
    return [max(a,b) for a,b in zip(curve,projected)]


def observe_only(bot,horizon,margin):
    if not hasattr(bot,'_force_belief'):
        bot._force_belief = ForceBelief()
    bot._force_belief.curve(bot,horizon,margin)


def dispatch_allowed(bot,src,dst,amount,role):
    if (src != bot.home or role == 'finish_king'
            or len(getattr(bot,'known_owners',())) < 2
            or sum(bot.cells[p][0] in (2,3) for p in bot.owned) < 4):
        return True
    tracker = getattr(bot,'_force_belief',None)
    if tracker is None:
        return True
    curve,active = tracker.curve(bot,12,2)
    if not active:
        return True
    keep = max([1]+[force-(h-1)//2 for h,force in enumerate(curve) if h])+12
    permitted = bot.cells[src][2]-amount >= keep
    if not permitted:
        bot.last_report.setdefault('unresolved_dispatch_rejected',[]).append(dict(
            src=src,dst=dst,sent=amount,role=role,keep=keep,records=active))
    return permitted
