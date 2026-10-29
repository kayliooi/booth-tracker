"""Sales insights for the Insights tab: summaries, charts, a simple restock forecast and AI suggestions.

Everything here works on the DataFrames from storage.py; nothing is saved.
"""
import math

import altair as alt
import pandas as pd

# Chart colours. Bars use one violet (single series); the heatmap uses a one-hue violet ramp,
# light -> dark, checked with the dataviz palette validator against the lavender page:
# lightness monotone, visible steps, lightest step 2.1:1 on the page.
VIOLET = "#7C3AED"
HEAT = ["#B79CF8", "#9A6EF2", "#7C3AED", "#6527D3", "#4C1D95"]
INK, MUTED, GRID = "#2E1A47", "#6B5B85", "#E6DCFA"


# ---- numbers ----
def paid(sales):
    """Sales rows that were paid for (free gifts and trades excluded)."""
    return sales[~sales["freebie"] & (sales["payment"] != "trade")]


def traded(sales):
    """Sales rows for items traded away with other artists (no money, but they left stock)."""
    return sales[sales["payment"] == "trade"]


def headline(sales):
    """Key numbers for a set of sales rows: revenue, orders, average order, items per order, profit."""
    p = paid(sales)
    orders = p["order_id"].nunique()
    cost = (sales["qty"] * sales["unit_cost"]).sum()
    return {"revenue": p["total"].sum(), "orders": orders, "items": int(p["qty"].sum()),
            "avg_order": p["total"].sum() / orders if orders else 0.0,
            "items_per_order": p["qty"].sum() / orders if orders else 0.0,
            "cost": cost, "profit": p["total"].sum() - cost}


def with_type(sales, items):
    """Sales rows with the item's type added ("Other" when unknown) and blank fandoms as "Other"."""
    types = dict(zip(items["item_id"], items["type"]))
    return sales.assign(type=sales["item_id"].map(types).fillna("").replace("", "Other"),
                        fandom=sales["fandom"].replace("", "Other"))


def by_fandom(sales, items):
    """Revenue and pieces sold per fandom, biggest first."""
    p = with_type(paid(sales), items)
    return (p.groupby("fandom", as_index=False).agg(revenue=("total", "sum"), sold=("qty", "sum"))
            .sort_values("revenue", ascending=False))


def fandom_by_type(sales, items):
    """Revenue and pieces sold for every fandom x product type that sold something."""
    p = with_type(paid(sales), items)
    return p.groupby(["fandom", "type"], as_index=False).agg(revenue=("total", "sum"), sold=("qty", "sum"))


def by_event(sales, events, event_costs=None):
    """Per event (oldest first): date, revenue, pieces sold, orders, average order, and money.

    goods = cost to make what left the table (free gifts included); costs = event costs (table fee,
    travel...); profit = revenue - goods - costs.
    """
    p = paid(sales)
    out = (p.groupby("event", as_index=False)
           .agg(revenue=("total", "sum"), sold=("qty", "sum"), orders=("order_id", "nunique")))
    out["avg_order"] = out["revenue"] / out["orders"]
    out["date"] = out["event"].map(dict(zip(events["name"], events["date"]))).fillna("")
    goods = (sales["qty"] * sales["unit_cost"]).groupby(sales["event"]).sum()
    out["goods"] = out["event"].map(goods).fillna(0.0)
    costs = (event_costs.groupby("event")["amount"].sum() if event_costs is not None and not event_costs.empty
             else pd.Series(dtype=float))
    out["costs"] = out["event"].map(costs).fillna(0.0)
    out["profit"] = out["revenue"] - out["goods"] - out["costs"]
    return out.sort_values("date")


def event_dates(events, event):
    """(first day, last day) of an event as "YYYY-MM-DD" strings; last = first for one-day events.

    ("", "") if the event is unknown or has no date.
    """
    row = events[events["name"] == event]
    if row.empty or not row.iloc[0]["date"]:
        return "", ""
    first = str(row.iloc[0]["date"])[:10]
    last = str(row.iloc[0].get("end_date", "") or "")[:10]
    return first, max(first, last) if last else first


