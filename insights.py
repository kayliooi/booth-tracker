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
    """Sales rows that were paid for (free gifts excluded)."""
    return sales[~sales["freebie"]]


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


def restock_forecast(sales, items, events, buffer=1.25):
    """A simple "what to bring next time" guess per item that has sold before.

    Average pieces sold per event (counting events from the item's first sale onwards), plus a
    25% buffer, compared with stock on hand. It's an average of the past, not a guarantee.
    """
    p = paid(sales)
    if p.empty:
        return pd.DataFrame(columns=["name", "avg_per_event", "bring", "stock", "reprint"])
    dates = dict(zip(events["name"], events["date"]))
    event_dates = sorted({dates.get(e, "") for e in p["event"].unique()})
    rows = []
    for item_id, group in p.groupby("item_id"):
        first = min(dates.get(e, "") for e in group["event"].unique())
        n_events = sum(1 for d in event_dates if d >= first) or 1
        avg = group["qty"].sum() / n_events
        rows.append({"item_id": item_id, "avg_per_event": avg, "bring": math.ceil(avg * buffer)})
    out = pd.DataFrame(rows).merge(items[["item_id", "name", "stock"]], on="item_id")
    out["reprint"] = (out["bring"] - out["stock"].clip(lower=0)).clip(lower=0)
    return out.sort_values(["reprint", "avg_per_event"], ascending=False)


def group_requests(requests):
    """Open customer requests grouped by what was asked (same subject + fandom + type, ignoring case).

    Returns one row per request with: key, subject, fandom, type, asks, online (asks from the public idea
    page), events, last asked, notes, contacts (names/@handles who asked), ids; most asked first.
    """
    cols = ["key", "subject", "fandom", "type", "asks", "online", "events", "last", "notes", "contacts", "ids"]
    open_ = requests[requests["status"].isin(["", "open"])]
    if open_.empty:
        return pd.DataFrame(columns=cols)
    open_ = open_.assign(key=open_["subject"].str.strip().str.lower() + "|" + open_["fandom"].str.strip().str.lower()
                         + "|" + open_["type"].str.strip().str.lower()).sort_values("timestamp")
    out = (open_.groupby("key", as_index=False, sort=False)
           .agg(subject=("subject", "first"), fandom=("fandom", "first"), type=("type", "first"),
                asks=("request_id", "count"), online=("source", lambda s: int((s == "online").sum())),
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


def heatmap(df, currency):
    """Fandom x product type grid, darker = more sales. Gaps between cells in the page colour."""
    chart = (alt.Chart(df).mark_rect(cornerRadius=4, stroke="#F7F3FF", strokeWidth=2)
             .encode(x=alt.X("type:N", title=None, axis=alt.Axis(labelAngle=-35, labelLimit=100)),
                     y=alt.Y("fandom:N", title=None),
                     color=alt.Color("revenue:Q", title=f"Sales ({currency})",
                                     scale=alt.Scale(range=HEAT),
                                     legend=alt.Legend(orient="bottom", gradientLength=180)),
                     tooltip=[alt.Tooltip("fandom:N", title="Fandom"), alt.Tooltip("type:N", title="Type"),
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
items. Prices are in the currency shown.

Reply in short Markdown for a phone screen, about 300-450 words, with these sections:
### What's working
### What to draw next
(3-5 concrete artwork ideas: character + concept + product type, tied to what sells, to a gap, or to
customer requests - weigh requests by how often they were asked)
### Stock for the next event
### Pricing, deals & freebies
### One experiment to try"""


def ai_brief(sales, items, events, deals, rules, artworks, currency, scope, requests=None, event_costs=None):
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
    lines += ["", "Sales by fandom x type (revenue, pieces):"]
    lines += [f"- {r.fandom} / {r.type}: {r.revenue:.2f}, {r.sold}"
              for r in fandom_by_type(sales, items).sort_values("revenue", ascending=False).itertuples()]
    lines += ["", "Items (fandom | type | name | price | sold | stock left | sell-through | profit):"]
    prices = dict(zip(items["item_id"], items["price"]))
    lines += [f"- {r.fandom or '-'} | {r.type or '-'} | {r.name} | {prices.get(r.item_id, 0):.2f} | {r.sold} | "
              f"{r.stock} | {r.sell_through:.0%} | {r.profit:.2f}" for r in perf.itertuples()]
    hours = by_hour(sales)
    if not hours.empty:
        lines += ["", "Orders by hour: " + ", ".join(f"{r.hour}:00={r.orders}" for r in hours.itertuples())]
    lines += ["", "Deals: " + (", ".join(f"{d.qty} {d.type} for {d.price:.2f}" for d in deals.itertuples()) or "none")]
    lines += ["Free gift rules: " + (", ".join(f"spend {r.min_spend:.2f} -> {r.count} gift(s)"
                                               for r in rules.itertuples()) or "none")]
    gifts = sales[sales["freebie"]]
    if not gifts.empty:
        lines += [f"Free gifts given: {int(gifts['qty'].sum())}"]
    upcoming = events[events["date"] >= pd.Timestamp.today().strftime("%Y-%m-%d")]
    lines += ["", "Upcoming events: " + (", ".join(f"{e.name} ({e.date})" for e in upcoming.itertuples()) or "none")]
    if not artworks.empty:
        lines += ["Artworks in progress: " + ", ".join(f"{a.title} [{a.fandom or '-'}, {a.stage}]"
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
