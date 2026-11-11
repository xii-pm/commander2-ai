"""Local King security from current public sight and funded short routes.

Insurance release requires the entire passable three-ring neighborhood to
be visible now. A pessimistic independent-stack envelope supplements the
existing deadline model; departure warnings are never excluded. Unknown
armies outside this neighborhood remain a limitation of any public model.
"""
from collections import deque
from math import ceil
from std_geometry import BLANK, KING, FORT, BLOCKED

RADIUS = 3
HORIZON = 8
BUFFER = 12


def coverage(bot):
    distance = {bot.home: 0}
    queue = deque([bot.home])
    missing = []
    while queue:
        pos = queue.popleft()
        if pos not in bot.cells:
            missing.append(pos)
            continue
        if bot.cells[pos][0] in BLOCKED or distance[pos] == RADIUS:
            continue
        for nxt in bot.neighbors[pos]:
            if nxt not in distance:
                distance[nxt] = distance[pos]+1
                queue.append(nxt)
    return not missing, distance, sorted(missing)


def guard(bot):
    """Overcount separate stacks rather than sharing an opponent's budget."""
    horizon = 12 if bot.config.get('home_watch_disciplined',False) else HORIZON
    curve = bot.threat_curve(horizon)
    independent = [0] * (horizon+1)
    for pos, (kind, owner, units, seen) in bot.memory.items():
        if owner <= 0 or owner == bot.army or owner in bot.eliminated:
            continue
        age = max(0, bot.tick-seen)
        if pos not in bot.cells and age > 8:
            continue
        distance = max(1, bot.risk_dist.get(pos, 999)-age)
        for h in range(distance, horizon+1):
            growth = int(ceil((h+age)*.52)) if kind in (KING,FORT) else 0
            independent[h] += max(0, units-distance)+growth
    return max([BUFFER]+[max(curve[h], independent[h]+2)-(h-1)//2
                         for h in range(1,horizon+1)])


def release(bot, reserve):
    if not bot.config.get('home_watch_release', False):
        return reserve
    if (bot.config.get('home_watch_disciplined',False)
            and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) < 2):
        return reserve
    clear, _, missing = coverage(bot)
    floor = guard(bot) if clear else reserve
    hard = max(1,bot.config.get('base_guard',2),
               bot.config.get('contact_guard',0) if getattr(bot,'_contact_seen',False) else 0,
               getattr(bot,'_fog_guard',0) if bot.config.get('fog_memory',0) else 0,
               getattr(bot,'_conservation_keep',0) if bot.config.get('conservation_guard',False) else 0)
    value = min(reserve,max(hard,floor)) if clear else reserve
    bot._home_watch = dict(visible=clear, missing=missing, radius=RADIUS,
        previous_keep=reserve, keep=value, envelope_keep=floor, released=reserve-value)
    return value