def day_number(timestamp, first_day):
    """Which day of the event a sale happened on: 1 for the first day, 2 for the next... (0 if unknown)."""
    try:
        return (pd.Timestamp(str(timestamp)[:10]) - pd.Timestamp(first_day)).days + 1
    except (ValueError, TypeError):
        return 0


def by_day(sales, first_day):
    """Per event day (from the sale times): day number, date, revenue, orders and pieces sold."""
    p = paid(sales)
    if p.empty or not first_day:
        return pd.DataFrame(columns=["day", "label", "date", "revenue", "orders", "sold"])
    p = p.assign(date=p["timestamp"].str[:10])
    out = (p.groupby("date", as_index=False)
           .agg(revenue=("total", "sum"), orders=("order_id", "nunique"), sold=("qty", "sum")))
    out["day"] = [day_number(d, first_day) for d in out["date"]]
    out["label"] = [f"Day {d}" if d > 0 else "Before" for d in out["day"]]
    return out.sort_values("date")[["day", "label", "date", "revenue", "orders", "sold"]]


def by_payment(sales):
    """Money and orders per payment method (blank = recorded before payment methods existed)."""
    p = paid(sales)
    return (p.assign(payment=p["payment"].replace("", "unknown"))
            .groupby("payment", as_index=False).agg(revenue=("total", "sum"), orders=("order_id", "nunique")))


def by_hour(sales):
    """Number of orders started in each hour of the day (from the sale timestamps)."""
    p = paid(sales)
    first = p.groupby("order_id")["timestamp"].min()
    hours = pd.to_datetime(first, errors="coerce").dt.hour.dropna().astype(int)
    return hours.value_counts().rename_axis("hour").reset_index(name="orders").sort_values("hour")


def item_performance(sales, items):
    """Per item: sold, revenue, profit, stock left and sell-through (sold / (sold + stock left))."""
    p = paid(sales)
    costs = (sales.assign(cost=sales["qty"] * sales["unit_cost"]).groupby("item_id", as_index=False)
             .agg(cost=("cost", "sum")))                    # includes free gifts given away
    sold = p.groupby("item_id", as_index=False).agg(sold=("qty", "sum"), revenue=("total", "sum"))
    out = (items[["item_id", "name", "fandom", "type", "stock"]]
           .merge(sold, on="item_id", how="left").merge(costs, on="item_id", how="left").fillna(
               {"sold": 0, "revenue": 0.0, "cost": 0.0}))
    out["sold"] = out["sold"].astype(int)
    out["profit"] = out["revenue"] - out["cost"]
    total = out["sold"] + out["stock"].clip(lower=0)
    out["sell_through"] = (out["sold"] / total.where(total > 0)).fillna(0.0)
    return out.sort_values(["sold", "revenue"], ascending=False)


# ---- themes and seasons ----
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def tags(text):
    """Theme names from a comma-separated cell, e.g. "Xmas, Couple" -> ["Xmas", "Couple"]."""
    return [t.strip() for t in str(text or "").split(",") if t.strip()]


def is_festive(theme):
    """True for a theme with a season (from/to month set), e.g. Xmas; False for all-year ones like Gym."""
    return theme["from_month"] in MONTHS and theme["to_month"] in MONTHS


def season(theme, day):
    """The current or next season of a festive theme as (first day, last day) dates, seen from `day`.

    Seasons are whole months and can wrap past New Year (e.g. Dec-Jan). None for all-year themes.
    """
    if not is_festive(theme):
        return None
    m1, m2 = MONTHS.index(theme["from_month"]) + 1, MONTHS.index(theme["to_month"]) + 1
    for year in (day.year - 1, day.year, day.year + 1):
        start = pd.Timestamp(year=year, month=m1, day=1)
        end = (pd.Timestamp(year=year + (m2 < m1), month=m2, day=1) + pd.offsets.MonthEnd(0))
        if end.date() >= day:
            return start.date(), end.date()
    return None


