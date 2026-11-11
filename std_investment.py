"""Choose a first producer before spending all king income on small land trades.

A savings goal is not funded future income. Only current stock pays dispatch;
the ordinary arbiter retains emergency defense and immediate king captures.
"""
from math import ceil
from std_geometry import KING,FORT,MARSH
from std_objectives import neutral_fort_tail


def ordinary_capital_plan(bot):
    if (len(bot.owned)<12 or bot.pending or getattr(bot,'_investment_column',None)
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)!=1):
        return None
    parent,distance=bot.owned_tree(bot.home)
    curve=bot.threat_curve(6)
    guard=max([bot.home_keep,8,int(ceil(sum(bot.cells[p][2] for p in bot.owned)*0.35))]+
        [max(0,force-(h-1)//2) for h,force in enumerate(curve) if h])
    current=bot.cells[bot.home][2];options=[]
    for target,data in sorted(bot.cells.items()):
        if data[:2]!=(FORT,0):continue
        for gate in sorted(bot.neighbors[target]):
            if distance.get(gate,999)>5:continue
            route=bot.path(parent,gate)+[target]
            if any(bot.cells[pos][0]==MARSH or pos in bot.protected() for pos in route[:-1]):continue
            holds=sum(max(0,max(1,bot.counter(pos)+1)-bot.cells[pos][2]) for pos in route[1:-1])
            packet=data[2]+max(neutral_fort_tail(bot,target),bot.counter(target)+2)+holds
            goal=guard+packet
            if goal-current>90:continue
            info=dict(target=target,route=route,packet=packet,guard=guard,goal=goal,
                shortfall=max(0,goal-current),funded=current>=goal,road_holds=holds,
                future_growth_funds=False,model='first-producer savings from twelve owned lands')
            options.append((packet+3*(len(route)-1),len(route),target,info))
    return min(options,key=lambda item:item[:3])[3] if options else None


def plan(bot):
    proposal = ordinary_capital_plan(bot)
    entry = getattr(bot,'_surveyed_adjacent_capital',None)
    first_quote = bool(proposal and not getattr(bot,'_capital_quote_observed',False))
    if proposal:
        bot._capital_quote_observed = True
    if (entry is None and first_quote and bot.calls <= 64 and proposal
            and len(proposal['route']) == 2 and proposal['packet'] <= 60):
        entry = dict(target=proposal['target'],packet=proposal['packet'],entered=bot.calls,
            reason='early adjacent neutral fort has a surveyed affordable packet; policy entry only')
        bot._surveyed_adjacent_capital = entry
    if entry:
        bot.last_report['surveyed_adjacent_capital'] = entry
    return proposal if entry else None


def propose(bot,choices,investment):
    if not investment:return
    if investment['funded']:
        choices.append((2300.0+100.0/(len(investment['route'])-1),bot.home,
            investment['route'][1],investment['packet'],'investment',investment['target']))
        return
    parent,distance=bot.owned_tree(bot.home);options=[]
    for src in sorted(bot.owned):
        steps=distance.get(src,999)
        if not 0<steps<=6 or src in bot.protected():continue
        movable=bot.cells[src][2]-max(1,bot.counter(src)+1,bot.cells[src][2]-bot.available(src))
        route=bot.path(parent,src)
        cost=sum(max(0,bot.counter(pos)+1-bot.cells[pos][2]) for pos in route[1:-1])
        useful=min(investment['shortfall'],movable-cost)
        if useful<steps:continue
        amount=min(movable,investment['shortfall']+cost)
        options.append((400.0+useful/float(steps),src,parent[src],amount,'capital_pool',bot.home))
    if options:
        best=max(options);choices.append(best)
        bot.last_report['opening_capital_pool']=dict(proposal=best,goal=investment['goal'],
            shortfall=investment['shortfall'],current_stock_only=True)
