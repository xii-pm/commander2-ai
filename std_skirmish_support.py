"""One-command adjacent support for the local search's leaf valuation only.

Only the strongest adjacent donor is credited. Its payload is reduced by
visible attacks which could resolve before the return. An immediately losing
king receives no support credit. Future growth and hidden troops are omitted;
this heuristic does not authorize a dispatch or certify future king safety.
"""


def return_support(bot, board):
    army, home = bot.army, bot.home
    if home not in board or board[home][1] != army:
        return 0
    adjacent = bot.neighbors[home]
    immediate = max([0]+[max(0, board[p][2]-1) for p in adjacent
                        if p in board and board[p][1] not in (0, army)])
    if board[home][2] <= immediate:
        return 0
    best = 0
    for source in adjacent:
        if source not in board or board[source][1] != army:
            continue
        attacks = {}
        for p in bot.neighbors[source]:
            if p in board and board[p][1] not in (0, army):
                owner, units = board[p][1:]
                attacks[owner] = max(attacks.get(owner, 0), max(0, units-1))
        payload = max(0, board[source][2]-1-sum(attacks.values()))
        best = max(best, payload)
    return best
