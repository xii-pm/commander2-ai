"""Keep a growing king out of low-force ordinary-tile capture cycles.

Inspired by ProbeFort's sustained king accumulation in native development
games. This is an opportunity-cost heuristic, not a claim about unseen force.
"""
from std_geometry import BLANK, KING, FORT


def tiny_duel_reclaim(bot, move):
    if (not bot.config.get('duel_contact_patience', False) or move is None
            or move[0] != bot.home or move[1] not in bot.cells
            or not getattr(bot, '_opening_contact', False) or bot.calls < 48
            or bot.cells[bot.home][2] < 8
            or sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) != 1):
        return False
    _, dst, amount = move
    kind, owner, units = bot.cells[dst]
    king = bot.kings.get(owner)
    return (kind == BLANK and owner not in (0, bot.army) and units <= 3
        and 0 < amount <= units+2 and king is not None and king['units'] >= 8
        and bot.risk_dist.get(king['pos'], 999) <= 2
        and bot.tick-king['seen'] <= bot.KING_MAX_AGE)


def allowed(bot, move):
    if tiny_duel_reclaim(bot, move):
        return False
    if not bot.config.get('patient_home_intercept', False) or move is None:
        return True
    src, dst, _ = move
    if src != bot.home or dst not in bot.cells:
        return True
    kind, owner, units = bot.cells[dst]
    home_units = bot.cells[bot.home][2]
    return not (getattr(bot, '_opening_contact', False)
        and kind == BLANK and owner > 0 and owner != bot.army
        and units <= 3 and home_units >= 8 and units*3 < home_units)
