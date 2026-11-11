"""Prevent ordinary supply from closing a recently confirmed friendly path.

This is a bounded route history, not an estimate of soldier identity. Combat,
ownership changes, producer objectives and king rescue retain their policies.
Observation happens once, before the opening-policy transaction previews.
"""
from std_geometry import BLANK,KING,FORT

ROLES=('supply','advance')
AGE=12
LIMIT=8

def in_stage(bot):
    return (getattr(bot,'_single_capital_fortress',False) and not bot.kings
        and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)==1)

def observe(bot):
    if not in_stage(bot):
        bot._transport_paths=[]
        return
    paths=[v for v in getattr(bot,'_transport_paths',[])
        if bot.calls-v['start']<=AGE
        and all(bot.cells.get(p,(0,0,0))[1]==bot.army for p in v['path'])]
    order=getattr(bot,'_observed_pending',None)
    if not order:
        bot._transport_paths=paths
        return
    src=order['src'];dst=order['dst'];role=order.get('role')
    matches=[v for v in paths if v['path'][-1]==src]
    paths=[v for v in paths if v['path'][-1]!=src]
    if (getattr(bot,'_last_order_confirmed',False) and role in ROLES
            and bot.cells.get(src,(0,0,0))[1]==bot.army
            and bot.cells.get(dst,(0,0,0))[1]==bot.army):
        extended=[dict(start=v['start'],path=v['path']+[dst],
            confirmations=v['confirmations']+1) for v in matches
            if dst not in v['path'] and len(v['path'])<LIMIT]
        paths.extend(extended)
        paths.append(dict(start=bot.calls,path=[src,dst],confirmations=1))
    # Multiple packets may share a road; keep bounded witnesses, never one
    # global target that could force an unrelated army onto another's route.
    bot._transport_paths=paths[-32:]

def filter_choices(bot,choices):
    if not in_stage(bot):return choices
    if any(h<=2 for h,_ in bot.last_report.get('defense_shortages',())):return choices
    paths=getattr(bot,'_transport_paths',[])
    kept=[];rejected=[]
    for row in choices:
        _,src,dst,amount,mode,target=row
        closes=next((v for v in paths if v['path'][-1]==src
            and dst in v['path'][:-1] and v['confirmations']>=2),None)
        if (mode in ROLES and closes
                and bot.cells.get(dst,(0,0,0))[1]==bot.army
                and bot.cells.get(target,(0,0,0))[0]==BLANK):
            rejected.append(dict(proposal=row,path=closes))
        else:kept.append(row)
    bot.last_report['transport_path_guard']=dict(rejected=rejected,
        paths=paths,basis='confirmed friendly route; ordinary single-producer transport only')
    return kept
