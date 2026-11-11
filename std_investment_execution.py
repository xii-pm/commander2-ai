"""A confirmed first-fort dispatch retains its economic destination."""
from std_geometry import FORT,MARSH
from std_objectives import neutral_fort_tail


def prepare(bot):
    task=getattr(bot,'_investment_column',None)
    if not task:return
    observed=getattr(bot,'_observed_pending',None)
    if task.get('pending'):
        if (observed and bot._last_order_confirmed
                and all(task['order'][k]==observed[k] for k in ('src','dst','sent','role'))):
            task.update(current=observed['dst'],pending=False,expires=bot.calls+12)
        elif bot.pending:return
        else:task=None
    if task and (bot.calls>task['expires'] or task['current'] not in bot.owned
            or bot.cells.get(task['target'],(0,bot.army,0))[1]==bot.army
            or observed and observed['src']==task['current']
                and observed['role']!='investment_route'):
        task=None
    bot._investment_column=task


def propose(bot,choices,reserves):
    bot._investment_route_options={}
    task=getattr(bot,'_investment_column',None)
    if not task or task.get('pending'):return
    src,target=task['current'],task['target']
    d=bot.cells.get(target)
    if not d or d[:2]!=(FORT,0):return
    parent,distance=bot.owned_tree(src)
    options=[]
    for root in bot.neighbors[target]:
        if distance.get(root,999)>6:continue
        route=bot.path(parent,root)+[target]
        if any(bot.cells[q][0]==MARSH for q in route):continue
        holds={q:max(1,reserves.get(q,1),bot.counter(q)+1) for q in route[:-1]}
        if bot.home in holds:holds[bot.home]=max(holds[bot.home],bot.home_keep)
        cap=min(bot.available(src),bot.cells[src][2]-holds[src])
        power=cap
        feasible=cap>0
        for q in route[1:-1]:
            power+=bot.cells[q][2]-holds[q]
            if power<=0:feasible=False
        need=d[2]+max(neutral_fort_tail(bot,target),bot.counter(target)+2)
        if not feasible or power<need:continue
        dst=route[1]
        if dst!=target and bot.cells[dst][2]+cap<=bot.counter(dst):continue
        choice=(2200.0+100.0/(len(route)-1),src,dst,cap,'investment_route',target)
        options.append(choice)
        bot._investment_route_options[choice[1:]]=dict(route=route,need=need,arrival=power)
    if options:
        choice=max(options);choices.append(choice)
        bot.last_report['investment_column']=dict(bot._investment_route_options[choice[1:]],
            current=src,target=target,confirmed=True)


def committed(bot,src,dst,amount,mode,target):
    if not bot.pending:return
    if mode=='investment' and getattr(bot,'_producer_investment',None):
        bot._investment_column=dict(target=target,current=src,expires=bot.calls+12,
            pending=True,order=dict(bot.pending))
    elif mode=='investment_route' and (src,dst,amount,mode,target) in getattr(bot,'_investment_route_options',{}):
        bot._investment_column=dict(target=target,current=src,expires=bot.calls+12,
            pending=True,order=dict(bot.pending))
