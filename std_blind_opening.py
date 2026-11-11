"""Insure the unexposed single-producer opening before the first raid."""
from std_home_watch import coverage


def reserve(bot,current,share,foothold=0,adaptive=False):
    first_contact = getattr(bot,'_warning_first_contact',None)
    if first_contact is None and any(c[1] not in (0,bot.army) for c in bot.cells.values()):
        first_contact=bot.calls
        bot._warning_first_contact=first_contact
    threshold=32
    if bot.calls<threshold or first_contact is not None:
        return current
    bot._late_warning_active=True
    producers = sum(bot.cells[p][0] in (2,3) for p in bot.owned)
    if (producers != 1 or len(bot.owned) < 8
            or getattr(bot,'_king_exposed',False)
            or getattr(bot,'_first_fort_investment',None)):
        return current
    clear,area,missing = coverage(bot)
    if adaptive:
        # Public fixed hills cannot conceal a traversable approach. The
        # ordinary coverage search already stops at the first unseen cell.
        missing=[p for p in missing if p not in getattr(bot,'hill_hints',())
            and getattr(bot,'memory',{}).get(p,(0,))[0] not in (4,5)]
        clear=not missing
    missing=[p for p in missing if area[p]<=2]
    if not missing:
        return current
    total = sum(bot.cells[p][2] for p in bot.owned)
    if adaptive and min(area[p] for p in missing)<=2:
        foothold=0
    keep = max(current,(max(0,total-foothold)*share+99)//100)
    bot._blind_opening_reserve = dict(share=share,units=total,keep=keep,
        missing_warning_cells=len(missing),foothold=foothold,adaptive=adaptive,
        basis='policy insurance; unseen force unknown')
    return keep
