"""Two-command king strikes funded by current local stock.

The opponent has two orders, so observed donors are bounded by two direct
dispatches or one two-edge merge. A king sortie onto the staging cell reduces
both sides of the final comparison equally. Home may release its ordinary
reserve only when this staging cell blocks every two-edge king route home,
or the remaining home stock independently covers the visible reply budget.
Unknown reinforcements are not invented. This remains a public-board policy,
not a certificate against hidden forces or arbitrary native rule changes.
"""
from std_geometry import KING, FORT, MARSH, BLOCKED, hex_distance


def departure_budget(bot, target, horizon=2):
    """Budget the largest recent observed departure that could return in time.

    This is combined with the visible reply by maximum: a returning column
    may be the same column already visible again. It is an uncertainty proxy,
    not a certificate against multiple independent unseen reinforcements.
    """
    if not bot.config.get('king_departure_reply', False):
        return 0
    warning = getattr(bot, '_departure_warning', None)
    if warning is None:
        return 0
    owner = bot.cells[target][1]
    age_limit = bot.config.get('mobile_departure_steps', 0)
    budget = 0
    for record in warning.records:
        if (record['owner'] != owner or owner in bot.eliminated
                or bot.calls-record['born'] > age_limit):
            continue
        if any(hex_distance(pos, target) <= horizon for pos in record['region']):
            budget = max(budget, max(0, record['units']-1))
    return budget


def reply_budget(bot, endpoints, excluded=()):
    """Estimate visible mobile stock reaching an endpoint in two commands.

One natural growth allowance per producer is included. The top two direct
donors and every two-edge friendly-enemy merge are compared, never summed
across mutually exclusive two-command schedules.
"""
    excluded=set(excluded)
    roots=set(endpoints)
    enemy={p for p,d in bot.cells.items() if d[1]>0 and d[1]!=bot.army
           and p not in excluded and p not in roots}
    direct={p for root in roots for p in bot.neighbors[root] if p in enemy}
    # Ordinary claims need a soldier left behind; producers can grow once.
    # Unseen reinforcements and uncalibrated global growth are not modeled.
    payload=lambda p:max(0,bot.cells[p][2]-1+(1 if bot.cells[p][0] in (KING,FORT) else 0))
    largest=sorted((payload(p) for p in direct),reverse=True)
    best=sum(largest[:2])
    for mid in direct:
        for src in bot.neighbors[mid]:
            if src in enemy and bot.cells[src][1]==bot.cells[mid][1]:
                best=max(best,payload(mid)+payload(src))
    return best


def king_bypass(bot, target, stage):
    """Unknown common cells are possible alternative two-edge king routes."""
    if bot.home in bot.neighbors[target]:
        return True
    common=set(bot.neighbors[target]) & set(bot.neighbors[bot.home])
    return any(p!=stage and (p not in bot.cells or bot.cells[p][0] not in BLOCKED)
               for p in common)


def plan(bot):
    if not bot.config.get('king_two_command_strike',False):
        return None
    owners={d[1] for d in bot.cells.values() if d[1]>0 and d[1]!=bot.army}
    if len(owners)!=1:
        return None
    proposals=[]
    for target in bot.enemies:
        if bot.cells[target][0]!=KING:
            continue
        for stage in bot.neighbors[target]:
            data=bot.cells.get(stage)
            if not data or data[1]!=bot.army or data[0] in (KING,MARSH)+BLOCKED:
                continue
            visible=reply_budget(bot,(target,stage),excluded=(target,))
            returning=departure_budget(bot,target)
            donation=max(visible,returning)
            # Leave one on stage; cover two king growth allowances and a strict
            # winning surplus. No future friendly production funds this packet.
            packet=bot.cells[target][2]+donation+3-data[2]
            if packet<=0:
                continue
            bypass=king_bypass(bot,target,stage)
            guard=max(2,reply_budget(bot,(bot.home,),excluded=() if bypass else (target,))+1)
            if bypass:
                # A geometrically possible unknown intermediate cannot erase
                # the already observed king stack from the home reply budget.
                common=set(bot.neighbors[target]) & set(bot.neighbors[bot.home])
                alternatives=[p for p in common if p != stage
                              and (p not in bot.cells or bot.cells[p][0] not in BLOCKED)]
                if any(p not in bot.cells for p in alternatives):
                    guard=max(guard,bot.cells[target][2]+donation+3)
                else:
                    # Two commands must leave a soldier on both source and
                    # bypass. An opposing garrison there is consumed; a rival
                    # garrison can merge. Both growth allowances are charged.
                    for mid in alternatives:
                        _,owner,units=bot.cells[mid]
                        stock=bot.cells[target][2]+(units if owner==bot.cells[target][1] else -units)-1
                        guard=max(guard, stock+1)
            for src in bot.neighbors[stage]:
                cell=bot.cells.get(src)
                if (not cell or cell[1]!=bot.army or src==target
                        or cell[0] in (MARSH,)+BLOCKED or target in bot.neighbors[src]):
                    continue
                available=(cell[2]-guard if src==bot.home else bot.available(src))
                if src!=bot.home:
                    available=min(available,cell[2]-1-bot.counter(src,excluded=(target,)))
                held=bot.cells[bot.home][2]-(packet if src==bot.home else 0)
                if packet>available or held<guard:
                    continue
                proposals.append(dict(target=target,route=[src,stage,target],packet=packet,
                    guard=guard,source=src,stage=stage,enemy=bot.cells[target][2],
                    visible_two_order_donation=visible,observed_departure_budget=returning,
                    reply_donation_budget=donation,king_bypass=bypass,
                    stage_after_dispatch=data[2]+packet,home_after_dispatch=held,
                    source_current=cell[2],funded=True,
                    model='current visible two-order reply budget; king sortie conserves strike difference'))
    return min(proposals,key=lambda p:(p['packet'],p['source']==bot.home,p['target'],p['source'])) if proposals else None


def propose(choices, strike):
    if strike:
        choices.append((1200000,strike['source'],strike['stage'],strike['packet'],
                        'tempo_king',strike['target']))
