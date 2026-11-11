"""Local producer counterattacks release only the eliminated threat's reserve."""
from std_geometry import FORT


def interception_keep(bot, src, dst):
    if (not bot.config.get('producer_counterstrike',False)
            or not bot.config.get('producer_reserve',False)
            or getattr(bot,'_opening_contact',True) is not False
            or src not in bot.cells or dst not in bot.cells
            or bot.cells[src][:2] != (FORT,bot.army)
            or dst not in bot.neighbors[src] or bot.cells[dst][1] <= 0
            or bot.cells[dst][1] == bot.army):
        return None
    return 1+bot.counter(src,excluded=(dst,))


def propose(bot, choices):
    for src in bot.owned:
        if bot.cells[src][0] != FORT:
            continue
        for dst in bot.neighbors[src]:
            keep=interception_keep(bot,src,dst)
            if keep is None:
                continue
            sent=bot.cells[dst][2]+1
            if sent > bot.cells[src][2]-keep:
                continue
            distance=bot.risk_dist.get(dst,999)
            base=13000 if distance == 1 else 500
            choices.append((base+bot.cells[dst][2]/float(distance+1),
                            src,dst,sent,'intercept',dst))
            bot.last_report.setdefault('producer_counterstrikes',[]).append(
                dict(src=src,dst=dst,sent=sent,remaining_guard=keep))
