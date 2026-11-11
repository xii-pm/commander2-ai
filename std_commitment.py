"""Bounded producer objectives; each callback must rebuild a funded schedule.

Only the target and its staging road persist. No future command, old troop
amount, or route is trusted. Tactical proposals remain independent.
"""
from std_geometry import KING, FORT


def prepare(bot):
    bot._funded_producer_roots = {}
    active = getattr(bot, '_producer_commitment', None)
    eligible = (bot.config.get('producer_commitment', False)
        and getattr(bot, '_opening_contact', True) is False
        and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) == 1)
    if not eligible:
        active = None
    if active:
        target, root = active['target'], active['root']
        if (bot.tick >= active['expires'] or target not in bot.cells
                or bot.cells[target][0] != FORT
                or bot.cells[target][1] == bot.army or root not in bot.owned
                or root not in bot.neighbors[target]):
            active = None
    bot._producer_commitment = active
    bot._production_binding = active
    if active:
        bot.last_report['producer_commitment'] = dict(active)


def retain_funded(bot, proposals):
    """Keep a binding only when its current exact collector still funds it."""
    active = getattr(bot, '_production_binding', None)
    if not active:
        return proposals
    matching = [p for p in proposals if p[5] == active['target']
                and bot._funded_producer_roots.get((p[1], p[2], p[3], p[5])) == active['root']]
    bot.last_report['producer_commitment_funded'] = bool(matching)
    other_domains = [p for p in proposals if bot.cells[p[5]][0] != FORT]
    return matching + other_domains if matching else proposals


def committed(bot, src, dst, amount, mode, target):
    if (not bot.config.get('producer_commitment', False) or mode != 'merge'
            or getattr(bot, '_opening_contact', True) is not False
            or sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) != 1
            or any(h <= 6 for h, _ in bot.last_report.get('defense_shortages', []))):
        return
    root = bot._funded_producer_roots.get((src, dst, amount, target))
    if root is None:
        return
    previous = getattr(bot, '_producer_commitment', None)
    expires = (previous['expires'] if previous and previous['target'] == target
               and previous['root'] == root else bot.tick + 12)
    bot._producer_commitment = dict(target=target, root=root, expires=expires)
