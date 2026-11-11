"""Current-stock packet accounting on an already observed friendly route."""
from std_geometry import BLANK


def fort_expedition(bot, path, departure, movable, signed=False):
    """A contested king funds its first costly fort from half its stock.

    This local route budget does not alter home_keep or ordinary king moves.
    A feeder through home pays the same hold as a direct home departure.
    """
    guard = max(bot.home_keep, (bot.cells[bot.home][2]+1)//2)
    home_spare = bot.cells[bot.home][2]-guard
    if path[0] == bot.home:
        departure = min(departure, home_spare)
    power = minimum = departure
    for pos in path[1:-1]:
        gain = movable[pos] if signed else -1 if bot.cells[pos][2] == 0 else movable[pos]
        if pos == bot.home:
            gain = min(gain, home_spare)
        power += gain
        minimum = min(minimum, power)
    return departure, power, minimum, guard


def minimum_dispatch(bot, path, required, movable, signed=False):
    """Fund every prefix before using later pickups; leave empty roads one.

    The last cell is the capture target. No future growth or unknown road is
    counted. The caller has already priced visible defenders and counterattacks.
    """
    gain, needed = 0, 1
    for pos in path[1:-1]:
        if pos not in bot.cells or bot.cells[pos][1] != bot.army:
            return None
        gain += movable[pos] if signed else -1 if bot.cells[pos][2] == 0 else movable[pos]
        needed = max(needed, 1-gain)
    needed = max(needed, required-gain)
    return needed if needed <= movable[path[0]] else None


def known_tail(bot, start, amount):
    """At most three currently visible neutral captures; no future sight."""
    best=0
    stack=[(start,min(5,amount),frozenset([start]),0)]
    while stack:
        pos,units,seen,count=stack.pop()
        best=max(best,count)
        if count==3 or units<=1:
            continue
        for nxt in bot.neighbors[pos]:
            if nxt in seen or nxt not in bot.cells:
                continue
            kind,owner,defenders=bot.cells[nxt]
            arrived=units-1-defenders
            if kind==BLANK and owner==0 and arrived>max(0,bot.counter(nxt)):
                stack.append((nxt,arrived,seen|{nxt},count+1))
    return best


def dispatch_with_tail(bot, path, required, movable, signed=False):
    minimum=minimum_dispatch(bot,path,required,movable,signed=signed)
    if minimum is None:
        return None
    gain=sum(movable[p] if signed else -1 if bot.cells[p][2]==0 else movable[p] for p in path[1:-1])
    defending=bot.cells[path[-1]][2]
    candidates=[(known_tail(bot,path[-1],sent+gain-defending),sent)
                for sent in range(minimum,min(movable[path[0]],minimum+3)+1)]
    best=max(count for count,_ in candidates)
    return min(sent for count,sent in candidates if count==best)
