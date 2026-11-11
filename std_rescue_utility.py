"""When every schedule misses the first gap, avoid tiny-delivery starvation."""


def select(bot, alternatives, deadlines, inherited, severe_only=False):
    if not alternatives or not deadlines:
        return inherited
    first_h,first_need=deadlines[0]
    if severe_only:
        producers=sum(bot.cells[p][0] in (2,3) for p in bot.owned)
        if (producers<3 or not 2<=first_h<=6
                or first_need<=bot.cells[bot.home][2]):
            return inherited
    # A next-command attack is already executable: retain its strongest
    # immediate partial rescue even when no examined move fully pays it.
    # An inherited funded later rescue also has priority over a utility guess.
    if first_h<=1 or any(inherited[2][h]>=need for h,need in deadlines):
        return inherited
    # Preserve the inherited policy whenever the earliest deadline can be paid.
    if any(row[3][first_h]>=first_need for row in alternatives):
        return inherited
    # Preserve fully payable immediate gaps. Partial delivery at an impossible
    # gap is not a survival certificate and must not seize every future order.
    protected=[(h,need) for h,need in deadlines if h<=3
               and any(row[3][h]>=need for row in alternatives)]
    candidates=[row for row in alternatives if all(row[3][h]>=need for h,need in protected)]
    if not candidates:
        return inherited
    def rank(row):
        force,cost,moves,arrivals=row
        utility=sum(min(need,arrivals[h])/float(h+1) for h,need in deadlines)
        return utility,-cost,force,moves
    best=max(candidates,key=rank)
    force,cost,moves,arrivals=best
    old_arrivals=inherited[2]
    if arrivals==old_arrivals:
        return inherited
    bot.last_report['rescue_shortfall_utility']=dict(first_deadline=first_h,
        impossible_first_shortage=first_need,protected_payable=protected,
        prior_arrivals=old_arrivals,arrival_curve=arrivals,moves=moves,
        discounted_coverage=rank(best)[0],
        limitation='Every examined schedule misses the first gap; survival remains unproven.')
    return (rank(best),moves,arrivals)