def season_status(themes, day, soon_days=70):
    """Festive themes that are in season on `day` or start within `soon_days`, soonest first.

    One dict per theme: name, emoji, start, end, now (in season), days (until it starts; 0 when now).
    """
    out = []
    for t in themes.to_dict("records"):
        found = season(t, day)
        if found:
            start, end = found
            days = max((start - day).days, 0)
            if days <= soon_days:
                out.append({**t, "start": start, "end": end, "now": start <= day, "days": days})
    return sorted(out, key=lambda s: s["days"])


def off_season_items(items, themes, day, lead_days=45):
    """Item ids whose festive themes are all out of season on `day` (and not starting within `lead_days`).

    Items without festive themes (untagged, or only all-year themes like Gym) are never off-season.
    """
    festive = {t["name"]: t for t in themes.to_dict("records") if is_festive(t)}
    off = set()
    for item_id, cell in zip(items["item_id"], items["themes"]):
        mine = [festive[t] for t in tags(cell) if t in festive]
        if mine and all((season(t, day)[0] - day).days > lead_days for t in mine):
            off.add(item_id)
    return off


def _theme_rows(sales, items):
    """Paid sales rows, one per theme of the item sold (in a "theme" column); untagged items left out.

    Themes come from the item now, so tagging an item also counts its earlier sales.
    """
    p = paid(sales)
    item_tags = {i: tags(t) for i, t in zip(items["item_id"], items["themes"])}
    return (p.assign(theme=p["item_id"].map(item_tags), fandom=p["fandom"].replace("", "Other"))
            .explode("theme").dropna(subset=["theme"]))


def by_theme(sales, items):
    """Revenue and pieces sold per theme, biggest first (an item with two themes counts in both)."""
    return (_theme_rows(sales, items).groupby("theme", as_index=False)
            .agg(revenue=("total", "sum"), sold=("qty", "sum")).sort_values("revenue", ascending=False))


def fandom_by_theme(sales, items):
    """Revenue and pieces sold for every fandom x theme that sold something."""
    return (_theme_rows(sales, items).groupby(["fandom", "theme"], as_index=False)
            .agg(revenue=("total", "sum"), sold=("qty", "sum")))


OPEN_ORDER_STATUSES = ("taken", "making", "ready")


def order_lines(preorders, lines=None):
    """Every pre-order's items as rows of preorder_id, item_id, qty.

    New orders keep their items in the "preorder_lines" table; older single-item orders kept one item in
    preorders.item_id, which is used when an order has no lines. Commissions have no lines.
    """
    lines = lines if lines is not None else pd.DataFrame(columns=["preorder_id", "item_id", "qty"])
    older = preorders[(preorders["item_id"] != "") & ~preorders["preorder_id"].isin(lines["preorder_id"])]
    return pd.concat([lines[["preorder_id", "item_id", "qty"]], older[["preorder_id", "item_id", "qty"]]],
                     ignore_index=True)


def reserved_stock(preorders, lines=None):
    """Pieces of existing items promised to open pre-orders: {item_id: qty}. Not for sale at the booth."""
    open_ids = preorders.loc[preorders["status"].isin(OPEN_ORDER_STATUSES), "preorder_id"]
    held = order_lines(preorders, lines)
    held = held[held["preorder_id"].isin(open_ids) & (held["item_id"] != "")]
    return held.groupby("item_id")["qty"].sum().astype(int).to_dict()


