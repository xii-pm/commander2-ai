"""Do not pay for repeated low-value land trades against several rivals."""
from std_geometry import BLANK,KING,FORT


def filter_choices(bot,choices):
    if (not getattr(bot,'_opening_contact',False)
            or len(set(bot.known_owners)-set(bot.eliminated))<2
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)!=1
            or any(h<=6 for h,_ in bot.last_report.get('defense_shortages',()))):
        return choices
    kept=[];rejected=[]
    for row in choices:
        _,src,dst,amount,mode,target=row
        d=bot.cells.get(target)
        voluntary=(mode in ('capture','advance','intercept','road_mobilize')
            and d and d[0]==BLANK and d[1]>0 and d[1]!=bot.army
            and d[2]<=4 and bot.risk_dist.get(target,999)>2
            and not bot.new_sight(target))
        (rejected if voluntary else kept).append(row)
    if rejected:
        bot.last_report['multi_front_trades_deferred']=rejected
    return kept
