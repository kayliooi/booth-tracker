"""Basket pricing: every item has a single price, and "N for $X" deals apply to any mix of one type.

Works in cents so totals never pick up floating-point errors.
"""
from collections import defaultdict


def _cents(x):
    """Convert dollars to whole cents."""
    return int(round(float(x) * 100))


def _best_split(prices, options):
    """Choose how many of `prices` (sorted high to low) to cover with deals.

    Deals cost the same whichever pieces go in them, so the most expensive pieces go into deals.
    Returns (pieces in deals, deal cost, {(qty, price): times used}), all in cents.
    """
    n = len(prices)
    best = [0] + [None] * n          # best[k]: cheapest way to cover exactly k pieces with deals
    pick = [None] * (n + 1)
    for k in range(1, n + 1):
        for q, p in options:
            if q <= k and best[k - q] is not None and (best[k] is None or best[k - q] + p < best[k]):
                best[k], pick[k] = best[k - q] + p, (q, p)

    tail = [0] * (n + 1)             # tail[m]: single price of every piece from m onwards
    for i in range(n - 1, -1, -1):
        tail[i] = tail[i + 1] + prices[i]

    m = 0
    for k in range(1, n + 1):
        if best[k] is not None and best[k] + tail[k] < best[m] + tail[m]:
            m = k

    used, k = defaultdict(int), m
    while k:
        used[pick[k]] += 1
        k -= pick[k][0]
    return m, best[m], dict(used)


def price_basket(lines, deals):
    """Work out what to charge for a basket.

    lines: dicts with item_id, type, unit_price and qty.
    deals: dicts with type, qty and price, e.g. {"type": "Small sticker", "qty": 3, "price": 5}.

    Returns (charges, applied):
        charges: {item_id: amount to charge for that line}; a deal's price is split across its
                 pieces in proportion to their single prices.
        applied: [{"type", "used": {(qty, price): times}, "saving"}] for each type that got a deal.
    """
    options = defaultdict(list)
    for d in deals:
        if d["type"] and int(d["qty"]) >= 1:
            options[d["type"]].append((int(d["qty"]), _cents(d["price"])))

    pieces = defaultdict(list)       # type -> [(price in cents, item_id)], one entry per piece
    for line in lines:
        pieces[line["type"]] += [(_cents(line["unit_price"]), line["item_id"])] * int(line["qty"])

    charges = {line["item_id"]: 0 for line in lines}
    applied = []
    for typ, units in pieces.items():
        units.sort(key=lambda u: u[0], reverse=True)
        m, deal_cost, used = _best_split([p for p, _ in units], options.get(typ, []))

        in_deals, list_total = units[:m], sum(p for p, _ in units[:m])
        remaining = deal_cost
        for i, (p, item_id) in enumerate(in_deals):
            if i == m - 1:
                share = remaining                     # last piece takes the rounding leftovers
            elif list_total:
                share = deal_cost * p // list_total
            else:
                share = deal_cost // m
            charges[item_id] += share
            remaining -= share
        for p, item_id in units[m:]:
            charges[item_id] += p

        if m:
            applied.append({"type": typ,
                            "used": {(q, p / 100): times for (q, p), times in used.items()},
                            "saving": (list_total - deal_cost) / 100})

    return {i: c / 100 for i, c in charges.items()}, applied
