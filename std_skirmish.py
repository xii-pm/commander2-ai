"""Bounded public-observation combat search; no engine or opponent imports."""
from math import exp

from std_geometry import BLANK, KING, FORT, BLOCKED, hex_distance
from std_patience import allowed as patient_intercept_allowed
from std_skirmish_support import return_support


def apply_move(board, move, army):
    result = dict(board)
    if move is None:
        return result
    src, dst, amount = move
    if src not in result or dst not in result or result[src][1] != army:
        return result
    kind, _, units = result[src]
    amount = min(amount, units-1)
    if amount <= 0:
        return result
    result[src] = kind, army, units-amount
    terrain, owner, defending = result[dst]
    if owner == army:
        result[dst] = terrain, owner, defending+amount
    elif amount > defending:
        result[dst] = terrain, army, amount-defending
    else:
        result[dst] = terrain, owner, defending-amount
    return result


def search(bot, proposals):
    """Maximize worst public reply, checking both command resolution orders.

    Idle is a real option. Growth is omitted for both players over this single
    exchange; the reserve cushion covers the unknown production phase and fog.
    """
    cells, army, home = bot.cells, bot.army, bot.home
    enemy = [p for p in bot.enemies if bot.risk_dist.get(p, 999) <= 6]
    if not enemy:
        return None
    focus = min(enemy, key=lambda p: (bot.risk_dist.get(p, 999), p))
    enemy_kings = {p for p in bot.enemies if cells[p][0] == KING}
    cushion = bot.config.get('skirmish_cushion', 6)
    if bot.config.get('adaptive_skirmish_cushion', False):
        # A one-soldier observer cannot dispatch a raid yet. Scale the fog
        # cushion with currently observed mobile force instead of requiring
        # eight idle king soldiers before the first safe economic move.
        mobile = max([0] + [max(0, cells[p][2]-1) for p in enemy])
        cushion = min(cushion, 2+(mobile+3)//4)
    positions = set(cells)
    # Value only: no future troop is made available to apply_move or dispatch.
    # Native ordinary land grows roughly once per fifty callbacks. Keeping
    # such land for the configured horizon is uncertain, especially in fog.
    income_horizon = bot.config.get('skirmish_income_horizon', 0)
    plain_income = income_horizon/50.0
    visibility_value = {p: len({n for n in bot.neighbors[p] if n not in bot.memory})
                        for p in positions}

    def value(board, include_support=True):
        if board.get(home, (0, 0, 0))[1] != army:
            return -10000000
        if any(board[p][1] == army for p in enemy_kings):
            return 10000000
        total = 0.0
        forces = []
        for p, (kind, owner, units) in board.items():
            if owner <= 0:
                continue
            sign = 1 if owner == army else -1
            total += sign*(units + (65 if kind == FORT else 3))
            if kind == BLANK:
                total += sign*plain_income
            if owner == army:
                total += visibility_value[p]*.8
                if p != home:
                    total += max(0, units-1)*.07*(8-min(8, hex_distance(p, focus)))
            else:
                distance = bot.risk_dist.get(p, 999)
                if distance <= 4:
                    forces.append(max(0, units-1)/float(max(1, distance)))
        forces.sort(reverse=True)
        hazard = (forces[0] if forces else 0)+(forces[1]*.25 if len(forces)>1 else 0)
        slack = board[home][2]-hazard-cushion
        if include_support and bot.config.get('skirmish_adjacent_support', False):
            slack += return_support(bot, board)
        total -= 20*exp(max(-6, min(8, -slack/6.0)))
        return total

    own = {None: ('skirmish_wait', home)}
    sources = sorted(bot.owned, key=lambda p: (cells[p][2], p), reverse=True)[:12]
    for src in sources:
        # Let the same public reply search price king outflow, instead of
        # excluding it solely because a long-term economic reserve is high.
        # This is an experimental candidate-coverage change, not a safety proof.
        amount = (max(0,cells[src][2]-1) if src == home
                  and bot.config.get('skirmish_home_stock',False) else bot.available(src))
        if amount < 1:
            continue
        for dst in bot.neighbors[src]:
            if dst not in cells or cells[dst][0] in BLOCKED:
                continue
            kind, owner, units = cells[dst]
            if owner == army:
                if dst != home and hex_distance(dst, focus) >= hex_distance(src, focus):
                    continue
                counts = [amount]
            else:
                if amount <= units:
                    continue
                counts = {amount, units+1}
            for count in counts:
                own[(src, dst, count)] = ('defend' if dst == home else 'skirmish', dst)
    for _, src, dst, amount, mode, target in sorted(proposals, reverse=True)[:32]:
        if amount > 0:
            own[(src, dst, amount)] = (mode, target)
    own = {move: label for move, label in own.items()
           if patient_intercept_allowed(bot, move)}

    replies = {None}
    for src in bot.enemies:
        units = cells[src][2]
        if units <= 1 or bot.risk_dist.get(src, 999) > 6:
            continue
        for dst in bot.neighbors[src]:
            if dst not in cells or cells[dst][0] in BLOCKED:
                continue
            replies.add((src, dst, units-1))
            if cells[dst][1] != cells[src][1] and units-1 > cells[dst][2]:
                replies.add((src, dst, cells[dst][2]+1))
    # Select the most harmful distinct public replies before the exchange.
    # Keep the original reply beam for this isolated leaf-value experiment.
    # Support changes the exchanged board's price, not reply coverage.
    replies = sorted(replies, key=lambda move: value(apply_move(cells, move,
        cells[move[0]][1] if move else 0), False))[:10]
    best = None
    for move, (mode, target) in own.items():
        score = float('inf')
        own_first = apply_move(cells, move, army)
        for reply in replies:
            opponent = cells[reply[0]][1] if reply else 0
            a = value(apply_move(own_first, reply, opponent))
            b = value(apply_move(apply_move(cells, reply, opponent), move, army))
            score = min(score, a, b)
        score -= .3 if move else 0
        # Deterministic tie: fewer dispatched troops, then visible coordinates.
        tie = (score, -(move[2] if move else 0), move or ((-1,-1),(-1,-1),0))
        if best is None or tie > best[0]:
            best = tie, move, mode, target
    _, move, mode, target = best
    bot.last_report['skirmish'] = dict(options=len(own), replies=len(replies),
                                      value=round(best[0][0], 3), cushion=cushion,
                                      income_horizon=income_horizon)
    if bot.config.get('skirmish_adjacent_support', False):
        bot.last_report['skirmish']['adjacent_support'] = return_support(bot, cells)
    if move is None:
        return (500000, home, home, 0, 'skirmish_wait', target)
    return (500000, move[0], move[1], move[2], mode, target)
