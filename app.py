"""Art booth tracker: inventory and sales, tagged by event. Built for phone screens."""
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from pricing import price_basket
from storage import CsvStore, SheetsStore

# ---- settings ----
CURRENCY = "$"
TIMEZONE = "Asia/Singapore"
LOW_STOCK = 3          # warn when stock is at or below this

st.set_page_config(page_title="Booth Tracker", page_icon="🎨", layout="centered")
st.html(f"<style>{(Path(__file__).parent / 'styles' / 'app.css').read_text(encoding='utf-8')}</style>")


def _secret(key):
    """Return a value from Streamlit secrets, or None if it isn't set (e.g. running locally)."""
    try:
        return st.secrets[key]
    except Exception:
        return None


# ---- password gate (set app_password in secrets) ----
password = _secret("app_password")
if password and not st.session_state.get("authed"):
    st.title("🎨 Booth Tracker")
    entered = st.text_input("Password", type="password")
    if entered == password:
        st.session_state.authed = True
        st.rerun()
    elif entered:
        st.error("Wrong password")
    st.stop()


# ---- storage ----
@st.cache_resource
def get_store():
    """Connect to the Google Sheet if secrets are set, otherwise use local CSV files in data/.

    Cached so the connection is made once and shared by all users.
    """
    creds, url = _secret("gcp_service_account"), _secret("spreadsheet_url")
    if creds and url:
        return SheetsStore(creds, url)
    return CsvStore("data")


store = get_store()


@st.cache_data(ttl=300, show_spinner=False)
def load(table):
    """Return a table ("items", "events", "sales" or "deals") as a DataFrame.

    Cached for 5 minutes to avoid hitting Google Sheets on every tap; call load.clear() after writing.
    """
    return store.load(table)


def new_id():
    """Return a short random id like "id3f9a1c2b".

    The letter prefix stops ids like "12e45678" being read as numbers (e.g. by Google Sheets).
    """
    return "id" + uuid.uuid4().hex[:8]


def now():
    """Return the current local time (TIMEZONE) as "YYYY-MM-DD HH:MM:SS"."""
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def money(x):
    """Format a number as currency, e.g. 1234.5 -> "$1,234.50"."""
    return f"{CURRENCY}{x:,.2f}"


def deal_text(qty, price):
    """Describe a deal, e.g. "3 for $5.00"."""
    return f"{qty} for {money(price)}"


# ---- basket (held per phone/browser until the sale is completed) ----
def add_to_basket(item_id):
    """Put one of an item in the basket."""
    basket = st.session_state.setdefault("basket", {})
    basket[item_id] = basket.get(item_id, 0) + 1


def remove_from_basket(item_id):
    """Take one of an item out of the basket."""
    basket = st.session_state.setdefault("basket", {})
    basket[item_id] = basket.get(item_id, 0) - 1
    if basket[item_id] <= 0:
        del basket[item_id]


def clear_basket():
    """Empty the basket without recording anything."""
    st.session_state.basket = {}


def quote_basket(basket, items, deals):
    """Price the basket with deals applied.

    Returns a dict with lines (name, qty, unit_price and the charge after deals for each item),
    applied deals, subtotal (at single prices) and total.
    """
    by_id = items.set_index("item_id")
    lines = [{"item_id": i, "name": by_id.at[i, "name"], "fandom": by_id.at[i, "fandom"],
              "type": by_id.at[i, "type"], "unit_price": float(by_id.at[i, "price"]), "qty": q}
             for i, q in basket.items() if i in by_id.index]
    charges, applied = price_basket(lines, deals.to_dict("records"))
    for line in lines:
        line["charge"] = charges[line["item_id"]]
    return {"lines": lines, "applied": applied,
            "subtotal": sum(line["unit_price"] * line["qty"] for line in lines),
            "total": round(sum(charges.values()), 2)}


