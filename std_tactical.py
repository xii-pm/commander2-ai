"""Bounded two-exchange public-board search, without engine access.

Beams are approximations, not a complete minimax proof. Both command orders
are checked. Future fog and growth are omitted; the leaf retains a fog margin.
Only the first command is proposed and all later commands are replanned.
"""
from math import exp

from std_geometry import BLANK, KING, FORT, BLOCKED, hex_distance
from std_skirmish import apply_move


def search(bot, proposals, cushion=None, economic_probe=False):
    board, army, home = bot.cells, bot.army, bot.home
    opponents = {d[1] for d in board.values() if d[1] > 0 and d[1] != army}
    if len(opponents) != 1:
        return None
    rival = next(iter(opponents))
    enemy_kings = {p for p, d in board.items() if d[:2] == (KING, rival)}
    near = [p for p in bot.enemies if bot.risk_dist.get(p, 999) <= 6]
    if not near:
        return None
    focus = min(near, key=lambda p: (bot.risk_dist.get(p, 999), p))
    if cushion is None:
        cushion = bot.config.get('skirmish_cushion', 8)
    visibility = {p: len([n for n in bot.neighbors[p] if n not in bot.memory])
                  for p in board}
    leaves = [0]

    def value(cells):
        leaves[0] += 1
        if cells.get(home, (0, 0, 0))[1] != army:
            return -10000000.0
        if any(cells[p][1] == army for p in enemy_kings):
            return 10000000.0
        total, threats = 0.0, []
        for p, (kind, owner, units) in cells.items():
            if owner <= 0:
                continue
            sign = 1 if owner == army else -1
            total += sign*(units+(65 if kind == FORT else 3))
            if owner == army:
                total += visibility[p]*.8
                if p != home:
                    total += max(0, units-1)*.07*(8-min(8, hex_distance(p, focus)))
            elif bot.risk_dist.get(p, 999) <= 4:
                threats.append(max(0, units-1)/float(max(1, bot.risk_dist[p])))
        threats.sort(reverse=True)
        hazard = (threats[0] if threats else 0)+(threats[1]*.25 if len(threats)>1 else 0)
        # Nearby own packets remain available for one actual next command.
        # Count only the largest adjacent donor, never all branches at once.
        support = max([0]+[max(0, cells[p][2]-1) for p in bot.neighbors[home]
                           if p in cells and cells[p][1] == army])
        slack = cells[home][2]+support-hazard-cushion
        return total-20*exp(max(-6, min(8, -slack/6.0)))

    def moves(cells, side):
        sources = sorted([p for p, d in cells.items() if d[1] == side and d[2] > 1],
                         key=lambda p: (cells[p][2], p), reverse=True)[:8]
        result = {None}
        for src in sources:
            amount = cells[src][2]-1
            for dst in bot.neighbors[src]:
                if dst not in cells or cells[dst][0] in BLOCKED:
                    continue
                _, owner, units = cells[dst]
                if owner == side:
                    if cells[dst][2] == 0 and amount <= 1:
                        continue
                    result.add((src, dst, amount))
                elif amount > units:
                    result.add((src, dst, units+1))
                    result.add((src, dst, amount))
        return result

    def key(move):
        return move or ((-1,-1),(-1,-1),0)

    def beam(cells, side, width):
        reverse = side == army
        options = sorted(moves(cells, side),
                         key=lambda m: (value(apply_move(cells, m, side)), key(m)),
                         reverse=reverse)
        chosen = options[:width]
        # Keep waiting as a distinct opponent reply and own continuation.
        if None not in chosen:
            chosen.append(None)
        return chosen

    def exchange(cells, own, reply):
        return (apply_move(apply_move(cells, own, army), reply, rival),
                apply_move(apply_move(cells, reply, rival), own, army))

    cache = {}

    def continuation(cells):
        signature = tuple(sorted(cells.items()))
        if signature in cache:
            return cache[signature]
        immediate = value(cells)
        if abs(immediate) >= 10000000:
            return immediate
        responses = beam(cells, army, 5)
        replies = beam(cells, rival, 4)
        best = -float('inf')
        for move in responses:
            worst = float('inf')
            for reply in replies:
                worst = min(worst, *(value(b) for b in exchange(cells, move, reply)))
                if worst <= best:
                    break
            best = max(best, worst-(.3 if move else 0))
        # Prefer a victory in this exchange to the same projected victory one
        # exchange later; otherwise waiting can tie an immediate king capture.
        best *= .99
        cache[signature] = best
        return best

    root = moves(board, army)
    for _, src, dst, amount, mode, target in proposals:
        if amount > 0:
            root.add((src, dst, amount))
    replies = beam(board, rival, 4)
    ranked = []
    for move in root:
        worst = min(value(b) for reply in replies for b in exchange(board, move, reply))
        ranked.append((worst, key(move), move))
    ranked.sort(reverse=True)
    candidates = [row[2] for row in ranked[:10]]
    if None not in candidates:
        candidates.append(None)
    probes = set()
    if economic_probe:
        for move in root:
            if (move is not None and move[0] == home and move[2] == 1
                    and board[move[1]] == (BLANK, 0, 0)
                    and hex_distance(move[1], focus) >= hex_distance(home, focus)
                    and visibility[move[1]] > 0):
                probes.add(move)
        for move in sorted(probes):
            if move not in candidates:
                candidates.append(move)
    safe_probes = []
    best = None
    for move in candidates:
        worst = float('inf')
        tested_replies = sorted(moves(board, rival), key=key) if move in probes else replies
        for reply in tested_replies:
            worst = min(worst, *(continuation(b) for b in exchange(board, move, reply)))
            if move not in probes and best is not None and worst < best[0][0]:
                break
        if move in probes and worst > -1000000:
            safe_probes.append((visibility[move[1]], worst, move))
        rank = (worst-(.3 if move else 0), -(move[2] if move else 0), key(move))
        if best is None or rank > best[0]:
            best = rank, move
    rank, move = best
    # The fixed fog-price leaf can prefer perpetual waiting even after every
    # examined two-exchange raid is exhausted. One current soldier may buy
    # new information, provided a defense continuation exists in this bounded
    # model. The caller separately funds unexplained hidden departures.
    if safe_probes and rank[0] < 1000000:
        _, value_score, move = max(safe_probes)
        rank = value_score-.3, -1, key(move)
    bot.last_report['tactical'] = dict(depth=2, root_options=len(root),
        searched=len(candidates), replies=len(replies), leaves=leaves[0],
        continuations=len(cache), value=round(rank[0],3), cushion=cushion,
        economic_probes=len(probes), surviving_probes=len(safe_probes),
        model='visible board; no future growth/fog; bounded beams')
    if move is None:
        return (500000, home, home, 0, 'tactical_wait', home)
    return (500000, move[0], move[1], move[2], 'tactical', move[1])
