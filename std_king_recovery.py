"""Bounded replenishment after observed king combat, using current stock only."""
from std_geometry import KING
from std_merge import merge_schedule


def observe(bot, previous, order):
    if not bot.config.get('post_battle_recovery', False):
        return
    home = bot.home
    task = getattr(bot, '_king_recovery', None)
    if not home:
        bot._king_recovery = None
        return
    if task and (bot.calls >= task['expires'] or task['home'] != home):
        task = None
    before, current = previous.get(home), bot.cells[home][2]
    if before and before[:2] == (KING, bot.army):
        outgoing = order['sent'] if order and order['src'] == home else 0
        incoming = (order['sent'] if order and order['dst'] == home
                    and getattr(bot, '_last_order_confirmed', False) else 0)
        # Deduct our own dispatch; confirmed friendly arrival can mask damage.
        # Ignoring producer growth underestimates combat loss by at most one
        # on a normal callback, rather than inventing a hidden hostile packet.
        stationed = max(0, before[2]-outgoing)
        garrison_loss = max(0, stationed+incoming-current)
        sortie_loss = 0
        if outgoing and order.get('role') == 'intercept':
            defended = previous.get(order['dst'])
            after = bot.cells.get(order['dst'])
            # A defensive sortie can spend the king's army without changing
            # its stationary garrison. Require the visible source deduction;
            # surviving troops on a friendly destination are not combat loss.
            if (defended and defended[1] not in (0, bot.army)
                    and after and before[2]-current >= outgoing-1):
                survivors = after[2] if after[1] == bot.army else 0
                sortie_loss = min(defended[2]+1,max(0,outgoing-survivors))
        lost = garrison_loss+sortie_loss
        stationed += sortie_loss
        producers = bot.last_report.get('objective_state', {}).get('owned_producers', 0)
        # A small successful sortie does not justify diverting a long convoy.
        # Direct king damage keeps the earlier trigger; a voluntary intercept
        # must spend at least half its pre-combat defensive strength.
        threshold = (stationed+1)//2 if sortie_loss and not garrison_loss else stationed//3
        if lost >= max(32, threshold) and producers >= 3:
            # A contested friendly arrival cannot pass exact transfer checks.
            # Restore the observed pre-combat garrison even when that arrival
            # is unconfirmed; never exceed the existing defensive insurance.
            goal = min(bot.home_keep, max(32, stationed, current+lost//2))
            if goal > current:
                task = dict(home=home,goal=max(goal,task['goal'] if task else 0),
                    expires=bot.calls+18,born=bot.calls,observed_loss=lost,
                    garrison_loss=garrison_loss,sortie_loss=sortie_loss)
    bot._king_recovery = task
    if task:
        # This temporary hold is independent of the ordinary safe-ring release.
        # It expires on legal callbacks and never renews from income or dispatch.
        bot.home_keep = max(bot.home_keep,task['goal'])
        bot.last_report['home_keep'] = bot.home_keep
        bot.last_report['home_guard_floor'] = max(bot.home_keep,bot.home_guard_hold())
        bot.last_report['king_recovery'] = dict(task,held=current,
            remaining=task['expires']-bot.calls)


def propose(bot, choices, reserves):
    task = getattr(bot, '_king_recovery', None)
    if not task or bot.last_report.get('defense_shortages'):
        return
    gap = task['goal']-bot.cells[bot.home][2]
    budget = min(12,task['expires']-bot.calls)
    if gap <= 0 or budget <= 0:
        return
    # Economic recovery cannot empty a visibly exposed fort or unsafe relay.
    holds = {p:max(1,reserves.get(p,1),bot.fort_reserves.get(p,1),bot.counter(p)+1)
             for p in bot.owned}
    plans = merge_schedule(bot.neighbors,bot.cells,bot.army,bot.home,holds,budget)
    if not plans:
        return
    funded = [plan for plan in plans if plan[0] >= gap]
    if funded:
        force,cost,moves = min(funded,key=lambda p:(p[1],-p[0],p[2]))
    else:
        force,cost,moves = max(plans,key=lambda p:(p[0]/float(p[1]),p[0],-p[1],p[2]))
    src,dst,amount = moves[0]
    parent,_ = bot.owned_tree(bot.home)
    path = bot.path(parent,src)
    deficit = sum(max(0,holds[p]-bot.cells[p][2]) for p in path[1:-1])
    amount = min(amount,gap+deficit)
    if amount <= 0:
        return
    bot.last_report['king_recovery_plan'] = dict(goal=task['goal'],gap=gap,
        force=force,commands=cost,moves=moves,first_packet=amount,
        funded=force >= gap,budget=budget,
        model='Current friendly stock and safe holds; re-evaluate after each order.')
    choices.append((1600+min(gap,force)/float(cost),src,dst,amount,'king_recovery',bot.home))