def restock_forecast(sales, items, events, buffer=1.25, reserved=None, off_season=frozenset()):
    """A simple "what to bring next time" guess per item that has sold before.

    Average pieces sold per event (counting events from the item's first sale onwards), plus a
    25% buffer, compared with stock on hand minus pieces reserved for pre-orders ({item_id: qty}).
    Items in `off_season` (ids, see off_season_items) get no reprint suggestion, only their reserved pieces.
    It's an average of the past, not a guarantee.
    """
    p = paid(sales)
    if p.empty:
        return pd.DataFrame(columns=["name", "avg_per_event", "bring", "stock", "reserved", "reprint",
                                     "off_season"])
    dates = dict(zip(events["name"], events["date"]))
    sale_dates = sorted({dates.get(e, "") for e in p["event"].unique()})
    rows = []
    for item_id, group in p.groupby("item_id"):
        first = min(dates.get(e, "") for e in group["event"].unique())
        n_events = sum(1 for d in sale_dates if d >= first) or 1
        avg = group["qty"].sum() / n_events
        rows.append({"item_id": item_id, "avg_per_event": avg, "bring": math.ceil(avg * buffer)})
    out = pd.DataFrame(rows).merge(items[["item_id", "name", "stock"]], on="item_id")
    out["reserved"] = out["item_id"].map(reserved or {}).fillna(0).astype(int)
    out["off_season"] = out["item_id"].isin(off_season)
    bring = out["bring"].where(~out["off_season"], 0)
    out["reprint"] = (bring + out["reserved"] - out["stock"].clip(lower=0)).clip(lower=0)
    return out.sort_values(["reprint", "avg_per_event"], ascending=False)


def request_key(subject, fandom, mtype):
    """Grouping key for requests asking for the same thing (subject|fandom|type, ignoring case and spaces).

    Works on single strings or on whole columns (pandas Series).
    """
    norm = (lambda s: s.str.strip().str.lower()) if isinstance(subject, pd.Series) else (lambda s: s.strip().lower())
    return norm(subject) + "|" + norm(fandom) + "|" + norm(mtype)


def group_requests(requests):
    """Open customer requests grouped by what was asked (same subject + fandom + type, ignoring case).

    Returns one row per request with: key, subject, fandom, type, asks, online (asks from the public idea
    page), events, last asked, notes, contacts (names/@handles who asked), ids; most asked first.
    """
    cols = ["key", "subject", "fandom", "type", "asks", "online", "events", "last", "notes", "contacts", "ids"]
    open_ = requests[requests["status"].isin(["", "open"])]
    if open_.empty:
        return pd.DataFrame(columns=cols)
    open_ = open_.assign(key=request_key(open_["subject"], open_["fandom"], open_["type"])).sort_values("timestamp")
    out = (open_.groupby("key", as_index=False, sort=False)
           .agg(subject=("subject", "first"), fandom=("fandom", "first"), type=("type", "first"),
                asks=("request_id", "count"),
                online=("source", lambda s: int(s.str.startswith("online").sum())),     # ideas + 👍 votes
                events=("event", lambda e: ", ".join(dict.fromkeys(x for x in e if x))),
                last=("timestamp", "max"), notes=("notes", lambda n: "; ".join(dict.fromkeys(x for x in n if x))),
                contacts=("contact", lambda c: ", ".join(dict.fromkeys(x for x in c if x))),
                ids=("request_id", list)))
    return out.sort_values(["asks", "last"], ascending=False)[cols]


# ---- charts ----
def _style(chart):
    """Quiet chart styling: transparent background, hairline grid, muted axis text."""
    return (chart.properties(background="transparent")
            .configure(font="'Source Sans Pro', 'Source Sans 3', sans-serif")
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor=GRID, domainColor=GRID,
                            tickColor=GRID, labelFontSize=12, titleFontSize=12, titleFontWeight="normal",
                            labelLimit=160)
            .configure_legend(labelColor=MUTED, titleColor=MUTED, titleFontWeight="normal"))


def _money_axis(currency, title):
    return alt.Axis(title=title, format=",.0f", labelExpr=f"'{currency}' + format(datum.value, ',.0f')",
                    tickCount=4)


