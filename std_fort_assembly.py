"""Fund a fort capture by merging public current stock on an owned tree.

Each table entry contains a fully funded postorder schedule. Only its first
command is offered; new observations rebuild troop balances and all routes.
Enemy actions and future income can invalidate a later command, so this is an
economic proposal, never a survival guarantee or a reserved future dispatch.
"""
from collections import deque
from std_geometry import KING, FORT, MARSH
from std_objectives import neutral_fort_tail


def collect(bot, root, reserves, budget=24):
    blocked = bot.protected()
    allowed = {p for p in bot.owned if p not in blocked and bot.cells[p][0] != MARSH}
    if root not in allowed:
        return {}
    distance, parent, queue = {root:0}, {}, deque([root])
    while queue:
        pos = queue.popleft()
        if distance[pos] >= min(10,budget):
            continue
        for nxt in sorted(bot.neighbors[pos]):
            if nxt in allowed and nxt not in distance:
                distance[nxt], parent[nxt] = distance[pos]+1,pos
                queue.append(nxt)
    children = {p:[] for p in distance}
    for pos,prior in parent.items():
        children[prior].append(pos)
    tables = {}
    for pos in sorted(distance,key=lambda p:(-distance[p],p)):
        keep = max(1,reserves.get(pos,1),bot.cells[pos][2]-bot.available(pos),bot.counter(pos)+1)
        base = bot.cells[pos][2]-keep
        table = {0:(base,())}
        for child in sorted(children[pos]):
            merged = dict(table)
            for cost,(power,orders) in table.items():
                for child_cost,(gain,child_orders) in tables[child].items():
                    total_cost = cost+child_cost+1
                    if total_cost > budget or gain <= 0:
                        continue
                    proposal = (power+gain,orders+child_orders+((child,pos,gain),))
                    if total_cost not in merged or proposal > merged[total_cost]:
                        merged[total_cost] = proposal
            table = merged
        # A greater cost with no greater delivered force is dominated.
        best = -float('inf')
        tables[pos] = {}
        for cost in sorted(table):
            if table[cost][0] > best:
                tables[pos][cost] = table[cost]
                best = table[cost][0]
    def schedule(orders):
        # Independent branches can execute in any order; shared
        # trunks must wait for every selected incoming child. Move
        # the largest useful payload per remaining edge first.
        pending = list(orders)
        arranged = []
        while pending:
            incoming = {dst for src,dst,amount in pending}
            ready = [move for move in pending if move[0] not in incoming]
            first = max(ready,key=lambda move:(move[2]/float(distance[move[0]]),move))
            arranged.append(first)
            pending.remove(first)
        return tuple(arranged)
    return {cost:(power,schedule(orders)) for cost,(power,orders) in tables[root].items()}


def propose(bot,choices,reserves):
    producers = sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)
    rivals = set(getattr(bot,'known_owners',()))-set(getattr(bot,'eliminated',()))
    if producers==2 and not hasattr(bot,'_income_bridge_context'):
        bot._income_bridge_context=dict(spread=len(bot.owned)>=64,
            observed_at=bot.calls,land_at_handoff=len(bot.owned))
    if hasattr(bot,'_income_bridge_context'):
        bot.last_report['income_bridge_context']=dict(bot._income_bridge_context)
    if (producers==2 and bot._income_bridge_context['spread'] and len(rivals)<3
            and not getattr(bot,'_single_capital_fortress',False)
            and not getattr(bot,'_opening_contact',False)):
        bot.last_report['second_assembly_deferred']='ordinary expansion retains command priority'
        return
    if len(rivals) < 2:
        return
    # An unexposed home can currently have a one-soldier economic
    # hold. A sunk fort army cannot promise to return through fog.
    reserves = dict(reserves)
    total = sum(bot.cells[p][2] for p in bot.owned)
    reserves[bot.home] = max(reserves.get(bot.home,1),
        (total*bot.config.get('guard_share',18)+99)//100)
    continuing = (producers == 3 and bot.calls <= getattr(bot,'_assembly_bridge_until',-1))
    if (producers not in (1,2) and not continuing or len(getattr(bot,'known_owners',())) < 2
            or len(bot.owned) < 8 or bot.pending):
        return
    options = []
    certificates = {}
    for target,data in sorted(bot.cells.items()):
        if data[0] != FORT or data[1] == bot.army:
            continue
        gates = [p for p in bot.neighbors[target] if p in bot.owned]
        for gate in sorted(gates):
            for cost,(power,orders) in collect(bot,gate,reserves).items():
                commands = cost+1
                tail = max(neutral_fort_tail(bot,target),bot.counter(target)+2)
                growth = commands if data[1] > 0 else 0
                needed = data[2]+tail+growth
                if power < needed:
                    continue
                first = orders[0] if orders else (gate,target,needed)
                src,dst,amount = first
                if not (0 < amount <= bot.available(src) and dst in bot.neighbors[src]):
                    continue
                # Friendly collection must remain useful after explicit holds;
                # capture execution is independently checked by the arbiter.
                # A long tree is an investment competing with every
                # capture and march. Charge its full command cost
                # instead of granting all funded trees priority.
                score = (bot.config.get('production_value',600)*.9
                    /float(1+.25*commands)+min(12.0,power-needed)
                    +3*len(bot.new_sight(target)))
                row = (score,src,dst,amount,'fort_assembly',target)
                options.append(row)
                certificates[row] = dict(orders=orders+((gate,target,needed),),target=target)

    if options and producers == 1 and not getattr(bot,'_early_fort_survey_started',False):
        if not hasattr(bot,'_quiet_assembly_quote'):
            bot._quiet_assembly_quote = dict(allowed=(len(bot.owned)>=64
                and not getattr(bot,'_opening_contact',False)
                and not any(bot.threat_curve(12))), observed_at=bot.calls)
        bot.last_report['quiet_assembly_entry'] = dict(bot._quiet_assembly_quote)
        if not bot._quiet_assembly_quote['allowed']:
            return
    if options:
        best = max(options)
        choices.append(best)
        certificate = certificates[best]
        certificate['holds'] = [(p,max(1,reserves.get(p,1),
            bot.cells[p][2]-bot.available(p),bot.counter(p)+1))
            for p in sorted({o[0] for o in certificate['orders']})]

        bot.last_report['fort_assembly'] = dict(proposal=best,fully_funded_now=True,
            future_growth_funds=False,command_budget=24,options=len(options),
            certificate=certificate)


def committed(bot,src,dst,amount,mode,target):
    # Only an actual selected collection in the two-producer stage opens
    # this bounded transition. Unselected proposals cannot start a phase.
    if (mode == 'fort_assembly' and bot.pending
            and bot.pending.get('role') == mode
            and sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned) == 2):
        bot._assembly_bridge_until = bot.calls+64
