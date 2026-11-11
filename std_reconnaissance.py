"""Small current-funded information routes after a local search chooses waiting.

Adapted from Probe's information-per-command scouting, within the proposal
architecture. Unknown cells and silhouettes are never traversed. No future
growth pays the route. Visible threat checks are estimates, not safety proofs.
"""
from std_geometry import BLANK, KING, FORT, hex_distance


def propose(bot, choices, movable):
    if (not bot.config.get('opening_wait_recon',False)
            or not getattr(bot,'_opening_contact',False)):
        return
    curve=bot.threat_curve(6)
    held=bot.cells[bot.home][2]
    if any(force > held for force in curve[1:]):
        return
    focus=getattr(bot,'_information_focus',None)
    options=[]
    sources=sorted(bot.owned,key=lambda p:(-min(4,movable[p]),p))[:8]
    if bot.home not in sources:
        sources.append(bot.home)
    for src in sources:
        available=min(4,movable[src])
        if src == bot.home:
            available=min(available,max(0,held-max(curve[1:])-1))
        if available < 1:
            continue
        stack=[(src,(src,),0,0)]
        while stack:
            p,path,cost,packet=stack.pop()
            if len(path)>1 and bot.cells[p][1] != bot.army:
                sight=bot.new_sight(p)
                if sight:
                    progress=(hex_distance(src,focus)-hex_distance(p,focus)) if focus else 0
                    score=(5*len(sight)+8*len(sight & bot.hill_hints)+3*progress
                           -2*bot.visits.get(p,0))/float(len(path)-1+cost*.2)
                    if score>0:
                        options.append((score,src,path,packet))
            if len(path)>=4:
                continue
            for dst in bot.neighbors[p]:
                if dst in path or dst not in bot.cells:
                    continue
                kind,owner,units=bot.cells[dst]
                if kind != BLANK or owner not in (0,bot.army):
                    continue
                # Existing friendly soldiers are not pledged as later pickups.
                # Neutral occupation and empty roads consume a current soldier.
                newcost=cost+(units+1 if owner==0 else int(units==0))
                counter=bot.counter(dst)
                required=max(packet,newcost+counter)
                if required>available:
                    continue
                stack.append((dst,path+(dst,),newcost,required))
    if not options:
        return
    value,src,path,packet=max(options,key=lambda option:(option[0],-option[3],option[1],option[2]))
    if packet<=0:
        return
    choices.append((500001+min(100,value),src,path[1],packet,'recon_wait',path[-1]))
    bot.last_report['opening_wait_recon']=dict(source=src,route=path,packet=packet,
        value=round(value,3),current_king_units=held,visible_threat=curve,
        model='Up to four current soldiers and three visible edges; no future growth or unknown road.')


def propose_stalled_contact(bot, choices, movable):
    """A thin contact opening may spend field scouts to break a long standstill.

    The king is excluded from this supplement. Ordinary search waiting still
    retains its own original scouting proposals and defense checks.
    """
    if (not bot.config.get('opening_wait_recon', False)
            or not getattr(bot, '_opening_contact', False)
            or bot.calls < 48
            or bot.tick-getattr(bot, '_frontier_last_progress', bot.tick) < 24
            or sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) != 1):
        return
    start = len(choices)
    field = {p: 0 if p == bot.home else amount for p, amount in movable.items()}
    propose(bot, choices, field)
    for index in range(start, len(choices)):
        choices[index] = (660000.0,)+choices[index][1:]
