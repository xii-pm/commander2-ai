"""Fund and reopen a visible supply corridor to an isolated king.

No hidden road, predicted income, or remote stock is dispatched. Each proposal
is one current legal edge; a fresh observation rebuilds its complete route.
"""
from heapq import heappush, heappop
from std_geometry import KING, FORT, MARSH, BLOCKED

PRIORITY=24000
MAX_STEPS=24


def propose(bot,choices,reserves):
    goal=getattr(bot,'_single_capital_goal',None)
    if (goal is None or not getattr(bot,'_single_capital_fortress',False)
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)<2
            or bot.cells[bot.home][2]>=goal):
        return
    cells=bot.cells
    allowed={p for p,c in cells.items() if c[0] not in BLOCKED+(MARSH,)
             and (c[0]!=KING or p==bot.home)}
    # Positive costs prevent a pickup loop from being called a supply route.
    costs={bot.home:0};parent={bot.home:None};depth={bot.home:0}
    queue=[(0,bot.home)]
    while queue:
        cost,pos=heappop(queue)
        if cost!=costs[pos] or depth[pos]>=MAX_STEPS:
            continue
        c=cells[pos]
        toll=0 if c[1]==bot.army else c[2]+1
        edge=1+0.12*toll+0.02*bot.counter(pos)
        for nxt in bot.neighbors[pos]:
            if nxt not in allowed:
                continue
            new=cost+edge
            if new<costs.get(nxt,float('inf')):
                costs[nxt]=new;parent[nxt]=pos;depth[nxt]=depth[pos]+1
                heappush(queue,(new,nxt))
    records=[]
    for src in sorted(bot.owned):
        if src==bot.home or src not in parent or src in bot.protected():
            continue
        amount=min(bot.available(src),max(0,cells[src][2]-reserves.get(src,1)))
        if amount<16:
            continue
        route=[src]
        while route[-1]!=bot.home:
            route.append(parent[route[-1]])
        power=amount
        for step,dst in enumerate(route[1:],1):
            if dst==bot.home:
                break
            c=cells[dst]
            if c[1]==bot.army:
                power+=c[2]-max(1,reserves.get(dst,1))
            else:
                power-=c[2]+1+(step+1)//2 if c[0]==FORT else c[2]+1
            if power<=max(1,bot.counter(dst)):
                break
        else:
            continue
        if dst!=bot.home or power<16:
            continue
        first=route[1];c=cells[first]
        arrival=amount+c[2] if c[1]==bot.army else amount-c[2]
        if first!=bot.home and arrival<=max(1,bot.counter(first)):
            continue
        score=PRIORITY+min(4000,80*power/float(len(route)-1))
        choices.append((score,src,first,amount,'home_bank',bot.home))
        records.append(dict(route=route,dispatch=amount,arrival_stock=power,
            current_stock_only=True,reclaimed_edges=sum(cells[p][1]!=bot.army for p in route[1:])))
    if records:
        bot.last_report['fortress_corridors']=records
