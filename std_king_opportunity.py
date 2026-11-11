"""Current-stock short approaches to publicly contested, weakened kings.

Falling king stock plus third-party pressure is compatible with a siege, not
proof of who attacked. No future third-party damage funds a capture plan.
"""
from math import ceil, sqrt
from std_geometry import BLANK, KING, FORT, hex_distance


class Opportunity:
    def __init__(self):
        self.previous = {}
        self.signals = {}

    def observe(self, bot, cells):
        signals = {}
        pending = bot.pending
        touched = {pending['src'],pending['dst']} if pending else set()
        for pos,now in cells.items():
            old = self.previous.get(pos)
            if (old and now[0] == old[0] == KING and now[1] == old[1]
                    and now[1] > 0 and now[1] != bot.army and pos not in touched
                    and now[2] < old[2]):
                signals[pos] = dict(stock_drop=old[2]-now[2], previous_stock=old[2],
                    current_stock=now[2], cause='unattributed_public_stock_decrease')
        self.signals = signals
        self.previous = dict(cells)


def propose(bot, choices, movable, reserves):
    if (not bot.config.get('king_opportunity',False) or bot.map314 or bot.pending):
        return
    model = getattr(bot,'king_opportunity',None)
    if model is None:
        return
    records, skipped = [], []
    # Existing defense deadlines own the command before a preparatory race.
    if any(h<=6 for h,_ in bot.last_report.get('defense_shortages',())):
        bot.last_report['king_opportunity'] = dict(blocked='defense_deadline',offers=[])
        return
    held = bot.cells[bot.home][2]
    curve = bot.threat_curve(6)
    if any(force > held for force in curve[1:]):
        bot.last_report['king_opportunity'] = dict(blocked='unfunded_home_pressure',offers=[])
        return
    for target,signal in sorted(model.signals.items()):
        data = bot.cells.get(target)
        if not data or data[0] != KING or data[1] in (0,bot.army):
            continue
        victim, stock = data[1], data[2]
        outsiders = [(p,d) for p,d in bot.cells.items() if d[1] > 0
                    and d[1] not in (victim,bot.army) and d[0] in (BLANK,KING,FORT)
                    and d[2] > 1 and hex_distance(p,target) <= 2]
        if not outsiders:
            continue
        immediate = [(p,d) for p,d in outsiders
                     if p in bot.neighbors[target] and d[2]-1 > stock]
        if immediate:
            # Current adjacent captures already use the existing immediate
            # elimination branch. Do not race two commands against one.
            skipped.append(dict(target=target,reason='third_party_can_capture_in_one_current_order'))
            continue
        reinforcement = max([0]+[max(0,bot.cells[p][2]-1) for p in bot.neighbors[target]
                        if p in bot.cells and bot.cells[p][1] == victim])
        third_reply = max([0]+[d[2]-1 for p,d in outsiders if p in bot.neighbors[target]])
        roots = sorted((p for p in bot.owned if bot.cells[p][0] == BLANK
                        and movable.get(p,0) >= 3 and hex_distance(p,target) <= 3),
                       key=lambda p:(hex_distance(p,target),-movable[p],p))[:8]
        offers = []
        for src in roots:
            # Enumerate at most two visible preparatory steps plus a strike.
            stack = [(src,(src,))]
            while stack:
                pos,path = stack.pop()
                if len(path) >= 2 and target in bot.neighbors[pos]:
                    route = path+(target,)
                    commands = len(route)-1
                    road_cost = sum(1+(bot.cells[p][2] if bot.cells[p][1]==0 else 0) for p in path[1:])
                    # Never pre-spend damage another player may inflict.
                    king_need = stock+int(ceil(.52*commands))+reinforcement+third_reply+2
                    first = path[1]
                    first_cost = bot.cells[first][2] if bot.cells[first][1] == 0 else 0
                    counter = bot.counter(first,excluded=(target,))
                    amount = max(king_need+road_cost,first_cost+counter+2)
                    if amount <= movable[src] and held >= reserves.get(bot.home,1):
                        record = dict(target=target,victim=victim,route=route,commands=commands,
                            source=src,dispatch=amount,signal=signal,
                            third_party_owners=sorted({d[1] for _,d in outsiders}),
                            current_king_stock=stock,defender_one_order_reinforcement=reinforcement,
                            third_party_adjacent_reply=third_reply,road_cost=road_cost,
                            first_hop_counter=counter,king_need=king_need,
                            future_third_party_damage_funds=0,
                            race='conditional; future opponent moves and order timing unknown')
                        score = 850000.0+5000.0/commands+sqrt(amount)
                        offers.append(((score,src,first,amount,'assault',target),record))
                if len(path) >= 3:
                    continue
                for nxt in bot.neighbors[pos]:
                    d = bot.cells.get(nxt)
                    if (nxt in path or nxt == target or not d or d[0] != BLANK
                            or d[1] not in (0,bot.army)
                            or hex_distance(nxt,target) >= hex_distance(pos,target)):
                        continue
                    stack.append((nxt,path+(nxt,)))
        if offers:
            proposal,record = max(offers,key=lambda item:item[0])
            choices.append(proposal)
            records.append(record)
    bot.last_report['king_opportunity'] = dict(offers=records,skipped=skipped,
        model='public stock decrease plus nearby third-party pressure; current-funded visible route')