# ---- actions (run as button callbacks, before the page redraws) ----
def checkout(event):
    """Record the basket as one order at an event: a sales row per item, sharing an order_id.

    Lowers stock, remembers the order for "Undo last sale" and empties the basket.
    Refuses if any item no longer has enough stock (e.g. it was sold on another phone).
    """
    items = load("items")
    quote = quote_basket(st.session_state.get("basket") or {}, items, load("deals"))
    if not quote["lines"]:
        return
    stock = items.set_index("item_id")["stock"]
    short = [f"{line['name']} ({stock[line['item_id']]} left)"
             for line in quote["lines"] if stock[line["item_id"]] < line["qty"]]
    if short:
        st.session_state.flash = ("error", "Not enough stock: " + ", ".join(short))
        return

    order_id, timestamp = new_id(), now()
    rows = []
    for line in quote["lines"]:
        items.loc[items["item_id"] == line["item_id"], "stock"] -= line["qty"]
        rows.append({"sale_id": new_id(), "order_id": order_id, "timestamp": timestamp,
                     "event": event, "item_id": line["item_id"], "item": line["name"],
                     "fandom": line["fandom"], "qty": line["qty"],
                     "unit_price": line["unit_price"], "total": line["charge"]})
    store.append_rows("sales", rows)
    store.save("items", items)
    load.clear()

    count = sum(line["qty"] for line in quote["lines"])
    st.session_state.last_order = {"order_id": order_id, "count": count,
                                   "total": quote["total"], "timestamp": timestamp}
    st.session_state.basket = {}
    st.session_state.flash = ("success", f"Sold {count} item{'s' if count != 1 else ''} "
                                         f"for {money(quote['total'])}")


def delete_order(order_id):
    """Remove an order (every item in it) and put the items back in stock.

    Used by "Undo last sale" and "Remove a sale". Does nothing if the order is already gone;
    skips restoring stock for items that no longer exist.
    """
    sales = load("sales")
    rows = sales[sales["order_id"] == order_id]
    if rows.empty:
        return
    items = load("items")
    for row in rows.itertuples():
        items.loc[items["item_id"] == row.item_id, "stock"] += int(row.qty)
    store.save("items", items)
    store.save("sales", sales[sales["order_id"] != order_id])
    load.clear()
    if (st.session_state.get("last_order") or {}).get("order_id") == order_id:
        st.session_state.last_order = None
    st.session_state.flash = ("info", f"Removed sale of {int(rows['qty'].sum())} item(s), "
                                      f"{money(rows['total'].sum())} (stock restored)")


# ---- page ----
st.title("🎨 Booth Tracker")

flash = st.session_state.pop("flash", None)
if flash:
    getattr(st, flash[0])(flash[1])

items = load("items")
events = load("events").sort_values("date", ascending=False)
sales = load("sales")
deals = load("deals")

tab_sell, tab_inv, tab_sales, tab_events = st.tabs(["🛒 Sell", "📦 Inventory", "📊 Sales", "📅 Events"])

# ---- Sell ----
with tab_sell:
    active = items[items["active"]]
    if events.empty:
        st.info("Add an event in the 📅 Events tab first.")
    elif active.empty:
        st.info("Add items in the 📦 Inventory tab first.")
    else:
        if "pending_event" in st.session_state:
            st.session_state.event = st.session_state.pop("pending_event")
        event = st.selectbox("Event", events["name"].tolist(), key="event")
        ev_sales = sales[sales["event"] == event]
        c1, c2 = st.columns(2)
        c1.metric("Event sales", money(ev_sales["total"].sum()))
        c2.metric("Items sold", int(ev_sales["qty"].sum()))

        basket = st.session_state.setdefault("basket", {})
        if basket:
            quote = quote_basket(basket, items, deals)
            with st.container(border=True):
                st.markdown("**🧺 Basket** · tap an item to take one out")
                for line in quote["lines"]:
                    st.button(f"➖ {line['qty']} × {line['name']} · {money(line['unit_price'] * line['qty'])}",
                              key=f"rm_{line['item_id']}", width="stretch",
                              on_click=remove_from_basket, args=(line["item_id"],))
                for a in quote["applied"]:
                    used = " + ".join(f"{t} × ({deal_text(q, p)})" if t > 1 else deal_text(q, p)
                                      for (q, p), t in a["used"].items())
                    st.caption(f"🎉 {a['type']}: {used} · save {money(a['saving'])}")
                st.markdown(f"### Total {money(quote['total'])}")
                st.button("✅ Complete sale", type="primary", width="stretch",
                          on_click=checkout, args=(event,))
                st.button("Clear basket", width="stretch", on_click=clear_basket)

        last = st.session_state.get("last_order")
        if last and not basket:
            st.caption(f"Last sale: {last['count']} item(s) · {money(last['total'])} · {last['timestamp'][11:16]}")
            st.button("↩️ Undo last sale", on_click=delete_order, args=(last["order_id"],),
                      width="stretch")

        fandoms = sorted(f for f in active["fandom"].unique() if f)
        pick = st.pills("Fandom", fandoms, key="fandom_filter") if len(fandoms) > 1 else None
        shown = active if not pick else active[active["fandom"] == pick]

        hints = {}                                  # type -> "3 for $5.00" shown on item buttons
        for d in deals.itertuples():
            hints.setdefault(d.type, []).append(deal_text(d.qty, d.price))

        for fandom, group in shown.sort_values(["fandom", "type", "name"]).groupby("fandom", sort=False):
            if not pick and fandoms:
                st.caption(f"**{fandom or 'Other'}**")
            for item in group.itertuples():
                in_basket = basket.get(item.item_id, 0)
                left = item.stock - in_basket
                warn = " ⚠️" if 0 < left <= LOW_STOCK else ""
                deal = f" ({', '.join(hints[item.type])})" if item.type in hints else ""
                label = f"{item.name} · {money(item.price)}{deal} · {left} left{warn}"
                if in_basket:
                    label = f"🧺{in_basket} · {label}"
                st.button(label, key=f"add_{item.item_id}", width="stretch",
                          disabled=left <= 0, on_click=add_to_basket, args=(item.item_id,))