def bar_chart(df, category, value, currency, value_title, order=None):
    """Horizontal bars, one violet: magnitude per category (sorted biggest first unless `order` given)."""
    sort = order if order is not None else "-x"
    tooltip = [alt.Tooltip(f"{category}:N", title=category.title()),
               alt.Tooltip(f"{value}:Q", title=value_title, format=",.2f")]
    if "sold" in df.columns and value != "sold":
        tooltip.append(alt.Tooltip("sold:Q", title="Pieces sold"))
    chart = (alt.Chart(df).mark_bar(color=VIOLET, cornerRadiusEnd=4, height=16)
             .encode(y=alt.Y(f"{category}:N", sort=sort, title=None),
                     x=alt.X(f"{value}:Q", axis=_money_axis(currency, value_title)),
                     tooltip=tooltip)
             .properties(height=max(80, 34 * len(df))))
    return _style(chart)


def heatmap(df, currency, column="type"):
    """Fandom x product type (or x theme, column="theme") grid, darker = more sales.

    Gaps between cells in the page colour.
    """
    chart = (alt.Chart(df).mark_rect(cornerRadius=4, stroke="#F7F3FF", strokeWidth=2)
             .encode(x=alt.X(f"{column}:N", title=None, axis=alt.Axis(labelAngle=-35, labelLimit=100)),
                     y=alt.Y("fandom:N", title=None),
                     color=alt.Color("revenue:Q", title=f"Sales ({currency})",
                                     scale=alt.Scale(range=HEAT),
                                     legend=alt.Legend(orient="bottom", gradientLength=180)),
                     tooltip=[alt.Tooltip("fandom:N", title="Fandom"),
                              alt.Tooltip(f"{column}:N", title=column.title()),
                              alt.Tooltip("revenue:Q", title=f"Sales ({currency})", format=",.2f"),
                              alt.Tooltip("sold:Q", title="Pieces sold")])
             .properties(height=alt.Step(36)))                 # 36 px per fandom row
    return _style(chart)


def hour_chart(df):
    """Orders per hour of the day, one violet."""
    chart = (alt.Chart(df).mark_bar(color=VIOLET, cornerRadiusEnd=4, size=18)
             .encode(x=alt.X("hour:O", title="Hour of day", axis=alt.Axis(labelAngle=0)),
                     y=alt.Y("orders:Q", title="Orders", axis=alt.Axis(tickMinStep=1, tickCount=4)),
                     tooltip=[alt.Tooltip("hour:O", title="Hour"), alt.Tooltip("orders:Q", title="Orders")])
             .properties(height=180))
    return _style(chart)


# ---- AI suggestions (Claude) ----
AI_MODEL = "claude-opus-5-5"
AI_SYSTEM = """You are a friendly, practical business coach for an independent artist who sells \
fan-art merch (stickers, prints, sticker sheets) at conventions and art markets in Southeast Asia. \
You get a summary of their sales, stock, deals, free gifts and the artworks they are working on.

Give advice grounded in their numbers. When there is little data (few events or sales), say how \
confident you are and keep suggestions small and testable. Name specific fandoms, product types and \
items. Prices are in the currency shown. Items and artworks can have theme tags: festive themes with a \
season (e.g. CNY, Halloween, Xmas) and all-year ones (e.g. Gym, Couple). Use upcoming seasons when \
suggesting what to draw and bring, allowing a few weeks to draw and print.

Reply in short Markdown for a phone screen, about 300-450 words, with these sections:
### What's working
### What to draw next
(3-5 concrete artwork ideas: character + concept + product type, tied to what sells, to a gap, or to
customer requests - weigh requests by how often they were asked)
### Stock for the next event
### Pricing, deals & freebies
### One experiment to try"""


