"""Joint public replies and soft missing-force valuation after candidate admission.

One current order per visible opponent, a bounded reply beam, and all order
permutations are examined. Growth, fog transitions and later turns are not
simulated; this is a scenario comparison, never a minimax or survival proof.
"""
from itertools import product, permutations
from std_geometry import BLANK, KING, FORT, MARSH, BLOCKED, hex_distance
from std_rival_pressure import visible_curves

MAX_ROOTS = 8
REPLIES = 2
HORIZON = 6
INCOME = 10.0
MIN_GAIN = 2.0
LOSS = -1000000.0
WAIT_MODES = ('bank','skirmish_wait','security_wait','tactical_wait')
MODES = ('capture','advance','merge','supply','rear_supply','bank','fort_assembly',
         'investment','investment_route','intercept','guard_supply','economic_recall','frontier_recon')


def move_key(move):
    return move if move else ((-1,-1),(-1,-1),0)


def apply(board, move, owner):
    after = dict(board)
    if move is None:
        return after
    src,dst,amount = move
    a,b = board.get(src),board.get(dst)
    if not a or not b or a[1]!=owner or b[0] in BLOCKED+(MARSH,):
        return after
    sent = min(amount,a[2]-1)
    if sent<=0:
        return after
    after[src] = a[0],owner,a[2]-sent
    if b[1]==owner:
        after[dst]=b[0],owner,b[2]+sent
    elif sent>b[2]:
        after[dst]=b[0],owner,sent-b[2]
    else:
        after[dst]=b[0],b[1],b[2]-sent
    return after


def context(bot, choices):
    relevant={p for p in bot.cells if hex_distance(p,bot.home)<=3}
    for choice in choices:
        relevant.update(choice[1:3])
    board={p:bot.cells[p] for p in relevant if p in bot.cells}
    owners=sorted({d[1] for p,d in board.items() if d[1]>0 and d[1]!=bot.army})
    tracker=getattr(bot,'_rival_pressure',None)
    missing,records=tracker.project(bot,HORIZON) if tracker else ({},[])
    return dict(bot=bot,army=bot.army,home=bot.home,board=board,owners=owners,
                missing=missing,records=records,cache={})


def value(ctx, board):
    home,army=ctx['home'],ctx['army']
    if board[home][1]!=army:
        return LOSS
    stock=0.0
    for kind,owner,units in board.values():
        if owner<=0:
            continue
        sign=1 if owner==army else -1
        stock+=sign*(units+(INCOME if kind in (KING,FORT) else .4 if kind==BLANK else 0))
    # At most one currently funded adjacent transfer can reinforce next.
    # This contributes only to the leaf proxy, never funds the root order.
    support=max([0]+[max(0,board[p][2]-1) for p in ctx['bot'].neighbors[home]
        if p in board and board[p][1]==army and board[p][0]!=MARSH])
    visible=visible_curves_on_board(ctx,board)
    pressure=0.0
    for h in range(2,HORIZON+1):
        force=sum(max(visible.get(owner,[0]*(HORIZON+1))[h],
                      ctx['missing'].get(owner,[0]*(HORIZON+1))[h])
                  for owner in set(visible)|set(ctx['missing']))
        deficit=max(0,force-board[home][2]-support)
        pressure=max(pressure,deficit/(1.0+.25*h))
    return stock-2.0*pressure


def visible_curves_on_board(ctx, board):
    class View:
        pass
    view=View();bot=ctx['bot']
    view.cells=board;view.army=bot.army;view.eliminated=bot.eliminated;view.risk_dist=bot.risk_dist
    return visible_curves(view,HORIZON)


def reply_options(ctx, owner, root):
    board=ctx['board'];bot=ctx['bot'];home=ctx['home']
    # Rank on the root's resulting board, but issue only current-stock orders
    # from sources the opponent currently owns, as in the other orderings.
    initial=apply(board,root,ctx['army'])
    moves=set()
    for src,a in board.items():
        if a[1]!=owner or a[2]<=1 or a[0]==MARSH or hex_distance(src,home)>3:
            continue
        for dst in bot.neighbors[src]:
            b=board.get(dst)
            if not b or b[0] in BLOCKED+(MARSH,) or b[0]==KING and dst!=home:
                continue
            moves.add((src,dst,a[2]-1))
    def danger(move):
        after=apply(initial,move,owner)
        if after[home][1]!=ctx['army']:
            return (1,0,0,move)
        src,dst,amount=move
        victim=initial[dst]
        core=(victim[0] in (KING,FORT) and victim[1]==ctx['army'])
        # Preserve direct core attacks before approaches and ordinary trades.
        return (0,100000 if dst==home else 10000 if core else 0,
                amount/float(1+hex_distance(dst,home)),move)
    ranked=sorted(moves,key=danger,reverse=True)[:REPLIES]
    return [None]+ranked


