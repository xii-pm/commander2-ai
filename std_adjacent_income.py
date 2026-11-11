"""Buy a visible neighboring producer with currently funded surplus.

The fortress savings target is not an absolute prohibition on investment.
A single hop producer capture may use it only while retaining the complete
unmodified twelve turn threat curve and at least half the current king stock.
This does not assume that fog contains no reinforcement.
"""
from std_geometry import KING,FORT

def propose(bot,choices,reserves):
    bot._adjacent_income_auth={}
    if (not getattr(bot,'_single_capital_fortress',False) or bot.pending
            or sum(bot.cells[p][0] in (KING,FORT) for p in bot.owned)!=1
            or bot.cells[bot.home][2]<64
            or any(h<=6 for h,_ in bot.last_report.get('defense_shortages',()))):
        return
    stock=bot.cells[bot.home][2]
    floor=max(bot.home_keep,max(bot.threat_curve(12))+12,(stock+1)//2)
    history=getattr(bot,'_adjacent_income_history',{})
    for dst in sorted(bot.neighbors[bot.home]):
        data=bot.cells.get(dst)
        if (not data or data[0]!=FORT or data[1] in (0,bot.army)
                or data[1] in bot.eliminated
                or bot.calls-history.get((dst,data[1]),-1000)<24):continue
        # Pay the garrison, one immediate producer tick, a surviving unit,
        # and all currently visible adjacent counterforce.
        amount=data[2]+bot.counter(dst)+3
        if amount>stock-floor:continue
        bot._adjacent_income_auth[(bot.home,dst,amount)]=dict(
            keep=floor,owner=data[1],target_units=data[2])
        choices.append((1200.0,bot.home,dst,amount,'adjacent_income',dst))
        bot.last_report.setdefault('adjacent_income',[]).append(dict(
            dst=dst,sent=amount,keep=floor,current_stock=stock,
            basis='current visible producer; original complete threat retained'))

def authorized(bot,src,dst,amount,mode):
    if mode!='adjacent_income':return None
    return getattr(bot,'_adjacent_income_auth',{}).get((src,dst,amount))

def execute(bot,src,dst,amount,mode,commit):
    auth=authorized(bot,src,dst,amount,mode)
    if (not auth or src!=bot.home or bot.pending
            or dst not in bot.neighbors[src] or dst not in bot.cells
            or bot.cells[dst]!=(FORT,auth['owner'],auth['target_units'])
            or bot.cells[src][2]-amount<auth['keep']):return None
    before=bot.home_keep;active=bot._active_reserves.get(src,1)
    bot.home_keep=auth['keep'];bot._active_reserves[src]=auth['keep']
    try:return commit()
    finally:bot.home_keep=before;bot._active_reserves[src]=active

def committed(bot,src,dst,amount,mode,target):
    auth=authorized(bot,src,dst,amount,mode)
    if not auth or not bot.pending or bot.pending.get('role')!=mode:return
    if not hasattr(bot,'_adjacent_income_history'):bot._adjacent_income_history={}
    bot._adjacent_income_history[(dst,auth['owner'])]=bot.calls
    bot.last_report['adjacent_income_commit']=dict(auth,src=src,dst=dst,sent=amount)
