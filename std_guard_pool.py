"""Pay a mature king's existing insurance before a short-warning raid arrives."""
from math import ceil
from std_merge import merge_schedule


def propose(bot, choices):
    cells, own, home = bot.cells, bot.owned, bot.home
    total = sum(cells[p][2] for p in own)
    if (sum(cells[p][0] in (2,3) for p in own) < 6 or total < 300
            or len(set(bot.known_owners)-set(bot.eliminated)) < 1
            or bot.last_report.get('defense_shortages')):
        return
    goal = min(bot.home_keep, int(ceil(total*.20)))
    need = goal-cells[home][2]
    if need < max(12, int(ceil(total*.025))):
        return
    protected = bot.protected()
    reserves = {p:max(1,bot.counter(p)+1,
        getattr(bot,'_active_reserves',{}).get(p,1)) for p in own}
    for p in protected:
        if p in own and p != home:
            reserves[p] = cells[p][2]
    plans = merge_schedule(bot.neighbors,cells,bot.army,home,reserves,8)
    plans = [row for row in plans if row[0] >= min(need,20)]
    if not plans:
        return
    funded = [row for row in plans if row[0] >= need]
    if funded:
        force,cost,moves = min(funded,key=lambda row:(row[1],row[0],row[2]))
    else:
        force,cost,moves = max(plans,key=lambda row:(row[0]/float(row[1]),row[0],-row[1],row[2]))
    src,dst,amount = moves[0]
    if dst == home:
        amount = min(amount,need)
    choices.append((14000.0+min(force,need)/float(cost),src,dst,amount,'guard_pool',home))
    bot.last_report['guard_pool'] = dict(goal=goal,shortage=need,commands=cost,
        delivered_current_stock=force,moves=moves,fully_funded=bool(funded),
        limitation='Existing observed friendly stock and roads only; replan after every command.')