def evaluate(ctx, root):
    replies=[reply_options(ctx,owner,root) for owner in ctx['owners']]
    minimum=float('inf');leaves=0;lost=0
    # The same player's source changes can invalidate or clamp a later order.
    for profile in product(*replies):
        orders=([(ctx['army'],root)] if root else [])+[(owner,move) for owner,move in zip(ctx['owners'],profile) if move]
        for order in permutations(range(len(orders))):
            board=ctx['board']
            for index in order:
                owner,move=orders[index]
                board=apply(board,move,owner)
                if board[ctx['home']][1]!=ctx['army']:
                    break
            signature=tuple(sorted(board.items()))
            if signature not in ctx['cache']:
                ctx['cache'][signature]=value(ctx,board)
            result=ctx['cache'][signature]
            minimum=min(minimum,result);lost+=result==LOSS;leaves+=1
    return dict(value=minimum,leaves=leaves,losing_leaves=lost,
                all_public_orders_survive=not lost,reply_counts=[len(r) for r in replies])


def rerank(bot, choices, enabled=True):
    if not choices or bot.pending or getattr(bot,'map314',0):
        return choices
    original=max(choices)
    if original[0]>=1000000 or original[4] not in MODES:
        return choices
    near={bot.cells[p][1] for p in bot.enemies if bot.risk_dist.get(p,999)<=6}
    if len(near)<2 or len(set(bot.known_owners)-set(bot.eliminated))<2:
        return choices
    tracker=getattr(bot,'_rival_pressure',None)
    _,records=tracker.project(bot,HORIZON) if tracker else ({},[])
    local_mobile=sum(max(0,bot.cells[p][2]-1) for p in bot.enemies if bot.risk_dist.get(p,999)<=2)
    if not records and local_mobile<8:
        return choices
    pool=[];seen=set()
    for row in [original]+sorted(choices,reverse=True):
        _,src,dst,amount,mode,_=row
        move=None if mode in WAIT_MODES else (src,dst,amount)
        if (move in seen or mode not in MODES or row[0]>=1000000
                or src not in bot.cells or dst not in bot.cells
                or bot.cells[src][0]==MARSH or bot.cells[dst][0] in BLOCKED+(MARSH,)
                or mode not in WAIT_MODES and (type(amount) is not int or not 0<amount<bot.cells[src][2])):
            continue
        if row!=original and min(hex_distance(src,bot.home),hex_distance(dst,bot.home))>2:
            continue
        if bot.cells[dst][0]==KING and bot.cells[dst][1] not in (0,bot.army):
            continue
        seen.add(move);pool.append((row,move))
        if len(pool)>=MAX_ROOTS:
            break
    if not pool or pool[0][0]!=original:
        return choices
    if None not in seen:
        pool.append(((0,bot.home,bot.home,0,'security_wait',bot.home),None))
    ctx=context(bot,[p[0] for p in pool])
    if any(d[0]==MARSH and d[1]>0 and d[1]!=bot.army and hex_distance(p,bot.home)<=2
           for p,d in ctx['board'].items()):
        return choices
    evaluated=[(evaluate(ctx,move),row,move) for row,move in pool]
    baseline=evaluated[0]
    best=max(evaluated,key=lambda r:(r[0]['value'],r[1]==original,-(r[2][2] if r[2] else 0),move_key(r[2])))
    changed=(best[1]!=original and best[0]['value']>LOSS and best[0]['value']>=baseline[0]['value']+MIN_GAIN)
    bot.last_report['joint_response']=dict(changed=bool(changed and enabled),would_change=changed,
        original=list(original),selected=list(best[1]),records=records,
        evaluations=[dict(choice=list(row),**quote) for quote,row,_ in evaluated],
        cached_leaves=len(ctx['cache']),model='one current order per owner; bounded replies, all execution orders; soft tail risk')
    if not changed or not enabled:
        return choices
    chosen=best[1]
    promoted=(max(r[0] for r in choices)+.001,)+tuple(chosen[1:])
    return [r for r in choices if r!=chosen]+[promoted]
