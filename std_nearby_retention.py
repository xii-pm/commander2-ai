"""Retain paid first-producer garrisons through the fragile economic phase.

Only a confirmed nearby-capital or adjacent-income purchase enrolls a fort.
The home-guard handoff may expire independently; ownership, current counterforce
and the observed producer count decide when this garrison is still needed.
"""
from std_geometry import KING,FORT

def prepare(bot,reserves):
    bot._nearby_retention=None
    registry=dict(getattr(bot,'_paid_income_garrisons',{}))
    hold=getattr(bot,'_post_capital_guard',None)
    legacy=(hold and hold.get('nearby_capital') and hold.get('confirmed_capture')
        and bot.calls<=hold['until'])
    if legacy:registry.setdefault(hold['target'],dict(start=bot.calls,kind='nearby_capital'))
    order=getattr(bot,'_observed_pending',None)
    if (order and getattr(bot,'_last_order_confirmed',False)
            and order.get('role') in ('adjacent_income','relief_capital')
            and getattr(bot,'_single_capital_fortress',False)):
        registry.setdefault(order['dst'],dict(start=bot.calls,kind='adjacent_income'))
    owned=getattr(bot,'owned',set())
    fragile=(getattr(bot,'_single_capital_fortress',False)
        and sum(bot.cells[p][0] in (KING,FORT) for p in owned)<6)
    registry={p:v for p,v in registry.items() if bot.cells.get(p,(0,0,0))[:2]==(FORT,bot.army)
        and (fragile or legacy and p==hold['target'])}
    bot._paid_income_garrisons=registry
    guards=[]
    for target,record in sorted(registry.items()):
        goal=max(12,bot.counter(target)+2)
        reserves[target]=max(reserves.get(target,1),goal)
        guards.append(dict(target=target,goal=goal,stock=bot.cells[target][2],
            start=record['start'],kind=record['kind'],fragile=fragile))
    if guards:
        bot._nearby_retention=guards
        bot.last_report['nearby_capital_retention']=guards

def filter_choices(bot,choices):
    guards=getattr(bot,'_nearby_retention',None)
    if not guards:return choices
    by_target={v['target']:v for v in guards}
    urgent=any(h<=2 for h,_ in bot.last_report.get('defense_shortages',()))
    result=[];deferred=[]
    for row in choices:
        _,src,dst,amount,mode,target=row
        rescue=mode=='finish_king' or urgent and mode in ('defend','intercept')
        if (src in by_target and not rescue
                and bot.cells[src][2]-amount<by_target[src]['goal']):deferred.append(row)
        else:result.append(row)
    if deferred:bot.last_report['nearby_capital_retention_deferred']=deferred
    return result