def propose(bot, choices, reserves):
    if not bot.config.get('home_watch_clear', False):
        return
    clear, area, missing = coverage(bot)
    report = dict(visible=clear, missing=missing, radius=RADIUS, proposals=[])
    bot.last_report['home_watch'] = report
    bot.last_report['home_watch_release'] = getattr(bot, '_home_watch', None)
    screen(bot,choices,reserves,missing,report)
    disciplined = bot.config.get('home_watch_disciplined',False)
    horizon = 12 if disciplined else 6
    if disciplined and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) < 2:
        return
    if not clear or bot.pending or any(h <= horizon for h, _ in bot.last_report.get('defense_shortages', ())):
        return
    home_floor = max(bot.home_keep, guard(bot), reserves.get(bot.home,1))
    protected = bot.protected()
    targets = [p for p in bot.enemies if area.get(p,999) <= RADIUS
               and bot.cells[p][0] in (BLANK,FORT)]
    if disciplined:
        targets = [p for p in targets if area[p] == 1 or bot.cells[p][0] == FORT
                   or bot.cells[p][2] >= max(4,bot.config.get('urgent_intercept_floor',4))]
    for src in sorted(bot.owned):
        if src in protected or area.get(src,999) > RADIUS:
            continue
        parent, distance = {src:None}, {src:0}
        queue = deque([src])
        while queue:
            pos = queue.popleft()
            if distance[pos] >= RADIUS-1:
                continue
            for nxt in bot.neighbors[pos]:
                data = bot.cells.get(nxt)
                if (nxt in parent or not data or data[1] != bot.army
                        or data[0] not in (BLANK,FORT) or nxt == bot.home
                        or nxt in protected):
                    continue
                parent[nxt], distance[nxt] = pos, distance[pos]+1
                queue.append(nxt)
        for target in targets:
            keep = max(1,reserves.get(src,1))
            keep = max(keep,home_floor if src == bot.home else bot.counter(src,excluded=(target,))+1)
            cap = max(0,bot.cells[src][2]-keep)
            if cap < 2:
                continue
            for road in bot.neighbors[target]:
                if road not in parent:
                    continue
                route = bot.path(parent,road)+[target]
                steps = len(route)-1
                if disciplined and src != bot.home and steps > 1:
                    previous = getattr(bot,'_observed_pending',None)
                    if (not previous or previous['role'] != 'home_clear' or previous['dst'] != src
                            or not getattr(bot,'_last_order_confirmed',False)):
                        continue
                units = bot.cells[target][2]
                # No intermediate stock or future growth finances the route.
                required = units+2+bot.counter(target)+steps-1
                if bot.cells[target][0] == FORT:
                    required += (steps+1)//2
                # Keep every intermediate road defensible while forwarding.
                for p in route[1:-1]:
                    required += max(0,bot.counter(p)+1-bot.cells[p][2])
                if required > cap:
                    continue
                amount = min(cap,required+8)
                # Transport must be able to release the same packet on its
                # next callback. Do not dispatch onto a protected King road.
                score = 900.0 + (units+8)/float(steps) + 40*(RADIUS-area[target])
                choices.append((score,src,route[1],amount,'home_clear',target))
                report['proposals'].append(dict(src=src,target=target,route=route,
                    sent=amount,required=required,source_keep=keep))


def screen(bot, choices, reserves, missing, report):
    """Fund a small visible outpost that restores current warning sight."""
    horizon = 12 if bot.config.get('home_watch_disciplined',False) else 6
    if (bot.config.get('home_watch_disciplined',False)
            and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) < 2):
        return
    if (not bot.config.get('home_watch_screen',False) or not missing or bot.pending
            or any(h <= horizon for h,_ in bot.last_report.get('defense_shortages',()))):
        return
    gaps=set(missing)
    protected=bot.protected()
    for src in bot.owned:
        if src in protected or bot.risk_dist.get(src,999) > RADIUS:
            continue
        keep=max(1,reserves.get(src,1),bot.counter(src)+1)
        if src == bot.home:
            keep=max(keep,bot.home_keep,guard(bot))
        cap=bot.cells[src][2]-keep
        for dst in bot.neighbors[src]:
            data=bot.cells.get(dst)
            if (not data or data[0] != BLANK or data[1] != 0 or data[2] > 2
                    or bot.risk_dist.get(dst,999) > RADIUS):
                continue
            gain=len(gaps.intersection([dst]+bot.neighbors[dst]))
            if not gain:
                continue
            packet=data[2]+bot.counter(dst)+2
            if packet > cap:
                continue
            score=350+12*gain-packet*.5
            choices.append((score,src,dst,packet,'home_screen',dst))
            report.setdefault('screens',[]).append(dict(src=src,dst=dst,sent=packet,
                current_gaps_covered=gain,source_keep=keep))


# The unchanged legacy implementation above remains available for rollback.
_legacy_release=release
_legacy_propose=propose

def release(bot,reserve):
    if bot.config.get('home_watch_scoped',False):
        # Insurance is an economic policy input. Do not rewrite it globally
        # merely because a safe one-command dispatch exists this observation.
        return reserve
    return _legacy_release(bot,reserve)

def propose(bot,choices,reserves):
    if not bot.config.get('home_watch_scoped',False):
        return _legacy_propose(bot,choices,reserves)

