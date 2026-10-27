"""Printable pages built as standalone HTML files: a price list for the booth table and a one-page
event report. Open the file in any browser, then print or "Save as PDF".
"""
from html import escape

import pandas as pd

import insights

PAYMENT_NAMES = {"cash": "💵 Cash", "card": "💳 Card", "qr": "📱 QR", "deposit": "Order deposits",
                 "unknown": "Not recorded (older sales)"}

PAGE_CSS = """
@page { size: A4; margin: 14mm; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; color: #2E1A47; margin: 0; padding: 24px;
       background: #F7F3FF; }
.sheet { max-width: 820px; margin: 0 auto; background: #fff; border-radius: 16px; padding: 28px 32px; }
h1 { font-size: 30px; margin: 0 0 4px; }
.head { display: flex; align-items: center; gap: 14px; }
.logo { width: 72px; height: 72px; border-radius: 50%; flex: none; }
h2 { font-size: 20px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #EDE4FF; }
.sub { color: #6B5B85; margin: 0 0 8px; }
.deal { display: inline-block; background: #7C3AED; color: #fff; border-radius: 999px; padding: 3px 12px;
        font-weight: 600; font-size: 14px; margin-left: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
.card { border: 1px solid #E4D8FF; border-radius: 12px; padding: 10px; text-align: center; break-inside: avoid; }
.card img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; background: #F7F3FF; }
.name { font-size: 14px; margin-top: 6px; }
.price { font-size: 22px; font-weight: 700; color: #7C3AED; }
.fandom { font-size: 12px; color: #6B5B85; }
.out { opacity: .45; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.tile { border: 1px solid #E4D8FF; border-radius: 12px; padding: 10px 14px; }
.tile .label { font-size: 13px; color: #6B5B85; }
.tile .value { font-size: 24px; font-weight: 700; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #EDE4FF; }
th { color: #6B5B85; font-weight: 600; }
td.num, th.num { text-align: right; }
.foot { margin-top: 22px; font-size: 12px; color: #6B5B85; }
@media print { body { background: #fff; padding: 0; } .sheet { padding: 0; border-radius: 0; } }
"""


def _page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{escape(title)}</title>"
            f"<style>{PAGE_CSS}</style></head><body><div class='sheet'>{body}</div></body></html>")


def _title(text, logo_b64=""):
    """The page heading, with the round avatar beside it when there is one."""
    logo = f"<img class='logo' src='data:image/png;base64,{logo_b64}' alt=''>" if logo_b64 else ""
    return f"<div class='head'>{logo}<h1>{escape(text)}</h1></div>"


def _money(currency, x):
    return f"{currency}{x:,.2f}"


def price_list_html(items, deals, photos, currency, title="Price list", subtitle="", group_by="type",
                    with_photos=True, hide_sold_out=True, logo_b64=""):
    """A printable price list of the items for sale, grouped by type or fandom, with deals and photos.

    photos: {item_id: base64 JPEG}; logo_b64: base64 PNG shown beside the title. Returns the HTML page.
    """
    shown = items[items["active"]]
    if hide_sold_out:
        shown = shown[shown["stock"] > 0]
    deal_text = {}
    for d in deals.itertuples():
        deal_text.setdefault(d.type, []).append(f"{d.qty} for {_money(currency, d.price)}")
    key = "type" if group_by == "type" else "fandom"
    parts = [_title(title, logo_b64)] + ([f"<p class='sub'>{escape(subtitle)}</p>"] if subtitle else [])
    for group, rows in shown.sort_values([key, "name"]).groupby(key, sort=False):
        heading = escape(group or "Other")
        if key == "type" and group in deal_text:
            heading += "".join(f"<span class='deal'>{escape(t)}</span>" for t in deal_text[group])
        cards = []
        for it in rows.itertuples():
            img = (f"<img src='data:image/jpeg;base64,{photos[it.item_id]}' alt=''>"
                   if with_photos and it.item_id in photos else "")
            extra = escape(it.fandom) if key == "type" else escape(it.type)
            cards.append(f"<div class='card{' out' if it.stock <= 0 else ''}'>{img}"
                         f"<div class='name'>{escape(it.name)}</div>"
                         f"<div class='price'>{_money(currency, it.price)}</div>"
                         f"<div class='fandom'>{extra}</div></div>")
        parts.append(f"<h2>{heading}</h2><div class='grid'>{''.join(cards)}</div>")
    return _page(title, "".join(parts))