def ai_brief(sales, items, events, deals, rules, artworks, currency, scope, requests=None, event_costs=None,
             themes=None):
    """A compact text summary of the shop for the AI (no customer details are stored or sent)."""
    h = headline(sales)
    perf = item_performance(sales, items)
    lines = [f"Scope: {scope}. Currency: {currency}.",
             f"Revenue {h['revenue']:.2f}, orders {h['orders']}, pieces sold {h['items']}, "
             f"average order {h['avg_order']:.2f}, items per order {h['items_per_order']:.1f}, "
             f"cost of goods {h['cost']:.2f}, profit {h['profit']:.2f}.",
             "", "Events (date, revenue, pieces, orders, cost of goods, event costs, profit after all costs):"]
    lines += [f"- {r.event} ({r.date}): {r.revenue:.2f}, {r.sold}, {r.orders}, {r.goods:.2f}, {r.costs:.2f}, "
              f"{r.profit:.2f}" for r in by_event(sales, events, event_costs).itertuples()]
    for name in events["name"]:
        first, last = event_dates(events, name)
        days = by_day(sales[sales["event"] == name], first)
        if first != last and len(days) > 1:
            lines.append(f"  {name} by day: " + ", ".join(f"{d.label} {d.revenue:.2f} ({d.orders} orders)"
                                                         for d in days.itertuples()))
    lines += ["", "Sales by fandom x type (revenue, pieces):"]
    lines += [f"- {r.fandom} / {r.type}: {r.revenue:.2f}, {r.sold}"
              for r in fandom_by_type(sales, items).sort_values("revenue", ascending=False).itertuples()]
    lines += ["", "Items (fandom | type | themes | name | price | sold | stock left | sell-through | profit):"]
    prices = dict(zip(items["item_id"], items["price"]))
    item_themes = dict(zip(items["item_id"], items["themes"]))
    lines += [f"- {r.fandom or '-'} | {r.type or '-'} | {item_themes.get(r.item_id) or '-'} | {r.name} | "
              f"{prices.get(r.item_id, 0):.2f} | {r.sold} | {r.stock} | {r.sell_through:.0%} | {r.profit:.2f}"
              for r in perf.itertuples()]
    if themes is not None and not themes.empty:
        lines += ["", "Themes (season months or all-year): " + ", ".join(
            f"{t.name} ({t.from_month}-{t.to_month})" if is_festive(t._asdict()) else f"{t.name} (all-year)"
            for t in themes.itertuples())]
        theme_sales = by_theme(sales, items)
        if not theme_sales.empty:
            lines += ["Sales by theme (revenue, pieces): " + ", ".join(
                f"{r.theme} {r.revenue:.2f} ({r.sold})" for r in theme_sales.itertuples())]
        coming = season_status(themes, pd.Timestamp.today().date(), soon_days=120)
        if coming:
            lines += ["Seasons now or coming up: " + ", ".join(
                f"{s['name']} (now, until {s['end']})" if s["now"] else f"{s['name']} (starts {s['start']})"
                for s in coming)]
    hours = by_hour(sales)
    if not hours.empty:
        lines += ["", "Orders by hour: " + ", ".join(f"{r.hour}:00={r.orders}" for r in hours.itertuples())]
    lines += ["", "Deals: " + (", ".join(f"{d.qty} {d.type} for {d.price:.2f}" for d in deals.itertuples()) or "none")]
    lines += ["Free gift rules: " + (", ".join(f"spend {r.min_spend:.2f} -> {r.count} gift(s)"
                                               for r in rules.itertuples()) or "none")]
    gifts = sales[sales["freebie"]]
    if not gifts.empty:
        lines += [f"Free gifts given: {int(gifts['qty'].sum())}"]
    swaps = traded(sales)
    if not swaps.empty:
        lines += [f"Traded away with other artists (not sales): {int(swaps['qty'].sum())} pieces"]
    upcoming = events[events["date"] >= pd.Timestamp.today().strftime("%Y-%m-%d")]
    lines += ["", "Upcoming events: " + (", ".join(f"{e.name} ({e.date})" for e in upcoming.itertuples()) or "none")]
    if not artworks.empty:
        lines += ["Artworks in progress: " + ", ".join(
            f"{a.title} [{a.fandom or '-'}, {a.stage}" + (f", {a.themes}" if a.themes else "") + "]"
            for a in artworks.itertuples())]
    if requests is not None:
        asked = group_requests(requests)
        if not asked.empty:
            lines += ["", "Customer requests not made yet (what | fandom | merch type | times asked):"]
            lines += [f"- {r.subject} | {r.fandom or '-'} | {r.type or '-'} | {r.asks}" for r in asked.itertuples()]
    return "\n".join(lines)


