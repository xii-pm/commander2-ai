"""Concentrate a threatened single-producer empire before the last rescue hop.

This is a deliberate alternative to buying a guarded neutral fort. Existing
field stock follows current owned roads; no future dividend funds a command.
"""
from std_geometry import KING,FORT,BLANK,hex_distance

SHARE=70


def prepare(bot,reserves):
    active=getattr(bot,'_single_capital_fortress',False)
    producers=sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)
    # Concentration answers two immediate fronts while the enemy king
    # is unknown. Distant sightings alone do not justify abandoning
    # expansion or an already located king objective.
    close_owners={bot.cells[p][1] for p in bot.enemies
        if hex_distance(bot.home,p)<=4 and bot.cells[p][2]>0}
    bot.last_report['fortress_entry_context']=dict(close_owners=sorted(close_owners),
        known_king=bool(bot.kings),radius=4)
    if (not active and not bot.kings and len(close_owners)>=2
            and len(set(bot.known_owners)-set(bot.eliminated))>=2
            and (producers>=12 or producers>=4 and any(
                bot.cells[p][0]==BLANK and bot.cells[p][2]>=128
                and hex_distance(bot.home,p)<=6 for p in bot.enemies)
                or producers>=8 and any(bot.cells[p][0]==FORT
                    and bot.cells[p][2]>=64 and hex_distance(bot.home,p)<=4
                    for p in bot.enemies))
            and len(bot.owned)>=48):
        bot._single_capital_fortress=True
        active=True
        bot.last_report['mature_fortress_entry']=dict(producers=producers,
            land=len(bot.owned),close_owners=sorted(close_owners),
            basis='multiple near public fronts; enemy kings unknown')
    if not active and (not bot.kings and len(close_owners)>=2
            and len(set(bot.known_owners)-set(bot.eliminated))>=2
            and producers==1 and 12<=len(bot.owned)
            and sum(bot.cells[p][2] for p in bot.owned)<=80
            and bot.calls<=128 and not getattr(bot,'_opening_contact',False)):
        bot._single_capital_fortress=True
        active=True
    if not active:
        bot._single_capital_goal=None
        return
    total=sum(bot.cells[p][2] for p in bot.owned)
    share=SHARE if producers==1 else 40
    if 1<producers<6 and len(set(bot.known_owners)-set(bot.eliminated))>=2:
        share=max(share,70)
    if producers>=4 and bot.eliminated and len(set(bot.known_owners)-set(bot.eliminated))==1:
        from std_duel_raid_reserve import share as duel_raid_share
        share=duel_raid_share(bot,20)
    from std_connected_reserve import capital_stock
    allocation_stock=capital_stock(bot,total)
    goal=max(1,bot.home_keep,bot._connected_capital_floor,(allocation_stock*share+99)//100)
    bot._single_capital_goal=goal
    reserves[bot.home]=max(reserves.get(bot.home,1),goal)
    bot.last_report['single_capital_fortress']=dict(share=share,goal=goal,current_stock=total,
        phase='first capital' if producers==1 else 'fragile opening mature insurance')


def propose(bot,choices,reserves):
    goal=getattr(bot,'_single_capital_goal',None)
    if goal is None or bot.cells[bot.home][2]>=goal:
        return
    parent,distance=bot.owned_tree(bot.home)
    producers=sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)
    urgent=any(h<=6 for h,_ in bot.last_report.get('defense_shortages',()))
    for src in sorted(bot.owned):
        if src==bot.home or src not in parent or src in bot.protected() or distance[src]>8:
            continue
        amount=bot.available(src)
        if amount<=0:
            continue
        if 1<producers<6 and not urgent and amount<max(4,2*distance[src]):
            bot.last_report['capital_small_bank_deferred']=bot.last_report.get('capital_small_bank_deferred',0)+1
            continue
        dst=parent[src]
        if bot.cells[dst][2]+amount<=bot.counter(dst):
            continue
        # Bringing multiple otherwise stranded road stocks inward has value
        # even when one isolated donor cannot pay the complete king shortage.
        score=900+40*amount/float(distance[src])
        choices.append((score,src,dst,amount,'home_bank',bot.home))


def filter_choices(bot,choices):
    goal=getattr(bot,'_single_capital_goal',None)
    if goal is None:
        return choices
    kept=[];deferred=[]
    for row in choices:
        _,src,dst,amount,mode,target=row
        from std_adjacent_income import authorized
        from std_nearby_capital import authorized as nearby_authorized
        from std_adjacent_threat_relief import authorized as relief_authorized
        permitted=(relief_authorized(bot,src,dst,amount,mode) or src!=bot.home or mode=='finish_king' or nearby_authorized(bot,src,dst,amount,mode,target)
            or authorized(bot,src,dst,amount,mode)
            or bot.cells[src][2]-amount>=goal)
        (kept if permitted else deferred).append(row)
    if deferred:
        bot.last_report['single_capital_outflow_deferred']=deferred
    return kept