def scoped_floor(bot):
    hard=max(1,bot.config.get('base_guard',2),
        bot.config.get('contact_guard',0) if getattr(bot,'_contact_seen',False) else 0,
        getattr(bot,'_fog_guard',0) if bot.config.get('fog_memory',0) else 0,
        getattr(bot,'_conservation_keep',0) if bot.config.get('conservation_guard',False) else 0)
    # Retain half the actual home stock and at least two thirds of the
    # established insurance. The twelve-step full threat includes the target:
    # a simultaneous rival order is not assumed erased by our capture.
    return max(hard,guard(bot),(2*bot.home_keep+2)//3,(bot.cells[bot.home][2]+1)//2)

def eligible(bot):
    if (bot.pending or bot.home is None
            or getattr(bot,'_king_recovery',None)
            or getattr(bot,'_home_sight_streak',0)<3
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)<2
            or any(h<=12 for h,_ in bot.last_report.get('defense_shortages',()))):
        return False
    return coverage(bot)[0]

def augment(bot,choices,reserves):
    bot._home_scoped_auth={}
    if not bot.config.get('home_watch_scoped',False):return
    report=dict(eligible=False,authorized=[])
    bot.last_report['home_scoped']=report
    if not eligible(bot):return
    report['eligible']=True
    floor=scoped_floor(bot)
    stock=bot.cells[bot.home][2]
    report.update(current=stock,ordinary_keep=bot.home_keep,scoped_keep=floor)
    if floor>=stock:return
    clearing_hold(bot,choices,reserves,floor,report)
    if bot.config.get('home_watch_boost',False):
        # Enlarge an existing useful friendly dispatch without adding a
        # command, direction, objective, or priority bonus. No unknown route
        # or unmade future rescue pays for this packet.
        for i,choice in enumerate(choices):
            score,src,dst,amount,mode,target=choice
            if (src!=bot.home or dst not in bot.cells or bot.cells[dst][1]!=bot.army
                    or mode in ('defend','intercept','economic_recall','guard_supply')
                    or dst==src or target==bot.home or amount<4
                    or amount<stock-reserves.get(bot.home,bot.home_keep)
                    or reserves.get(bot.home,bot.home_keep)>bot.home_keep
                    or bot.counter(dst)>=amount+bot.cells[dst][2]-1):continue
            extra=min(stock-floor-amount,stock//4,amount)
            if extra<4:continue
            sent=amount+extra
            key=(src,dst,sent,mode)
            bot._home_scoped_auth[key]=dict(keep=floor,kind='dispatch',before=amount)
            choices[i]=(score,src,dst,sent,mode,target)
            report['authorized'].append(dict(kind='dispatch',src=src,dst=dst,
                target=target,mode=mode,before=amount,sent=sent,keep=floor))
    if not bot.config.get('home_watch_sortie',False):return
    # Clearing is not a reason to borrow while the King is still below its
    # established insurance. The observed failures included 33--87-unit
    # Kings whose insurance was not yet funded, rather than idle stockpiles.
    if stock<max(64,bot.home_keep):return
    # Do not start a separate police action over a funded front operation.
    # A local capture may consume an otherwise low-value economic command.
    best=max(choices) if choices else None
    if best and (best[0]>260 or best[4] in ('finish_king','assault','tempo_king','bridge_king','investment')):return
    if bot.home in bot.protected():return
    history=getattr(bot,'_home_sortie_history',{})
    for dst in bot.neighbors[bot.home]:
        data=bot.cells.get(dst)
        if not data or data[0] not in (BLANK,FORT) or data[1] in (0,bot.army):continue
        if bot.calls-history.get((dst,data[1]),-1000)<24:continue
        units=data[2]
        if (units<=3 and best and best[4] not in ('bank','guard_supply','economic_recall')
                and not (best[1]==bot.home and best[2]==dst)):
            continue
        amount=units+bot.counter(dst)+2+(1 if data[0]==FORT else 0)
        if amount>stock-floor:continue
        score=190+min(40,units*.5)+(30 if data[0]==FORT else 0)
        key=(bot.home,dst,amount,'home_sortie')
        bot._home_scoped_auth[key]=dict(keep=floor,kind='sortie',before=0,owner=data[1])
        choices.append((score,bot.home,dst,amount,'home_sortie',dst))
        report['authorized'].append(dict(kind='sortie',src=bot.home,dst=dst,
            sent=amount,keep=floor))

def execute(bot,src,dst,count,role,commit):
    """Exact observation authorization; restore every policy reserve after commit."""
    auth=getattr(bot,'_home_scoped_auth',{}).get((src,dst,count,role))
    if (not auth or src!=bot.home or bot.pending or not eligible(bot)
            or dst not in bot.neighbors[src] or dst not in bot.cells
            or type(count) is not int or count<=0
            or bot.cells[src][2]-count<max(auth['keep'],guard(bot))):return None
    before=bot.home_keep
    active=bot._active_reserves.get(src,1)
    bot.home_keep=auth['keep'];bot._active_reserves[src]=auth['keep']
    try:move=commit()
    finally:bot.home_keep=before;bot._active_reserves[src]=active
    if move and move[2]==count:
        bot.last_report['home_scoped_commit']=dict(auth,src=src,dst=dst,sent=count,ordinary_keep=before)
        if auth['kind']=='sortie':
            if not hasattr(bot,'_home_sortie_history'):bot._home_sortie_history={}
            bot._home_sortie_history[(dst,auth['owner'])]=bot.calls
        held=bot.cells[src][2]-count
        borrowed=max(0,before-held)
        if borrowed and bot.pending:
            bot.pending['home_scoped_export']=dict(borrowed=borrowed,held=held,home=src)
    return move

def observe_export(bot):
    """Confirmed voluntary exports are not damage requiring economic recall."""
    if not bot.config.get('home_watch_scoped',False):return
    visible=bot.home is not None and coverage(bot)[0]
    bot._home_sight_streak=(getattr(bot,'_home_sight_streak',0)+1) if visible else 0
    bot.last_report['home_sight_streak']=bot._home_sight_streak
    previous=getattr(bot,'_observed_pending',None)
    export=previous.get('home_scoped_export') if previous else None
    if (not export or not getattr(bot,'_last_order_confirmed',False)
            or export['home']!=bot.home or bot.cells[bot.home][2]<export['held']
            or getattr(bot,'_king_recovery',None)):return
    old=getattr(bot,'_economic_recall_goal',bot.home_keep)
    revised=min(old,max(export['held'],old-export['borrowed']))
    bot._economic_recall_goal=revised
    bot.last_report['home_scoped_export']=dict(export,before_goal=old,after_goal=revised,
        confirmed=True,model='Only confirmed own dispatch changes economic recall; tactical deadlines remain independent.')



def clearing_hold(bot,choices,reserves,floor,report):
    """Fund the existing adjacent clearing order, without adding a command."""
    if not bot.config.get('home_watch_hold',False):return
    stock=bot.cells[bot.home][2]
    if reserves.get(bot.home,bot.home_keep)>bot.home_keep:return
    if bot.home in bot.protected():return
    for i,choice in enumerate(choices):
        score,src,dst,amount,mode,target=choice
        data=bot.cells.get(dst)
        if (src!=bot.home or dst not in bot.neighbors[src] or target!=dst
                or mode not in ('capture','intercept','advance')
                or not data or data[0] not in (BLANK,FORT)
                or data[1] in (0,bot.army) or amount<=data[2]):continue
        # Do not assume the captured stack cancels a simultaneous order.
        # Every neighboring hostile stack is priced, including same-owner
        # stacks which may reply on successive callbacks. No hidden army,
        # future friendly growth or unmade rescue funds this packet.
        replies=[bot.cells[p] for p in bot.neighbors[dst]
                 if p in bot.cells and bot.cells[p][1] not in (0,bot.army)]
        if not replies:continue
        counter=sum(max(0,c[2]-1)+(1 if c[0] in (KING,FORT) else 0) for c in replies)
        required=data[2]+counter+2+(1 if data[0]==FORT else 0)
        extra=required-amount
        if extra<2 or extra>stock//4 or required>stock-floor:continue
        key=(src,dst,required,mode)
        bot._home_scoped_auth[key]=dict(keep=floor,kind='clear_hold',before=amount,
            counter=counter,owner=data[1])
        choices[i]=(score,src,dst,required,mode,target)
        report['authorized'].append(dict(kind='clear_hold',src=src,dst=dst,target=target,
            mode=mode,before=amount,sent=required,keep=floor,counter=counter))