def event_report_html(event, sales, items, events, event_costs, requests, currency, logo_b64=""):
    """A one-page summary of one event: money, best sellers, fandoms, payments, gifts, costs, requests."""
    ev_sales = sales[sales["event"] == event]
    h = insights.headline(ev_sales)
    row = events[events["name"] == event].iloc[0] if (events["name"] == event).any() else None
    costs = event_costs[event_costs["event"] == event]
    spent = costs["amount"].sum()
    profit = h["revenue"] - h["cost"] - spent
    m = lambda x: _money(currency, x)

    tiles = [("Sales", m(h["revenue"])), ("Orders", h["orders"]), ("Average order", m(h["avg_order"])),
             ("Pieces sold", h["items"]), ("Event costs", m(spent)), ("Profit after costs", m(profit))]
    first_day, last_day = insights.event_dates(events, event)
    when = f"{first_day} to {last_day}" if first_day != last_day else first_day
    sub = " · ".join(x for x in [when, row["location"] if row is not None else ""] if x)
    parts = [_title(event, logo_b64) if logo_b64 else _title(f"📄 {event}"),
             f"<p class='sub'>{escape(sub)}</p>" if sub else "",
             "<div class='tiles'>" + "".join(f"<div class='tile'><div class='label'>{k}</div>"
                                              f"<div class='value'>{v}</div></div>" for k, v in tiles) + "</div>"]

    def table(df, cols):
        """An HTML table; cols = [(column, title, kind)] where kind is "text", "num" or "money"."""
        cell = {"text": lambda v: escape(str(v)), "num": lambda v: f"{v:,.0f}", "money": m}
        head = "".join(f"<th class='{'' if kind == 'text' else 'num'}'>{escape(title)}</th>"
                       for _, title, kind in cols)
        body = "".join("<tr>" + "".join(f"<td class='{'' if kind == 'text' else 'num'}'>{cell[kind](r[col])}</td>"
                                        for col, _, kind in cols) + "</tr>" for _, r in df.iterrows())
        return f"<table><tr>{head}</tr>{body}</table>"

    first, last = insights.event_dates(events, event)
    if first != last:
        days = insights.by_day(ev_sales, first)
        if not days.empty:
            parts += ["<h2>By day</h2>", table(days, [("label", "Day", "text"), ("date", "Date", "text"),
                                                      ("orders", "Orders", "num"), ("sold", "Pieces", "num"),
                                                      ("revenue", "Sales", "money")])]
    perf = insights.item_performance(ev_sales, items)
    perf = perf[perf["sold"] > 0].head(10)
    if not perf.empty:
        parts += ["<h2>Best sellers</h2>", table(perf, [("name", "Item", "text"), ("sold", "Sold", "num"),
                                                         ("revenue", "Sales", "money")])]
    fd = insights.by_fandom(ev_sales, items)
    if not fd.empty:
        parts += ["<h2>By fandom</h2>", table(fd, [("fandom", "Fandom", "text"), ("sold", "Pieces", "num"),
                                                    ("revenue", "Sales", "money")])]
    pay = insights.by_payment(ev_sales)
    pay["payment"] = pay["payment"].map(PAYMENT_NAMES).fillna(pay["payment"])
    if not pay.empty:
        parts += ["<h2>Payments</h2>", table(pay, [("payment", "Paid by", "text"), ("orders", "Orders", "num"),
                                                    ("revenue", "Amount", "money")])]
    gifts = ev_sales[ev_sales["freebie"]]
    swaps = insights.traded(ev_sales)
    disc = ev_sales["discount"].sum()
    if not gifts.empty or disc or not swaps.empty:
        parts.append("<h2>Gifts, trades & discounts</h2><p>"
                     + (f"{int(gifts['qty'].sum())} free gifts given. " if not gifts.empty else "")
                     + (f"{int(swaps['qty'].sum())} pieces traded with other artists. " if not swaps.empty else "")
                     + (f"{m(disc)} in discounts." if disc else "") + "</p>")
    if not costs.empty:
        parts += ["<h2>Event costs</h2>", table(costs, [("category", "What", "text"), ("note", "Note", "text"),
                                                         ("amount", "Amount", "money")])]
    asked = insights.group_requests(requests[requests["event"] == event]) if requests is not None else pd.DataFrame()
    if not asked.empty:
        parts += ["<h2>Customer requests</h2>", table(asked, [("subject", "What", "text"), ("fandom", "Fandom", "text"),
                                                               ("type", "Type", "text"), ("asks", "Asked", "num")])]
    parts.append("<p class='foot'>Profit = sales − cost to make (incl. free gifts) − event costs. "
                 "Made with Booth Tracker.</p>")
    return _page(f"{event} report", "".join(parts))