def stream_claude(api_key, system, user_text):
    """Send one message to Claude and yield the reply text as it arrives (for st.write_stream).

    Uses server-side fallbacks so a rare safety-classifier false positive is retried on another
    model instead of failing; a refusal or a cut-off reply is reported at the end.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    with client.beta.messages.stream(
        model=AI_MODEL,
        max_tokens=8000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=system,
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        yield from stream.text_stream
        final = stream.get_final_message()
    if final.stop_reason == "refusal":
        yield "\n\n_Claude declined to answer this one. Try rephrasing your question._"
    elif final.stop_reason == "max_tokens":
        yield "\n\n_(The answer was cut off.)_"


def stream_suggestions(api_key, brief, question=""):
    """Ask Claude for business suggestions based on the shop summary."""
    ask = question.strip() or "What should I focus on next?"
    yield from stream_claude(api_key, AI_SYSTEM, f"<shop_summary>\n{brief}\n</shop_summary>\n\n{ask}")


# ---- AI social posts ----
POST_KINDS = {
    "thanks": "🙏 Thank you after an event",
    "coming": "📣 See you at an upcoming event",
    "new": "✨ New merch announcement",
    "restock": "📦 Back in stock",
}
POST_SYSTEM = """You write social media captions for an independent artist who sells fan-art merch \
(stickers, prints) at conventions in Southeast Asia. Write in their voice: warm, excited, casual, a \
little playful, never salesy or corporate. Use a few fitting emoji. Only mention facts given to you \
(events, dates, items, prices); never invent details. Don't mention sales numbers or money earned.

Reply with exactly 2 alternative captions in Markdown, each under a short "### Option 1" / \
"### Option 2" heading, each ready to copy: the caption, then a line of 8-12 relevant hashtags \
(fandoms, product types, the event, art/convention tags). Keep each caption under 120 words."""


def post_brief(kind, platform, details, events, items, sales, event=None):
    """The facts for a social post: what kind, which platform, the event and the merch to feature."""
    lines = [f"Post type: {POST_KINDS[kind]}", f"Platform: {platform}"]
    if event:
        e = events[events["name"] == event]
        if not e.empty:
            e = e.iloc[0]
            lines.append(f"Event: {event}" + (f", {e['date']}" if e["date"] else "")
                         + (f", at {e['location']}" if e.get("location") else ""))
        if kind == "thanks":
            best = item_performance(sales[sales["event"] == event], items).query("sold > 0").head(3)
            if not best.empty:
                lines.append("Crowd favourites at this event: " + ", ".join(best["name"]))
    on_sale = items[items["active"] & (items["stock"] > 0)]
    lines.append("Merch available (name | fandom | price): " + "; ".join(
        f"{r.name} | {r.fandom or '-'} | {r.price:.2f}" for r in on_sale.itertuples()))
    if details.strip():
        lines.append(f"Extra details from the artist: {details.strip()}")
    return "\n".join(lines)


def stream_post(api_key, brief):
    """Ask Claude for two caption options for a social post."""
    yield from stream_claude(api_key, POST_SYSTEM, f"<post_facts>\n{brief}\n</post_facts>\n\nWrite the captions.")
