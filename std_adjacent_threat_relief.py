"""Pay an atomic producer counterstrike against the resulting public threats.

Only the captured target stack is removed. Its owner's other armies, all
other rivals, producer growth and current adjacent counterforce remain paid.
No later return order or future friendly income funds the command.
"""
from std_geometry import KING,FORT

def propose(bot,choices,reserves):
    bot._relief_capital_auth={}
    if (not getattr(bot,'_single_capital_fortress',False) or bot.pending
            or bot.cells[bot.home][2]<128
            or any(h<=2 for h,_ in bot.last_report.get('defense_shortages',()))):return
    stock=bot.cells[bot.home][2]
    before=max(bot.threat_curve(12))
    history=getattr(bot,'_relief_capital_history',{})
    for dst in sorted(bot.neighbors[bot.home]):
        data=bot.cells.get(dst)
        if (not data or data[0]!=FORT or data[1] in (0,bot.army)
                or data[1] in bot.eliminated or data[2]<32
                or bot.calls-history.get((dst,data[1]),-1000)<24):continue
        after=max(bot.threat_curve(12,exclude=(dst,)))
        relief=max(0,before-after)
        if not relief:continue
        floor=max(24,after+24,bot.home_keep-relief)
        amount=data[2]+bot.counter(dst)+3
        if amount>stock-floor:continue
        auth=dict(keep=floor,owner=data[1],target_units=data[2],
            before_threat=before,after_threat=after,removed_threat=relief,
            counterforce=bot.counter(dst),current_stock=stock)
        bot._relief_capital_auth[(bot.home,dst,amount)]=auth
        choices.append((700000.0+relief,bot.home,dst,amount,'relief_capital',dst))
        bot.last_report.setdefault('relief_capital',[]).append(dict(auth,target=dst,sent=amount))

def authorized(bot,src,dst,amount,mode):
    if mode!='relief_capital':return None
    return getattr(bot,'_relief_capital_auth',{}).get((src,dst,amount))

def captured_target(bot,choice):
    _,src,dst,amount,mode,_=choice
    auth=authorized(bot,src,dst,amount,mode)
    if (auth and src==bot.home and src in bot.owned and dst in bot.neighbors[src]
            and bot.cells.get(dst)==(FORT,auth['owner'],auth['target_units'])
            and bot.cells[src][2]-amount>=auth['keep']):return dst
    return None

def remaining_curve(bot,choice,horizon,ordinary):
    target=captured_target(bot,choice)
    return bot.threat_curve(horizon,exclude=(target,)) if target is not None else ordinary

def execute(bot,src,dst,amount,mode,commit):
    auth=authorized(bot,src,dst,amount,mode)
    if (not auth or src!=bot.home or bot.pending or src not in bot.owned
            or dst not in bot.neighbors[src]
            or bot.cells.get(dst)!=(FORT,auth['owner'],auth['target_units'])
            or bot.cells[src][2]-amount<auth['keep']):return None
    before=bot.home_keep;active=bot._active_reserves.get(src,1)
    bot.home_keep=auth['keep'];bot._active_reserves[src]=auth['keep']
    try:return commit()
    finally:bot.home_keep=before;bot._active_reserves[src]=active

def committed(bot,src,dst,amount,mode,target):
    auth=authorized(bot,src,dst,amount,mode)
    if not auth or not bot.pending or bot.pending.get('role')!=mode:return
    history=getattr(bot,'_relief_capital_history',{})
    history[(dst,auth['owner'])]=bot.calls;bot._relief_capital_history=history
    bot.last_report['relief_capital_commit']=dict(auth,src=src,dst=dst,sent=amount)
