"""Compare a paid two-order elimination with the actual home deadline.

An ordinary funded assault retains its original dispatch and authority. This
policy only changes its rank: a danger five orders away need not cancel an
elimination in two orders. Hidden reinforcements remain an explicit risk.
"""
from std_geometry import KING, MARSH, BLOCKED


def eligible(bot, row):
    _,src,stage,amount,mode,target=row
    if (mode!='assault' or src==bot.home or not getattr(bot,'_single_capital_fortress',False)
            or target not in bot.cells or bot.cells[target][0]!=KING
            or bot.cells[target][1] in (0,bot.army) or stage==target
            or target not in bot.neighbors.get(stage,())
            or stage not in bot.cells or bot.cells[stage][0] in BLOCKED+(MARSH,)
            or amount>bot.available(src)):
        return None
    cell=bot.cells[stage]
    stage_stock=amount+cell[2] if cell[1]==bot.army else amount-cell[2]
    # This is the same current-stock assault, with explicit stage toll and
    # both target growth allowances. Do not promote a mere approach.
    need=bot.cells[target][2]+3
    if stage_stock<need:
        return None
    held=bot.cells[bot.home][2]
    before=bot.threat_curve(2)
    if any(held+(h-1)//2<force for h,force in enumerate(before) if h):
        return None
    owner=bot.cells[target][1]
    excluded=tuple(p for p,d in bot.memory.items() if d[1]==owner)
    after=bot.threat_curve(6,exclude=excluded,zero_uncertainty=False)
    if any(held+(h-1)//2<force for h,force in enumerate(after) if h):
        return None
    return dict(source=src,stage=stage,target=target,dispatch=amount,commands=2,
        stage_stock=stage_stock,king_capture_need=need,home_stock=held,
        before_curve=before,other_owner_curve=after,
        limitation='Current observed funded assault; hidden reinforcement and rival replies are not certified.')


def promote(bot,row):
    record=eligible(bot,row)
    if record:
        bot.last_report.setdefault('deadline_eliminations',[]).append(record)
        return True
    return False
