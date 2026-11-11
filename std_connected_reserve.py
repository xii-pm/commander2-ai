"""Do not demand disconnected soldiers at a persistently cut-off king."""
from std_geometry import KING,FORT

def capital_stock(bot,total):
    bot._connected_capital_floor=1
    source=bot.home
    if (bot.cells[source][2]<128
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)!=1):
        bot._capital_cut_since=None
        return total
    owned=set(bot.owned);component={source};front=[source]
    while front:
        pos=front.pop()
        for nxt in bot.neighbors[pos]:
            if nxt in owned and nxt not in component:
                component.add(nxt);front.append(nxt)
    if len(component)>3 or len(component)==len(owned):
        bot._capital_cut_since=None
        return total
    since=getattr(bot,'_capital_cut_since',None)
    if since is None:since=bot.calls;bot._capital_cut_since=since
    if bot.calls-since<12:return total
    reachable=sum(bot.cells[p][2] for p in component)
    bot._connected_capital_floor=max(bot.home_keep,max(bot.threat_curve(12))+24)
    bot.last_report['connected_capital_budget']=dict(total=total,reachable=reachable,
        disconnected=total-reachable,component=sorted(component),since=since,
        full_threat_floor=bot._connected_capital_floor,
        basis='only current friendly connected stock can satisfy king concentration; ordinary threat floor remains')
    return reachable
