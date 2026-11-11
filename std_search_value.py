"""Value first observations inside the existing frontier scoring system.

One previously unseen hex receives the existing neutral-land value. The
bonus is paid once in the endpoint value and divided by the same route cost.
No scout order, mission, reserve release or second command owner is created.
"""
from std_geometry import KING, FORT


def active(bot):
    return (bot.config.get('search_reveal_value', False)
            and bot.config.get('information', False) and bot.calls > 100
            and (not bot.config.get('search_contact_safety', False) or
                 not any(bot.risk_dist.get(p, 999) <= 6 for p in bot.enemies))
            and (not bot.config.get('search_reveal_insured', False) or
                 bot.cells[bot.home][2] >= bot.home_keep
                 and not bot.last_report.get('defense_shortages'))
            and not any(bot.tick-model['seen'] <= bot.KING_MAX_AGE
                        for model in bot.kings.values())
            and sum(bot.cells[p][0] in (KING, FORT) for p in bot.owned) >= 2
            and any(data[1] > 0 and data[1] != bot.army
                    for data in bot.memory.values()))


def bonus(bot, sight):
    # 58 is the existing frontier value of claiming one neutral plain. Reuse
    # that economic unit rather than fitting a new weight to a map or rival.
    return 58 * len(sight) if getattr(bot, '_search_reveal_active', False) else 0
