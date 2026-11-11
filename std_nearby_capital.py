"""Fund a short first-capital route through currently visible ordinary roads.

Every hop is repriced from actual stock. No hidden road, future growth or
unmade merge pays for a dispatch. Original full king threats remain charged.
"""
from std_geometry import BLANK,KING,FORT
from std_objectives import neutral_fort_tail

LIMIT=3
ALLOW_ENEMY=True

def is_target(bot,cell):
    return bool(cell and cell[0]==FORT and (cell[1]==0 or ALLOW_ENEMY
        and cell[1]>0 and cell[1]!=bot.army and cell[1] not in getattr(bot,'eliminated',())))

def prepare(bot):
    task=getattr(bot,'_nearby_capital_task',None)
    if not task:return
    old=getattr(bot,'_observed_pending',None)
    if bot.calls>task['expires']:
        task=None
    if task and task.get('pending'):
        if (old and getattr(bot,'_last_order_confirmed',False)
                and all(old.get(k)==task['order'].get(k) for k in ('src','dst','sent','role'))):
            task.update(current=old['dst'],pending=False,expires=bot.calls+12)
        elif bot.pending:return
        else:task=None
    if task:
        cell=bot.cells.get(task['target'])
        if cell and cell[:2]==(FORT,bot.army) and task['current']==task['target']:
            bot._post_capital_guard=dict(target=task['target'],guard=task['home_guard'],
                until=bot.calls+24,confirmed_capture=True,nearby_capital=True)
            bot.last_report['nearby_capital_acquired']=dict(task)
            task=None
        elif (bot.calls>task['expires'] or task['current'] not in bot.owned
                or not is_target(bot,cell) or cell[1]!=task.get('target_owner',0)
                or old and old.get('src')==task['current'] and old.get('role')!='nearby_capital'):
            task=None
    if task:
        bot._post_capital_guard=dict(target=task['target'],guard=task['home_guard'],
            until=task['expires'],confirmed_capture=False,nearby_capital=True)
    elif getattr(bot,'_post_capital_guard',{}):
        guard=bot._post_capital_guard
        if guard.get('nearby_capital') and not guard.get('confirmed_capture'):
            bot._post_capital_guard=None
    bot._nearby_capital_task=task

def routes(bot,source,targets,limit=LIMIT):
    stack=[(source,[source])]
    while stack:
        pos,path=stack.pop()
        if len(path)-1>=limit:continue
        for dst in sorted(bot.neighbors[pos],reverse=True):
            data=bot.cells.get(dst)
            if dst in path or not data:continue
            route=path+[dst]
            if dst in targets and is_target(bot,data):yield route
            elif data[0]==BLANK:stack.append((dst,route))

def quote(bot,route,reserves):
    target=route[-1];data=bot.cells[target]
    need=data[2]+max(12,neutral_fort_tail(bot,target),bot.counter(target)+2)
    # An enemy producer can grow on every command of this short march. The
    # quoted payload prepays that conservative bound from current inventory.
    if data[1]>0:need+=len(route)-1
    holds=[]
    # Keep enough stock at each intermediate cell to withstand currently
    # visible counterforce before the next decision. Friendly stock is not
    # counted as a promised pickup before this command actually arrives.
    for pos in reversed(route[1:-1]):
        cell=bot.cells[pos]
        keep=max(1,reserves.get(pos,1),bot.counter(pos)+1)
        holds.append(dict(pos=pos,keep=keep))
        need+=keep+(cell[2] if cell[1]!=bot.army else 0)
    return need,holds

def propose(bot,choices,reserves):
    bot._nearby_capital_auth={}
    task=getattr(bot,'_nearby_capital_task',None)
    if task and task.get('pending'):return
    if (not task and (not getattr(bot,'_single_capital_fortress',False)
            or not 1<=sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)<6
            or bot.cells[bot.home][2]<64)):
        return
    if bot.pending or any(h<=6 for h,_ in bot.last_report.get('defense_shortages',())):return
    source=task['current'] if task else bot.home
    if source not in bot.owned or source in bot.protected():return
    if task:targets={task['target']}
    else:
        attempts=getattr(bot,'_nearby_enemy_attempts',{})
        adjacent=getattr(bot,'_adjacent_income_history',{})
        targets={p for p,c in bot.cells.items() if is_target(bot,c) and (c[1]==0
            or bot.calls-max([attempts.get(p,-1000)]+[t for (q,_),t in adjacent.items() if q==p])>=24)}
    stock=bot.cells[source][2]
    if source==bot.home:
        floor=max(24,bot.home_keep,max(bot.threat_curve(12))+24)
    else:
        floor=max(1,reserves.get(source,1),bot.counter(source)+1)
    cap=stock-floor
    options=[]
    for route in routes(bot,source,targets,task['remaining'] if task else LIMIT):
        if any(pos in bot.protected() for pos in route[1:]):continue
        amount,holds=quote(bot,route,reserves)
        if amount>cap:continue
        target=route[-1];dst=route[1]
        # A confirmed and freshly affordable march finishes before banking.
        # The six-step defense veto above still cancels this priority.
        score=(600000.0 if task else 2350.0)+100.0/(len(route)-1)
        choice=(score,source,dst,amount,'nearby_capital',target)
        auth=dict(route=route,keep=floor,road_holds=holds,target=target,
            home_guard=task['home_guard'] if task else floor,
            destination=bot.cells[dst],current_stock_only=True,target_owner=bot.cells[target][1])
        bot._nearby_capital_auth[choice[1:]]=auth
        options.append(choice)
    if options:
        best=max(options);choices.append(best)
        bot.last_report['nearby_capital']=dict(bot._nearby_capital_auth[best[1:]],
            source=source,sent=best[3],continuing=bool(task))

def authorized(bot,src,dst,amount,mode,target=None):
    if mode!='nearby_capital':return None
    return next((v for k,v in getattr(bot,'_nearby_capital_auth',{}).items()
        if k[:4]==(src,dst,amount,mode) and (target is None or k[4]==target)),None)

def execute(bot,src,dst,amount,mode,commit):
    auth=authorized(bot,src,dst,amount,mode)
    if (not auth or bot.pending or src not in bot.owned
            or dst not in bot.neighbors[src] or bot.cells.get(dst)!=auth['destination']
            or bot.cells[src][2]-amount<auth['keep']):return None
    before=bot.home_keep;active=bot._active_reserves.get(src,1)
    if src==bot.home:bot.home_keep=auth['keep']
    bot._active_reserves[src]=auth['keep']
    try:return commit()
    finally:bot.home_keep=before;bot._active_reserves[src]=active

def committed(bot,src,dst,amount,mode,target):
    auth=authorized(bot,src,dst,amount,mode,target)
    if not auth or not bot.pending or bot.pending.get('role')!=mode:return
    bot._nearby_capital_task=dict(target=target,current=src,home_guard=auth['home_guard'],
        pending=True,order=dict(bot.pending),expires=bot.calls+12,remaining=len(auth['route'])-2,
        target_owner=auth['target_owner'])
    if auth['target_owner']>0 and src==bot.home:
        history=getattr(bot,'_nearby_enemy_attempts',{})
        history[target]=bot.calls;bot._nearby_enemy_attempts=history
    bot._post_capital_guard=dict(target=target,guard=auth['home_guard'],
        until=bot.calls+12,confirmed_capture=False,nearby_capital=True)
    bot.last_report['nearby_capital_commit']=dict(source=src,destination=dst,
        target=target,sent=amount,keep=auth['keep'])