# ---- Inventory ----
with tab_inv:
    fandom_options = sorted(f for f in items["fandom"].unique() if f)
    type_options = sorted(t for t in items["type"].unique() if t)

    with st.expander("➕ Add item", expanded=items.empty):
        with st.form("add_item", clear_on_submit=True):
            fandom = st.selectbox("Fandom", fandom_options, index=None, accept_new_options=True,
                                  placeholder="Pick or type a new one, e.g. Demon Slayer")
            item_type = st.selectbox("Type", type_options, index=None, accept_new_options=True,
                                     placeholder="Pick or type a new one, e.g. Small sticker")
            name = st.text_input("Merch name", placeholder="e.g. Small sticker - Shinobu")
            price = st.number_input(f"Single price ({CURRENCY})", min_value=0.0, step=0.5, format="%.2f")
            stock = st.number_input("Stock", min_value=0, step=1)
            if st.form_submit_button("Add item", width="stretch"):
                name = name.strip()
                if not name:
                    st.error("Merch name is required")
                elif name.lower() in items["name"].str.lower().tolist():
                    st.error(f"'{name}' already exists. Edit it below instead")
                else:
                    store.append("items", {"item_id": new_id(), "fandom": (fandom or "").strip(),
                                           "type": (item_type or "").strip(), "name": name,
                                           "price": price, "stock": int(stock), "active": True})
                    load.clear()
                    st.session_state.flash = ("success", f"Added {name}")
                    st.rerun()

    if not items.empty:
        low = items[items["active"] & (items["stock"] <= LOW_STOCK)]
        if not low.empty:
            st.warning("Low stock: " + ", ".join(f"{r.name} ({r.stock})" for r in low.itertuples()))

        st.caption("Edit directly, untick **Active** to hide an item from the Sell tab.")
        # item_id as the (hidden) index: data_editor always returns the index, so ids survive edits
        edited = st.data_editor(
            items.sort_values(["fandom", "type", "name"]).set_index("item_id"),
            column_order=["fandom", "type", "name", "price", "stock", "active"],
            column_config={
                "fandom": st.column_config.TextColumn("Fandom"),
                "type": st.column_config.TextColumn("Type"),
                "name": st.column_config.TextColumn("Merch name", required=True),
                "price": st.column_config.NumberColumn(f"Price ({CURRENCY})", min_value=0, format="%.2f"),
                "stock": st.column_config.NumberColumn("Stock", min_value=0, step=1),
                "active": st.column_config.CheckboxColumn("Active"),
            },
            hide_index=True, width="stretch", key="inv_editor",
        )
        if st.button("💾 Save changes", width="stretch"):
            if edited["name"].str.strip().eq("").any():
                st.error("Merch names can't be empty")
            else:
                store.save("items", edited.reset_index())
                load.clear()
                st.session_state.flash = ("success", "Inventory saved")
                st.rerun()

        st.subheader("🎉 Deals")
        if not type_options:
            st.info("Give items a **Type** (e.g. Small sticker) to set up deals like 3 for $5.")
        else:
            st.caption("A deal covers any mix of items of that type, e.g. any 3 Small stickers for $5. "
                       "Add a row at the bottom; select a row and press delete to remove it.")
            edited_deals = st.data_editor(
                deals, num_rows="dynamic", hide_index=True, width="stretch", key="deals_editor",
                column_config={
                    "type": st.column_config.SelectboxColumn("Type", options=type_options, required=True),
                    "qty": st.column_config.NumberColumn("Pieces", min_value=2, step=1, required=True),
                    "price": st.column_config.NumberColumn(f"For ({CURRENCY})", min_value=0,
                                                           format="%.2f", required=True),
                },
            )
            if st.button("💾 Save deals", width="stretch"):
                complete = edited_deals["type"].fillna("").ne("") & edited_deals[["qty", "price"]].notna().all(axis=1)
                store.save("deals", edited_deals[complete])
                load.clear()
                st.session_state.flash = ("success", "Deals saved")
                st.rerun()

