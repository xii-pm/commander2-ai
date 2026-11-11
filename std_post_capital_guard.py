"""Keep the paid home guard across confirmed first-fort acquisition."""


def committed(bot,src,dst,amount,mode,target):
    if mode=='investment' and bot.pending:
        plan=getattr(bot,'_producer_investment',None)
        if plan:
            bot._capital_guard_transit=dict(target=target,guard=plan['guard'],
                expires=bot.calls+24,confirmed_capture=False)


def reserve(bot):
    transit=getattr(bot,'_capital_guard_transit',None)
    hold=getattr(bot,'_post_capital_guard',None)
    observed=getattr(bot,'_observed_pending',None)
    if transit:
        if bot.calls>transit['expires']:transit=None
        elif (observed and getattr(bot,'_last_order_confirmed',False)
                and observed.get('role') in ('investment','investment_route')
                and observed['dst']==transit['target']
                and bot.cells.get(transit['target'],(0,0,0))[1]==bot.army):
            hold=dict(target=transit['target'],guard=transit['guard'],until=bot.calls+24,
                confirmed_capture=True)
            transit=None
    if hold and bot.calls>hold['until']:hold=None
    bot._capital_guard_transit=transit;bot._post_capital_guard=hold
    active=hold or transit
    bot.last_report['post_capital_guard']=dict(active) if active else None
    return active['guard'] if active else 1
