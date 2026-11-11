"""Current-funded first-fort convoys with an observed command sequence.

Only a fully paid collection and capture is proposed. Tactical defense can
interrupt it; every suffix is repriced against the next legal observation.
"""
from math import ceil

from std_geometry import KING, FORT, MARSH, hex_distance
from std_merge import merge_schedule


def prepare(bot):
    bot._fort_convoy_option = None
    active = getattr(bot, '_fort_convoy', None)
    if not bot.config.get('first_fort_convoy', False):
        bot._fort_convoy = None
        return
    if active and active['awaiting']:
        observed = getattr(bot, '_observed_pending', None)
        if (observed and (observed['src'],observed['dst'],observed['sent']) == active['moves'][0]
                and getattr(bot, '_last_order_confirmed', False)):
            active['moves'] = active['moves'][1:]
            active['awaiting'] = False
        elif bot.pending:
            return
        else:
            active = None
    if active and (not active['moves'] or bot.tick >= active['expires']):
        active = None
    bot._fort_convoy = active


def capture_need(bot, target):
    data = bot.cells.get(target)
    if not data or data[0] != FORT or data[1] != 0:
        return None
    counter = int(ceil(bot.counter(target)*bot.config.get('counter_margin',100)/100.0))
    return data[2]+max(1,counter+1)


def funded(bot, moves, reserves, target):
    """Reprice the final capture and fund every prefix from current units."""
    need = capture_need(bot,target)
    if not moves or need is None or moves[-1][1] != target:
        return None
    src,_,_ = moves[-1]
    moves = tuple(moves[:-1])+((src,target,need),)
    units = {p:bot.cells[p][2] for p in bot.owned}
    for i,(src,dst,amount) in enumerate(moves):
        keep = max(1,reserves.get(src,1),bot.home_keep if src == bot.home else 1)
        if (src not in units or dst not in bot.neighbors[src]
                or dst not in bot.cells or bot.cells[src][0] == MARSH
                or bot.cells[dst][0] == MARSH
                or amount <= 0 or amount > units[src]-keep):
            return None
        units[src] -= amount
        if dst == target:
            if i != len(moves)-1:
                return None
        elif dst in units:
            units[dst] += amount
        else:
            return None
    return moves


def plan(bot,reserves):
    budget = bot.config.get('first_fort_commands',16)
    reserves = dict(reserves)
    if bot.config.get('first_fort_preserve_home',False):
        # Protect the king's currently held capital for this long project.
        # Later observed inflows may pass through it above this fixed floor.
        reserves[bot.home] = max(reserves.get(bot.home,1),bot.cells[bot.home][2])
    usable = {p:d for p,d in bot.cells.items() if d[0] != MARSH}
    targets = sorted((p for p,d in bot.cells.items() if d[:2] == (FORT,0)),
                     key=lambda p:(bot.cells[p][2],hex_distance(bot.home,p),p))[:4]
    options = []
    for target in targets:
        need = capture_need(bot,target)
        roots = sorted((p for p in bot.neighbors[target]
                        if p in bot.owned and p in usable),
                       key=lambda p:(-(bot.cells[p][2]-reserves.get(p,1)),p))[:3]
        for root in roots:
            ready = max(0,bot.cells[root][2]-reserves.get(root,1))
            sequences = [()] if ready >= need else [moves for force,_,moves in
                merge_schedule(bot.neighbors,usable,bot.army,root,reserves,budget-1)
                if force+ready >= need]
            for sequence in sequences:
                moves = funded(bot,tuple(sequence)+((root,target,need),),reserves,target)
                if moves:
                    options.append((len(moves),need,target,root,moves))
    if not options:
        return None
    _,need,target,root,moves = min(options)
    return dict(target=target,root=root,moves=moves,
                expires=bot.tick+2*budget+4,awaiting=False,initial_need=need,
                home_floor=reserves.get(bot.home,bot.home_keep))


def propose(bot,choices,reserves):
    if not bot.config.get('first_fort_convoy',False):
        return
    if (sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) != 1
            or getattr(bot,'_opening_contact',False)
            or any(h <= 6 for h,_ in bot.last_report.get('defense_shortages',[]))):
        bot._fort_convoy = None
        return
    active = getattr(bot,'_fort_convoy',None)
    if active and active['awaiting']:
        return
    if active:
        protected = dict(reserves)
        if bot.config.get('first_fort_preserve_home',False):
            protected[bot.home] = max(protected.get(bot.home,1),active['home_floor'])
        moves = funded(bot,active['moves'],protected,active['target'])
        if moves is None:
            bot._fort_convoy = None
            return
        option = dict(active,moves=moves)
    else:
        option = plan(bot,reserves)
        if not option:
            return
    bot._fort_convoy_option = option
    first = option['moves'][0]
    score = 400+30.0/len(option['moves'])
    choices.append((score,first[0],first[1],first[2],'fort_convoy',option['target']))
    bot.last_report['first_fort_convoy'] = dict(target=option['target'],root=option['root'],
        commands=len(option['moves']),moves=option['moves'],continuing=bool(active),
        home_floor=option['home_floor'],
        expires=option['expires'],model='Current-stock sequence; no future growth; suffix repriced every observation.')


def committed(bot,src,dst,amount,mode):
    option = getattr(bot,'_fort_convoy_option',None)
    if option and mode == 'fort_convoy' and (src,dst,amount) == option['moves'][0]:
        bot._fort_convoy = dict(option,awaiting=True)
    elif getattr(bot,'_fort_convoy',None):
        bot._fort_convoy = None