# ---- Sales ----
with tab_sales:
    choice = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="sales_filter")
    view = sales if choice == "All events" else sales[sales["event"] == choice]

    c1, c2 = st.columns(2)
    c1.metric("Total sales", money(view["total"].sum()))
    c2.metric("Items sold", int(view["qty"].sum()))

    if view.empty:
        st.info("No sales yet.")
    else:
        total_col = st.column_config.NumberColumn("Total", format=f"{CURRENCY}%.2f")

        if view["fandom"].ne("").any():
            st.subheader("By fandom")
            by_fandom = (view.assign(fandom=view["fandom"].replace("", "Other"))
                         .groupby("fandom", as_index=False)[["qty", "total"]].sum()
                         .sort_values("total", ascending=False))
            st.dataframe(by_fandom, hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "qty": "Sold", "total": total_col})

        st.subheader("By item")
        by_item = (view.groupby("item", as_index=False)[["qty", "total"]].sum()
                   .sort_values("total", ascending=False))
        st.dataframe(by_item, hide_index=True, width="stretch",
                     column_config={"item": "Item", "qty": "Sold", "total": total_col})

        st.subheader("All sales")
        recent = view.sort_values("timestamp", ascending=False)
        st.dataframe(recent[["timestamp", "event", "fandom", "item", "qty", "total"]], hide_index=True,
                     width="stretch",
                     column_config={"timestamp": "Time", "event": "Event", "fandom": "Fandom",
                                    "item": "Item", "qty": "Qty", "total": total_col})

        st.download_button("⬇️ Download CSV", recent.to_csv(index=False), "sales.csv",
                           "text/csv", width="stretch")

        with st.expander("🗑️ Remove a sale (mistake)"):
            orders = (recent.groupby("order_id", sort=False)
                      .agg(timestamp=("timestamp", "first"), qty=("qty", "sum"), total=("total", "sum"),
                           names=("item", ", ".join))
                      .head(50))
            options = {oid: f"{o.timestamp[5:16]} · {o.qty} item(s) · {money(o.total)} · {o.names}"
                       for oid, o in orders.iterrows()}
            to_del = st.selectbox("Sale", list(options), format_func=options.get, key="del_sale")
            st.button("Remove sale and restore stock", on_click=delete_order, args=(to_del,),
                      width="stretch")

# ---- Events ----
with tab_events:
    with st.form("add_event", clear_on_submit=True):
        ev_name = st.text_input("Event name", placeholder="e.g. Comic Fiesta 2026")
        ev_date = st.date_input("Date", value=date.today())
        if st.form_submit_button("➕ Add event", width="stretch"):
            ev_name = ev_name.strip()
            if not ev_name:
                st.error("Event name is required")
            elif ev_name.lower() in events["name"].str.lower().tolist():
                st.error(f"'{ev_name}' already exists")
            else:
                store.append("events", {"event_id": new_id(), "name": ev_name, "date": ev_date.isoformat()})
                load.clear()
                st.session_state.pending_event = ev_name     # select it on the Sell tab
                st.session_state.flash = ("success", f"Added event {ev_name}")
                st.rerun()

    if not events.empty:
        totals = sales.groupby("event")[["qty", "total"]].sum()
        summary = events[["name", "date"]].copy()
        summary["sold"] = summary["name"].map(totals["qty"]).fillna(0).astype(int)
        summary["sales"] = summary["name"].map(totals["total"]).fillna(0.0)
        st.dataframe(summary, hide_index=True, width="stretch",
                     column_config={"name": "Event", "date": "Date", "sold": "Items sold",
                                    "sales": st.column_config.NumberColumn("Sales", format=f"{CURRENCY}%.2f")})
