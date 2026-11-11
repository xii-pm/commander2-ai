"""One executable rescue proposal in the existing deadline-defense family.

Current friendly stock, one command per step, no hidden troops or income
credit. Child branches merge before their shared trunk is forwarded. The
schedule is evidence for selecting this first order, never a mission lock:
the ordinary arbiter rechecks the next public observation and interceptions.
"""
from std_merge import merge_schedule


def proposal(bot, curve, deadlines=None):
    home_units = bot.cells[bot.home][2]
    if deadlines is None:
        deadlines = [(h, force-home_units-h//2) for h,force in enumerate(curve)
                     if h and force > home_units+h//2]
    if not deadlines:
        return None
    horizon = len(curve)-1
    # Timed king survival uses the same emergency hold of one as the
    # inherited deadline defense. Economic recall keeps its separate ledger.
    holds = {p:1 for p in bot.owned}
    plans = merge_schedule(bot.neighbors,bot.cells,bot.army,bot.home,holds,horizon)
    # Preserve a packet needed before a later branch can join its relay.
    # Enumerate at most the six adjacent first deliveries, then use the same
    # bounded tree collector on the resulting actual stock. A relay may thus
    # forward again after its child arrives; no factorial FIFO enumeration.
    for relay in bot.neighbors[bot.home]:
        if relay not in holds or bot.cells[relay][2] <= 1:
            continue
        amount = bot.cells[relay][2]-1
        first = ((relay,bot.home,amount),)
        cells = dict(bot.cells)
        cells[relay] = cells[relay][:2]+(1,)
        cells[bot.home] = cells[bot.home][:2]+(home_units+amount,)
        plans.append((amount,1,first))
        for force,cost,moves in merge_schedule(bot.neighbors,cells,bot.army,
                bot.home,holds,horizon-1):
            plans.append((amount+force,cost+1,first+moves))
    best = None
    alternatives = []
    for force,cost,moves in plans:
        stock = {p:bot.cells[p][2] for p in bot.owned}
        arrivals, delivered = [0], 0
        legal = True
        for src,dst,amount in moves:
            if (src == bot.home or amount <= 0 or src not in stock or dst not in stock
                    or dst not in bot.neighbors[src] or amount > stock[src]-1):
                legal = False
                break
            stock[src] -= amount
            stock[dst] += amount
            if dst == bot.home:
                delivered += amount
            arrivals.append(delivered)
        if not legal:
            continue
        arrivals += [delivered]*(horizon+1-len(arrivals))
        # Earlier survival deadlines dominate later stock. A large convoy
        # arriving after a fatal earlier shortage does not count as cover.
        coverage = tuple(min(need,arrivals[h]) for h,need in deadlines)
        if not any(coverage):
            continue
        if bot.config.get('rescue_triage', False):
            alternatives.append((force,cost,moves,arrivals))
        rank = coverage, -cost, force, moves
        if best is None or rank > best[0]:
            best = rank, moves, arrivals
    if best is None:
        return None
    selected_deadline = deadlines[0][0]
    shortfall_alternatives = list(alternatives)
    if alternatives:
        # If no current joint schedule can cover the earliest gap, repeatedly
        # sending its tiny partial maximum can starve every remote rescue.
        # Prefer the earliest later deadline with an actually funded schedule.
        # Earlier unfunded gaps remain reported; this is triage, not proof of
        # surviving a rival who immediately takes the shortest attack route.
        immediate = [(h,min(need,best[2][h])) for h,need in deadlines if h <= 3]
        alternatives = [plan for plan in alternatives
                        if all(plan[3][h] >= cover for h,cover in immediate)]
        funded = [h for h,need in deadlines
                  if any(arrivals[h] >= need for _,_,_,arrivals in alternatives)]
        if funded and min(funded) > selected_deadline:
            selected_deadline = min(funded)
            effective = [(h,need) for h,need in deadlines if h >= selected_deadline]
            best = max((
                (tuple(min(need,arrivals[h]) for h,need in effective),-cost,force,moves),
                moves,arrivals) for force,cost,moves,arrivals in alternatives)
    from std_rescue_utility import select as select_shortfall
    best = select_shortfall(bot,shortfall_alternatives,deadlines,best,True)
    _,moves,arrivals = best
    if (bot.config.get('pareto_rescue',False) and deadlines[0][0] <= 4
            and not all(arrivals[h] >= need for h,need in deadlines)):
        from std_security import schedules, arrival_curve
        original_arrivals = list(arrivals)
        original_coverage = tuple(min(need,arrivals[h]) for h,need in deadlines)
        upgrades = []
        plans = schedules(bot.neighbors,bot.cells,bot.army,bot.home,4)
        for plan in plans:
            if not plan:
                continue
            offered = list(arrival_curve(plan,bot.home,horizon))
            coverage = tuple(min(need,offered[h]) for h,need in deadlines)
            if (all(a >= b for a,b in zip(offered,original_arrivals))
                    and (coverage > original_coverage or (
                        original_arrivals[deadlines[0][0]] < deadlines[0][1]
                        and offered != original_arrivals))):
                upgrades.append((coverage,tuple(offered),-len(plan),plan,offered))
        if upgrades:
            _,_,_,moves,arrivals = max(upgrades)
            funded = [h for h,need in deadlines if arrivals[h] >= need]
            if funded:
                selected_deadline = min(funded)
            bot.last_report['pareto_rescue'] = dict(moves=moves,arrival_curve=arrivals,
                original_arrival_curve=original_arrivals,horizon=4,plans=len(plans),
                relation='No less current-stock delivery at every original deadline; '
                         'stronger shortage coverage or earlier partial rescue when the first gap '
                         'cannot be funded. No enemy-cut guarantee.')
    h,need = deadlines[0]
    src,dst,amount = moves[0]
    base = 12000 if bot.config.get('stable_commitment',False) and h <= 6 else 10000
    score = base+1000.0/(h+1)+min(need,arrivals[h])/float(len(moves))
    bot.last_report['deadline_convoy'] = dict(deadlines=deadlines,moves=moves,
        arrival_curve=arrivals,commands=len(moves),all_deadlines_funded=all(
            arrivals[t] >= gap for t,gap in deadlines),first_source=src,
        selected_deadline=selected_deadline,
        deferred_unfunded_deadlines=[h for h,_ in deadlines if h < selected_deadline],
        model='Current observed friendly tree and stock; no growth or enemy-cut guarantee.')
    return score,src,dst,amount,'defend',bot.home
