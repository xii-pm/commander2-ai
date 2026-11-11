"""Short warning from unexplained visible hostile departures, not snapshots.

A departure must leave an observed stock decrease which our prior attack and
adjacent visible gains cannot explain. Its possible locations start in current
adjacent fog, then expand by one edge per legal observation and lose visible
locations. Visible reappearance reduces the remaining mass. Warnings expire;
records and the ordinary threat curve are combined by maximum, never added.

This is a conservative evidence filter and a bounded risk heuristic. It does
not identify a hidden unit, model unknown combat, or certify king survival.
"""
from std_geometry import BLOCKED


class DepartureWarning:
    def __init__(self):
        self.records = []
        self.updated_at = None
        self.events = []

    @staticmethod
    def visible_gain(bot, pos, owner):
        current = bot.cells.get(pos)
        if not current or current[1] != owner:
            return 0
        previous = bot.previous.get(pos)
        return max(0, current[2]-(previous[2] if previous and previous[1] == owner else 0))

    @staticmethod
    def hidden(bot, positions):
        return {p for p in positions if p not in bot.cells
                and bot.memory.get(p,(0,))[0] not in BLOCKED}

    def observe(self, bot):
        if self.updated_at == bot.calls:
            return
        self.updated_at, self.events = bot.calls, []
        window = bot.config.get('mobile_departure_steps', 0)
        if not window:
            self.records = []
            return
        live = []
        for record in self.records:
            if bot.calls-record['born'] > window or record['owner'] in bot.eliminated:
                self.events.append('expired or eliminated')
                continue
            expanded = set(record['region'])
            for pos in record['region']:
                expanded.update(bot.neighbors[pos])
            # A visible increase can account for this packet. Removing the
            # full observed increase is deliberately conservative about fog.
            explained = sum(self.visible_gain(bot,p,record['owner']) for p in expanded)
            remaining = max(0, record['units']-explained)
            region = self.hidden(bot,expanded)
            if remaining < 8 or not region:
                self.events.append('visible reconciliation or no hidden location')
                continue
            live.append(dict(record,units=remaining,region=region))
        pending = getattr(bot, '_observed_pending', None)
        by_owner = {}
        for source, previous in sorted(bot.previous.items()):
            _, owner, units = previous
            if owner <= 0 or owner == bot.army or owner in bot.eliminated or units < 8:
                continue
            current = bot.cells.get(source)
            if current is None:
                # Losing sight alone does not prove departure. Ordinary cell
                # memory continues to handle that separate uncertainty.
                continue
            drop = units-(current[2] if current[1] == owner else 0)
            combat = pending['sent'] if pending and pending['dst'] == source else 0
            visible = sum(self.visible_gain(bot,p,owner) for p in bot.neighbors[source])
            remaining = max(0, drop-combat-visible)
            region = self.hidden(bot,bot.neighbors[source])
            if remaining < 8 or not region:
                continue
            record = dict(owner=owner,origin=source,units=remaining,born=bot.calls,
                          region=region,observed_drop=drop,combat_explanation=combat,
                          visible_explanation=visible)
            if owner not in by_owner or (remaining,source) > (by_owner[owner]['units'],by_owner[owner]['origin']):
                by_owner[owner] = record
        for owner,record in sorted(by_owner.items()):
            live.append(record)
            self.events.append(dict(event='unexplained visible departure',origin=record['origin'],
                owner=owner,units=record['units'],hidden_options=len(record['region'])))
        self.records = live

    def curve(self, bot, horizon, margin):
        self.observe(bot)
        curve,active = [0]*(horizon+1), []
        for record in self.records:
            eta = max(1,min([bot.risk_dist.get(p,999) for p in record['region']] or [999]))
            force = max(0,record['units']-eta)
            if eta > horizon or not force:
                continue
            active.append(dict(owner=record['owner'],origin=record['origin'],
                age=bot.calls-record['born'],units=record['units'],eta=eta,force=force,
                hidden_options=len(record['region'])))
            for h in range(eta,horizon+1):
                curve[h] = max(curve[h],force+margin)
        return curve,active
