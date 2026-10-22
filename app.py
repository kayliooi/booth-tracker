"""Art booth tracker: inventory and sales, tagged by event. Built for phone screens."""
import base64
import io
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

import insights
from pricing import price_basket
from storage import CsvStore, SheetsStore

# ---- settings ----
CURRENCY = "$"
TIMEZONE = "Asia/Singapore"
LOW_STOCK = 3          # warn when stock is at or below this

# booth kit suggestions, added with "Add starter list" on the Kit tab: (category, name, qty, notes)
KIT_STARTER = [
    ("🪧 Display", "Tablecloth", 1, ""),
    ("🪧 Display", "Banner", 1, ""),
    ("🪧 Display", "Acrylic stands", 3, ""),
    ("🪧 Display", "Print easels", 2, ""),
    ("🪧 Display", "Price signs", 1, ""),
    ("✨ Decor", "Fairy lights", 1, "spare batteries"),
    ("✨ Decor", "Plushies / table props", 1, ""),
    ("✨ Decor", "Business cards + holder", 1, ""),
    ("💳 Payment", "Card / QR reader", 1, "charged?"),
    ("💳 Payment", "PayNow QR sign", 1, ""),
    ("💳 Payment", "Cash float + coins", 1, ""),
    ("💳 Payment", "Cash box", 1, ""),
    ("💳 Payment", "Power bank + cable", 1, "charged?"),
    ("🛍️ Packing", "Paper bags", 1, ""),
    ("🛍️ Packing", "Sticker sleeves", 1, ""),
    ("🧰 Tools", "Tape", 1, ""),
    ("🧰 Tools", "Scissors", 1, ""),
    ("🧰 Tools", "Binder clips", 1, ""),
    ("🧰 Tools", "Cable ties", 1, ""),
    ("🧰 Tools", "Markers", 1, ""),
    ("🧰 Tools", "Extension cord", 1, ""),
    ("🧃 Personal", "Water bottle", 1, ""),
    ("🧃 Personal", "Snacks", 1, ""),
    ("🧃 Personal", "Exhibitor pass / badge", 1, ""),
]

# Studio: drawing stages in order, and production steps per method (the last step adds stock)
STAGES = {"idea": "💡 Idea", "sketch": "✏️ Sketch", "colour": "🎨 Colour", "shade": "🌗 Shade", "done": "✅ Done"}
METHODS = {
    "order": ("🏭 Order from printer", {"planned": "📝 Planned", "ordered": "📦 Ordered", "received": "🚚 Received"}),
    "self": ("🖨️ Print myself", {"planned": "📝 Planned", "printing": "🖨️ Printing", "cutting": "✂️ Cutting",
                                 "done": "✅ Done"}),
}

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


def md(text):
    """Escape "$" for text shown as markdown (labels, captions, messages).

    Otherwise Streamlit reads "$2.00 (3 for $5.00)" as a maths formula between the two $ signs.
    """
    return text.replace("$", r"\$")


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
    """Empty the basket (and chosen free gifts) without recording anything."""
    st.session_state.basket = {}
    st.session_state.freebies = {}
    st.session_state.skip_auto = set()


# ---- free gifts (chosen per basket, kept in st.session_state.freebies like the basket) ----
def add_freebie(item_id):
    """Add one free gift to the basket."""
    freebies = st.session_state.setdefault("freebies", {})
    freebies[item_id] = freebies.get(item_id, 0) + 1


def remove_freebie(item_id):
    """Take one free gift out of the basket."""
    freebies = st.session_state.setdefault("freebies", {})
    freebies[item_id] = freebies.get(item_id, 0) - 1
    if freebies[item_id] <= 0:
        del freebies[item_id]


def freebies_allowed(total, rules):
    """How many free gifts a basket total earns: the highest rule reached (0 if none)."""
    reached = rules[rules["min_spend"] <= total + 0.005]
    return int(reached["count"].max()) if not reached.empty else 0


def auto_gifts(items, basket, freebies):
    """Every-order items (thank-you sticker, name card...) going into this basket: {item_id: 1}.

    Empty if the basket is empty; skips items taken out for this order or out of stock.
    """
    if not basket:
        return {}
    skipped = st.session_state.get("skip_auto", set())
    return {r.item_id: 1 for r in items[items["every_order"]].itertuples()
            if r.item_id not in skipped
            and r.stock - basket.get(r.item_id, 0) - freebies.get(r.item_id, 0) > 0}


def toggle_auto_gift(item_id):
    """Take an every-order item out of this order, or put it back."""
    skipped = st.session_state.setdefault("skip_auto", set())
    skipped.symmetric_difference_update({item_id})


def trim_freebies(allowed):
    """Drop the most recently chosen free gifts until no more than `allowed` remain."""
    freebies = st.session_state.setdefault("freebies", {})
    while sum(freebies.values()) > allowed:
        remove_freebie(next(reversed(freebies)))


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

    Free gifts are recorded as extra rows with freebie = TRUE and total 0.
    Lowers stock, remembers the order for "Undo last sale" and empties the basket.
    Refuses if any item no longer has enough stock (e.g. it was sold on another phone).
    """
    items = load("items")
    quote = quote_basket(st.session_state.get("basket") or {}, items, load("deals"))
    if not quote["lines"]:
        return
    trim_freebies(freebies_allowed(quote["total"], load("freebie_rules")))
    by_id = items.set_index("item_id")
    gift_qty = dict(st.session_state.get("freebies", {}))
    for i, q in auto_gifts(items, st.session_state.get("basket") or {}, gift_qty).items():
        gift_qty[i] = gift_qty.get(i, 0) + q
    gifts = [{"item_id": i, "name": by_id.at[i, "name"], "fandom": by_id.at[i, "fandom"],
              "unit_price": float(by_id.at[i, "price"]), "qty": q, "charge": 0.0}
             for i, q in gift_qty.items() if i in by_id.index]

    needed = {}                                  # item_id -> pieces leaving the table (sold + free)
    for line in quote["lines"] + gifts:
        needed[line["item_id"]] = needed.get(line["item_id"], 0) + line["qty"]
    short = [f"{by_id.at[i, 'name']} ({by_id.at[i, 'stock']} left)"
             for i, q in needed.items() if by_id.at[i, "stock"] < q]
    if short:
        st.session_state.flash = ("error", "Not enough stock: " + ", ".join(short))
        return

    order_id, timestamp = new_id(), now()
    rows = []
    for line, free in [(line, False) for line in quote["lines"]] + [(g, True) for g in gifts]:
        items.loc[items["item_id"] == line["item_id"], "stock"] -= line["qty"]
        rows.append({"sale_id": new_id(), "order_id": order_id, "timestamp": timestamp,
                     "event": event, "item_id": line["item_id"], "item": line["name"],
                     "fandom": line["fandom"], "qty": line["qty"],
                     "unit_price": line["unit_price"], "total": line["charge"], "freebie": free,
                     "unit_cost": float(by_id.at[line["item_id"], "unit_cost"])})
    store.append_rows("sales", rows)
    store.save("items", items)
    load.clear()

    count = sum(line["qty"] for line in quote["lines"])
    free_count = sum(g["qty"] for g in gifts)
    st.session_state.last_order = {"order_id": order_id, "count": count, "free": free_count,
                                   "total": quote["total"], "timestamp": timestamp}
    clear_basket()
    gift_text = f" + {free_count} free gift{'s' if free_count != 1 else ''} 🎁" if free_count else ""
    st.session_state.flash = ("success", f"Sold {count} item{'s' if count != 1 else ''} "
                                         f"for {money(quote['total'])}{gift_text}")


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


def add_starter_kit():
    """Fill an empty kit list with KIT_STARTER suggestions."""
    store.append_rows("kit", [{"kit_id": new_id(), "category": c, "name": n, "qty": q, "notes": notes}
                              for c, n, q, notes in KIT_STARTER])
    load.clear()


def set_tick(event, kit_id, field, key):
    """Save one checklist tick for an event. field is "packed" or "returned"; key is the checkbox's key."""
    packing = load("packing")
    row = (packing["event"] == event) & (packing["kit_id"] == kit_id)
    if not row.any():
        packing = pd.concat([packing, pd.DataFrame([{"event": event, "kit_id": kit_id,
                                                     "packed": False, "returned": False}])],
                            ignore_index=True)
        row = (packing["event"] == event) & (packing["kit_id"] == kit_id)
    packing.loc[row, field] = st.session_state[key]
    store.save("packing", packing)
    load.clear()


# ---- photos (small thumbnails stored as text in the "images" table) ----
PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]
BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def make_thumbnail(file, max_side=256):
    """Shrink an uploaded photo to a small JPEG, base64-encoded so it fits in one Google Sheets cell."""
    img = ImageOps.exif_transpose(Image.open(file))      # phone photos: apply the camera's rotation
    if img.mode != "RGB":                                  # e.g. transparent PNG: put it on white
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        img = background
    img.thumbnail((max_side, max_side))
    for quality in (80, 65, 50, 35):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        data = base64.b64encode(buf.getvalue()).decode()
        if len(data) < 45_000:
            break
    return data


def set_photo(owner_id, key):
    """Save the photo just uploaded with file uploader `key` for an item or artwork (replaces the old one)."""
    file = st.session_state.get(key)
    if file is None:
        return
    try:
        data = make_thumbnail(file)
    except Exception:
        st.session_state.flash = ("error", "Couldn't read that picture. Try a JPG or PNG.")
        return
    images = load("images")
    images = pd.concat([images[images["owner_id"] != owner_id],
                        pd.DataFrame([{"owner_id": owner_id, "data": data, "updated": now()}])],
                       ignore_index=True)
    store.save("images", images)
    load.clear()
    st.session_state.flash = ("success", "Photo saved")


def remove_photo(owner_id):
    """Delete the photo of an item or artwork."""
    images = load("images")
    store.save("images", images[images["owner_id"] != owner_id])
    load.clear()


def move_stage(art_id, step):
    """Move an artwork one drawing stage forward (step=1) or back to revise (step=-1)."""
    artworks = load("artworks")
    i = artworks.index[artworks["art_id"] == art_id][0]
    stages = list(STAGES)
    pos = stages.index(artworks.at[i, "stage"]) if artworks.at[i, "stage"] in stages else 0
    artworks.at[i, "stage"] = stages[max(0, min(len(stages) - 1, pos + step))]
    store.save("artworks", artworks)
    load.clear()


def advance_batch(batch_id, step):
    """Move a production batch one step forward (step=1) or back (step=-1).

    Reaching the method's last step adds the pieces to stock: the item is created if it's new merch,
    otherwise its stock goes up and its cost per piece becomes the average over old and new stock.
    """
    batches = load("batches")
    i = batches.index[batches["batch_id"] == batch_id][0]
    steps = list(METHODS[batches.at[i, "method"]][1])
    pos = steps.index(batches.at[i, "status"]) if batches.at[i, "status"] in steps else 0
    pos = max(0, min(len(steps) - 1, pos + step))
    batches.at[i, "status"] = steps[pos]

    if pos == len(steps) - 1:
        b = batches.loc[i]
        unit = b["cost"] / b["qty"] if b["qty"] else 0.0
        items = load("items")
        match = items.index[(items["item_id"] == b["item_id"])
                            | (items["name"].str.lower() == b["name"].lower())]
        if len(match):
            j = match[0]
            old_stock, old_cost = max(int(items.at[j, "stock"]), 0), float(items.at[j, "unit_cost"])
            if old_cost and old_stock:
                unit = (old_stock * old_cost + b["qty"] * unit) / (old_stock + b["qty"])
            items.at[j, "stock"] = old_stock + b["qty"]
            items.at[j, "unit_cost"] = round(unit, 4)
            batches.at[i, "item_id"] = items.at[j, "item_id"]
        else:
            item_id = new_id()
            items = pd.concat([items, pd.DataFrame([{
                "item_id": item_id, "fandom": b["fandom"], "type": b["type"], "name": b["name"],
                "price": b["price"], "stock": b["qty"], "active": True, "freebie": False,
                "every_order": False, "unit_cost": round(unit, 4)}])], ignore_index=True)
            batches.at[i, "item_id"] = item_id
            images = load("images")
            art_photo = images[(images["owner_id"] == b["art_id"]) & (b["art_id"] != "")]
            if not art_photo.empty:                        # new merch starts with its artwork's picture
                store.append("images", {"owner_id": item_id, "data": art_photo.iloc[0]["data"],
                                        "updated": now()})
        batches.at[i, "received"] = now()[:10]
        store.save("items", items)
        st.session_state.flash = ("success", f"Added {b['qty']} × {b['name']} to stock "
                                             f"({money(unit)} each to make)")
    store.save("batches", batches)
    load.clear()


def batch_form(key, art=None):
    """Form that adds a production batch: new merch from a finished artwork, or a reprint (art=None)."""
    items = load("items")
    with st.form(key, clear_on_submit=True):
        if art is None:
            names = dict(zip(items["item_id"], items["name"]))
            item_id = st.selectbox("Item to reprint", sorted(names, key=names.get), format_func=names.get,
                                   index=None, placeholder="Choose an item")
        else:
            types = sorted(t for t in items["type"].unique() if t)
            ptype = st.selectbox("Product type", types, index=None, accept_new_options=True,
                                 placeholder="e.g. Big sticker, A6 print")
            name = st.text_input("Product name", placeholder=f"Leave blank for \"<type> - {art.title}\"")
            price = st.number_input(f"Selling price ({CURRENCY})", min_value=0.0, step=0.5, format="%.2f")
        qty = st.number_input("Quantity", min_value=1, step=1, value=10)
        cost = st.number_input(f"Total cost ({CURRENCY})", min_value=0.0, step=1.0, format="%.2f",
                               help="What the whole batch cost: printing, shipping, materials")
        vendor = st.text_input("Printer / shop", placeholder="e.g. PrintCo, or 'home printer'")
        method = st.selectbox("How", list(METHODS), format_func=lambda m: METHODS[m][0])
        if st.form_submit_button("🏭 Add to production", width="stretch"):
            if art is None:
                if not item_id:
                    st.error("Choose an item to reprint")
                    return
                it = items.set_index("item_id").loc[item_id]
                row = {"art_id": "", "item_id": item_id, "name": it["name"], "fandom": it["fandom"],
                       "type": it["type"], "price": it["price"]}
            else:
                if not ptype:
                    st.error("Product type is required")
                    return
                row = {"art_id": art.art_id, "item_id": "", "name": name.strip() or f"{ptype} - {art.title}",
                       "fandom": art.fandom, "type": ptype.strip(), "price": price}
            store.append("batches", {**row, "batch_id": new_id(), "qty": int(qty), "cost": cost,
                                     "vendor": vendor.strip(), "method": method, "status": "planned",
                                     "created": now()[:10], "received": ""})
            load.clear()
            st.session_state.flash = ("success", f"Added {int(qty)} × {row['name']} to production")
            st.rerun()


# ---- page ----
st.title("🎨 Booth Tracker")
menu_box = st.container()            # Prep / At the booth / After menu, filled at the end of the file

# Always create the message slot (even when empty): if the page layout above the tabs changed,
# Streamlit would rebuild the tabs and jump back to the first one after every save.
flash_box = st.container()
flash = st.session_state.pop("flash", None)
if flash:
    getattr(flash_box, flash[0])(md(flash[1]))

items = load("items")
events = load("events").sort_values("date", ascending=False)
sales = load("sales")
deals = load("deals")
freebie_rules = load("freebie_rules")
paid_sales = sales[~sales["freebie"]]             # free gifts don't count as items sold
photos = dict(zip(load("images")["owner_id"], load("images")["data"]))   # owner_id -> base64 JPEG


def photo_bytes(owner_id):
    """The stored thumbnail of an item or artwork as bytes for st.image, or None."""
    return base64.b64decode(photos[owner_id]) if owner_id in photos else None


# Each section below is a page function; the menu at the bottom of the file decides which are shown.

# ---- Sell ----
def page_sell():
    """At the booth: tap items into the basket, apply deals and free gifts, record the sale."""
    active = items[items["active"]]
    if events.empty:
        st.info("Add an event first: 🗓️ Prep → 📅 Events.")
    elif active.empty:
        st.info("Add items first: 🗓️ Prep → 📦 Inventory.")
    else:
        if "pending_event" in st.session_state:
            st.session_state.event = st.session_state.pop("pending_event")
        event = st.selectbox("Event", events["name"].tolist(), key="event")
        ev_sales = paid_sales[paid_sales["event"] == event]
        c1, c2 = st.columns(2)
        c1.metric("Event sales", money(ev_sales["total"].sum()))
        c2.metric("Items sold", int(ev_sales["qty"].sum()))

        basket = st.session_state.setdefault("basket", {})
        quote = quote_basket(basket, items, deals) if basket else None
        allowed = freebies_allowed(quote["total"], freebie_rules) if quote else 0
        trim_freebies(allowed)                     # e.g. an item was taken out, so fewer gifts are earned
        freebies = st.session_state.freebies
        auto = auto_gifts(items, basket, freebies)
        by_id = items.set_index("item_id")

        def left_of(item_id):
            """Stock not yet in the basket (sold or free)."""
            return (by_id.at[item_id, "stock"] - basket.get(item_id, 0) - freebies.get(item_id, 0)
                    - auto.get(item_id, 0))

        if basket:
            with st.container(border=True):
                st.markdown("**🧺 Basket** · tap an item to take one out")
                for line in quote["lines"]:
                    st.button(md(f"➖ {line['qty']} × {line['name']} · {money(line['unit_price'] * line['qty'])}"),
                              key=f"rm_{line['item_id']}", width="stretch",
                              on_click=remove_from_basket, args=(line["item_id"],))
                for a in quote["applied"]:
                    used = " + ".join(f"{t} × ({deal_text(q, p)})" if t > 1 else deal_text(q, p)
                                      for (q, p), t in a["used"].items())
                    st.caption(md(f"🎉 {a['type']}: {used} · save {money(a['saving'])}"))

                for item_id in auto:
                    st.button(f"➖ 📎 1 × {by_id.at[item_id, 'name']} · FREE", key=f"autorm_{item_id}",
                              width="stretch", on_click=toggle_auto_gift, args=(item_id,))
                for item_id in st.session_state.get("skip_auto", set()) & set(by_id.index):
                    st.button(f"➕ 📎 Add {by_id.at[item_id, 'name']} back", key=f"autoadd_{item_id}",
                              width="stretch", on_click=toggle_auto_gift, args=(item_id,))

                for item_id, qty in list(freebies.items()):
                    st.button(f"➖ 🎁 {qty} × {by_id.at[item_id, 'name']} · FREE", key=f"rmfree_{item_id}",
                              width="stretch", on_click=remove_freebie, args=(item_id,))
                to_choose = allowed - sum(freebies.values())
                if to_choose > 0:
                    options = items[items["freebie"]]
                    options = options[[left_of(i) > 0 for i in options["item_id"]]]
                    if options.empty:
                        st.caption("🎁 This basket earns a free gift, but no freebie items are in stock.")
                    else:
                        st.markdown(f"🎁 **Choose {to_choose} free gift{'s' if to_choose > 1 else ''}**")
                        for gift in options.sort_values("name").itertuples():
                            st.button(f"🎁 {gift.name} · {left_of(gift.item_id)} left", key=f"free_{gift.item_id}",
                                      width="stretch", on_click=add_freebie, args=(gift.item_id,))
                else:
                    more = freebie_rules[freebie_rules["min_spend"] > quote["total"] + 0.005]
                    more = more[more["count"] > allowed]
                    if not more.empty:
                        gap = more["min_spend"].min() - quote["total"]
                        st.caption(md(f"🎁 Spend {money(gap)} more for {'another' if allowed else 'a'} free gift"))

                st.markdown(md(f"### Total {money(quote['total'])}"))
                st.button("✅ Complete sale", type="primary", width="stretch",
                          on_click=checkout, args=(event,))
                st.button("Clear basket", width="stretch", on_click=clear_basket)

        last = st.session_state.get("last_order")
        if last and not basket:
            gifts = f" + {last['free']} 🎁" if last.get("free") else ""
            st.caption(md(f"Last sale: {last['count']} item(s){gifts} · {money(last['total'])} · "
                          f"{last['timestamp'][11:16]}"))
            st.button("↩️ Undo last sale", on_click=delete_order, args=(last["order_id"],),
                      width="stretch")

        fandoms = sorted(f for f in active["fandom"].unique() if f)
        pick = st.pills("Fandom", fandoms, key="fandom_filter") if len(fandoms) > 1 else None
        show_photos = active["item_id"].isin(photos.keys()).any() and st.checkbox(
            "📷 Show photos", value=True, key="show_photos")
        shown = active if not pick else active[active["fandom"] == pick]

        hints = {}                                  # type -> "3 for $5.00" shown on item buttons
        for d in deals.itertuples():
            hints.setdefault(d.type, []).append(deal_text(d.qty, d.price))

        for fandom, group in shown.sort_values(["fandom", "type", "name"]).groupby("fandom", sort=False):
            if not pick and fandoms:
                st.caption(f"**{fandom or 'Other'}**")
            for item in group.itertuples():
                in_basket = basket.get(item.item_id, 0)
                left = left_of(item.item_id)
                warn = " ⚠️" if 0 < left <= LOW_STOCK else ""
                deal = f" ({', '.join(hints[item.type])})" if item.type in hints else ""
                label = f"{item.name} · {money(item.price)}{deal} · {left} left{warn}"
                if in_basket:
                    label = f"🧺{in_basket} · {label}"
                button = dict(label=md(label), key=f"add_{item.item_id}", width="stretch",
                              disabled=left <= 0, on_click=add_to_basket, args=(item.item_id,))
                if show_photos and item.item_id in photos:
                    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                        st.image(photo_bytes(item.item_id), width=56)
                        st.button(**button)
                else:
                    st.button(**button)

# ---- Inventory ----
def page_inventory():
    """Prep: items, prices and stock, photos, deals and free gift rules."""
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
            for_sale = st.checkbox("For sale", value=True)
            freebie = st.checkbox("🎁 Can be chosen as a free gift")
            every_order = st.checkbox("📎 Give free with every order",
                                      help="e.g. thank-you sticker or name card: untick For sale, tick this")
            if st.form_submit_button("Add item", width="stretch"):
                name = name.strip()
                if not name:
                    st.error("Merch name is required")
                elif name.lower() in items["name"].str.lower().tolist():
                    st.error(f"'{name}' already exists. Edit it below instead")
                else:
                    store.append("items", {"item_id": new_id(), "fandom": (fandom or "").strip(),
                                           "type": (item_type or "").strip(), "name": name,
                                           "price": price, "stock": int(stock), "active": for_sale,
                                           "freebie": freebie, "every_order": every_order})
                    load.clear()
                    st.session_state.flash = ("success", f"Added {name}")
                    st.rerun()

    if not items.empty:
        low = items[(items["active"] | items["freebie"] | items["every_order"]) & (items["stock"] <= LOW_STOCK)]
        if not low.empty:
            st.warning("Low stock: " + ", ".join(f"{r.name} ({r.stock})" for r in low.itertuples()))

        st.caption("Edit directly. Untick **For sale** to hide an item from the Sell tab. "
                   "**🎁 Freebie**: can be chosen as a free gift. "
                   "**📎 Every order**: added free to every order automatically.")
        # item_id as the (hidden) index: data_editor always returns the index, so ids survive edits
        edited = st.data_editor(
            items.sort_values(["fandom", "type", "name"]).set_index("item_id")
            # items without a photo get an invisible 1-pixel image (empty cells would show "None")
            .assign(photo=lambda df: [f"data:image/jpeg;base64,{photos[i]}" if i in photos else BLANK_IMAGE
                                      for i in df.index]),
            column_order=["photo", "fandom", "type", "name", "price", "stock", "unit_cost", "active", "freebie",
                          "every_order"],
            disabled=["photo"],
            column_config={
                "photo": st.column_config.ImageColumn("📷", width="small"),
                "fandom": st.column_config.TextColumn("Fandom"),
                "type": st.column_config.TextColumn("Type"),
                "name": st.column_config.TextColumn("Merch name", required=True),
                "price": st.column_config.NumberColumn(f"Price ({CURRENCY})", min_value=0, format="%.2f"),
                "stock": st.column_config.NumberColumn("Stock", min_value=0, step=1),
                "unit_cost": st.column_config.NumberColumn(f"Cost/pc ({CURRENCY})", min_value=0, format="%.2f",
                                                           help="What one piece cost to make, for profit"),
                "active": st.column_config.CheckboxColumn("For sale"),
                "freebie": st.column_config.CheckboxColumn("🎁 Freebie"),
                "every_order": st.column_config.CheckboxColumn("📎 Every order"),
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

        with st.expander("📷 Item photos"):
            names = dict(zip(items["item_id"], items["name"]))
            photo_item = st.selectbox("Item", sorted(names, key=names.get), index=None, key="photo_item",
                                      format_func=lambda i: ("📷 " if i in photos else "") + names[i],
                                      placeholder="Choose an item")
            if photo_item:
                if photo_item in photos:
                    st.image(photo_bytes(photo_item), width=160)
                    st.button("🗑️ Remove photo", key=f"rmphoto_{photo_item}", on_click=remove_photo,
                              args=(photo_item,))
                st.file_uploader("Take or choose a photo", type=PHOTO_TYPES, key=f"up_{photo_item}",
                                 on_change=set_photo, args=(photo_item, f"up_{photo_item}"))
                st.caption("Saved as a small thumbnail, for recognising items quickly.")

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

        st.subheader("🎁 Free gifts")
        gift_names = items.loc[items["freebie"], "name"].tolist()
        st.caption(md(f"When a basket reaches **Spend at least**, you choose that many free gifts from the "
                      f"🎁 Freebie items. {CURRENCY}0 means every purchase gets one. Add rows for tiers, "
                      f"e.g. {CURRENCY}15 → 1 and {CURRENCY}30 → 2."))
        if gift_names:
            st.caption("Freebie items now: " + ", ".join(gift_names))
        else:
            st.caption("No items ticked as 🎁 Freebie yet.")
        edited_rules = st.data_editor(
            freebie_rules, num_rows="dynamic", hide_index=True, width="stretch", key="freebie_editor",
            column_config={
                "min_spend": st.column_config.NumberColumn(f"Spend at least ({CURRENCY})", min_value=0,
                                                           format="%.2f", required=True),
                "count": st.column_config.NumberColumn("Free gifts", min_value=1, step=1, required=True),
            },
        )
        if st.button("💾 Save free gift rules", width="stretch"):
            store.save("freebie_rules", edited_rules.dropna(subset=["min_spend", "count"]))
            load.clear()
            st.session_state.flash = ("success", "Free gift rules saved")
            st.rerun()

# ---- Sales ----
def page_sales():
    """After: totals, by fandom/item, free gifts given, all sales, remove a wrong sale."""
    choice = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="sales_filter")
    everything = sales if choice == "All events" else sales[sales["event"] == choice]
    view, gifts = everything[~everything["freebie"]], everything[everything["freebie"]]

    c1, c2 = st.columns(2)
    c1.metric("Total sales", money(view["total"].sum()))
    c2.metric("Items sold", int(view["qty"].sum()))

    # cost of everything that left the table, free gifts included
    everything = everything.assign(cost=everything["qty"] * everything["unit_cost"])
    view = view.assign(cost=view["qty"] * view["unit_cost"])
    if everything["cost"].sum() > 0:
        c3, c4 = st.columns(2)
        c3.metric("Cost to make", money(everything["cost"].sum()))
        c4.metric("Profit", money(view["total"].sum() - everything["cost"].sum()))
        st.caption("Cost uses each item's cost per piece (set in Inventory or from Studio batches). "
                   "Free gifts count as cost; items without a cost count as free to make.")

    if everything.empty:
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
        by_item = (view.groupby("item", as_index=False)[["qty", "total", "cost"]].sum()
                   .sort_values("total", ascending=False))
        by_item["profit"] = by_item["total"] - by_item["cost"]
        st.dataframe(by_item, hide_index=True, width="stretch",
                     column_order=["item", "qty", "total"] + (["profit"] if view["cost"].sum() > 0 else []),
                     column_config={"item": "Item", "qty": "Sold", "total": total_col,
                                    "profit": st.column_config.NumberColumn("Profit", format=f"{CURRENCY}%.2f")})

        if not gifts.empty:
            st.subheader(f"🎁 Free gifts given: {int(gifts['qty'].sum())}")
            by_gift = (gifts.assign(value=gifts["unit_price"] * gifts["qty"])
                       .groupby("item", as_index=False)[["qty", "value"]].sum()
                       .sort_values("qty", ascending=False))
            st.dataframe(by_gift, hide_index=True, width="stretch",
                         column_config={"item": "Item", "qty": "Given",
                                        "value": st.column_config.NumberColumn("Normal price",
                                                                               format=f"{CURRENCY}%.2f")})

        st.subheader("All sales")
        recent = everything.sort_values("timestamp", ascending=False)
        st.dataframe(recent[["timestamp", "event", "fandom", "item", "qty", "total", "freebie"]],
                     hide_index=True, width="stretch",
                     column_config={"timestamp": "Time", "event": "Event", "fandom": "Fandom",
                                    "item": "Item", "qty": "Qty", "total": total_col,
                                    "freebie": st.column_config.CheckboxColumn("🎁")})

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

# ---- Insights (analysis, restock forecast, AI suggestions) ----
def ai_error_message(error):
    """A friendly message for an error from the Claude API."""
    import anthropic
    if isinstance(error, anthropic.AuthenticationError):
        return "The Anthropic API key wasn't accepted. Check `anthropic_api_key` in your secrets."
    if isinstance(error, anthropic.PermissionDeniedError):
        return "This API key isn't allowed to use Claude. Check your Anthropic Console account."
    if isinstance(error, anthropic.RateLimitError):
        return "Claude is busy or your usage limit was reached. Try again in a minute."
    if isinstance(error, anthropic.APIConnectionError):
        return "Couldn't reach Claude. Check the internet connection."
    if isinstance(error, anthropic.APIStatusError):
        return f"Claude returned an error ({error.status_code}). Try again later."
    return f"Something went wrong: {error}"


def page_insights():
    """After: charts, restock forecast and AI suggestions."""
    scope = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="insights_scope")
    scoped = sales if scope == "All events" else sales[sales["event"] == scope]

    if insights.paid(scoped).empty:
        st.info("Insights appear here after your first sales.")
    else:
        h = insights.headline(scoped)
        c1, c2 = st.columns(2)
        c1.metric("Sales", money(h["revenue"]))
        c2.metric("Orders", h["orders"])
        c3, c4 = st.columns(2)
        c3.metric("Average order", money(h["avg_order"]))
        c4.metric("Items per order", f"{h['items_per_order']:.1f}")

        money_col = lambda title: st.column_config.NumberColumn(title, format=f"{CURRENCY}%.2f")

        st.subheader("Top fandoms")
        fd = insights.by_fandom(scoped, items)
        if len(fd) > 1:
            st.altair_chart(insights.bar_chart(fd, "fandom", "revenue", CURRENCY, "Sales"),
                            width="stretch", theme=None)
        with st.expander("📋 Numbers"):
            st.dataframe(fd, hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "revenue": money_col("Sales"), "sold": "Pieces"})

        st.subheader("Fandom × product type")
        ft = insights.fandom_by_type(scoped, items)
        st.caption("Darker = more sales. Empty squares are combinations you haven't sold yet: "
                   "a gap, or an idea.")
        st.altair_chart(insights.heatmap(ft, CURRENCY), width="stretch", theme=None)
        with st.expander("📋 Numbers"):
            st.dataframe(ft.sort_values("revenue", ascending=False), hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "type": "Type", "revenue": money_col("Sales"),
                                        "sold": "Pieces"})

        ev = insights.by_event(scoped, events)
        if scope == "All events" and len(ev) > 1:
            st.subheader("Events compared")
            st.altair_chart(insights.bar_chart(ev, "event", "revenue", CURRENCY, "Sales",
                                               order=ev["event"].tolist()), width="stretch", theme=None)
            with st.expander("📋 Numbers"):
                st.dataframe(ev[["event", "date", "revenue", "sold", "orders", "avg_order"]], hide_index=True,
                             width="stretch",
                             column_config={"event": "Event", "date": "Date", "revenue": money_col("Sales"),
                                            "sold": "Pieces", "orders": "Orders",
                                            "avg_order": money_col("Avg order")})

        hours = insights.by_hour(scoped)
        if len(hours) > 1:
            st.subheader("Busiest hours")
            st.caption("When orders happened. Handy for planning breaks and restocking the table.")
            st.altair_chart(insights.hour_chart(hours), width="stretch", theme=None)


# ---- Restock (what to bring next event, and how each item is doing) ----
def page_restock():
    """After: what to bring / reprint for the next event, and sales per item."""
    if insights.paid(sales).empty:
        st.info("Restock suggestions appear here after your first sales.")
        return
    money_col = lambda title: st.column_config.NumberColumn(title, format=f"{CURRENCY}%.2f")

    st.subheader("🔮 Next event: what to bring")
    forecast = insights.restock_forecast(sales, items[items["active"]], events)
    st.caption("Based on the average sold per event so far (all events), plus 25% extra. "
               "A rough guide from past sales, not a promise.")
    need = forecast[forecast["reprint"] > 0]
    if need.empty:
        st.success("You have enough stock of everything that has sold before.")
    else:
        st.warning("Reprint before the next event: " + ", ".join(
            f"{r.name} (+{int(r.reprint)})" for r in need.itertuples()))
    st.dataframe(forecast[["name", "avg_per_event", "bring", "stock", "reprint"]], hide_index=True,
                 width="stretch",
                 column_config={"name": "Item", "avg_per_event": st.column_config.NumberColumn(
                     "Avg / event", format="%.1f"), "bring": "Bring", "stock": "In stock",
                     "reprint": "Reprint"})

    st.subheader("Items")
    scope = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="restock_scope")
    scoped = sales if scope == "All events" else sales[sales["event"] == scope]
    perf = insights.item_performance(scoped, items[items["active"]])
    st.caption("Sold through = share of the pieces you had that sold (sold ÷ (sold + stock left)).")
    st.dataframe(perf[["name", "sold", "revenue", "profit", "stock", "sell_through"]], hide_index=True,
                 width="stretch",
                 column_order=["name", "sold", "sell_through", "revenue", "stock"]
                 + (["profit"] if insights.headline(scoped)["cost"] > 0 else []),
                 column_config={"name": "Item", "sold": "Sold", "revenue": money_col("Sales"),
                                "profit": money_col("Profit"), "stock": "Left",
                                "sell_through": st.column_config.NumberColumn("Sold through",
                                                                              format="percent")})



# ---- AI ideas (Claude suggestions based on the sales summary) ----
AI_QUESTIONS = ["What should I draw next?", "What should I bring to the next event?",
                "How can I raise my average order?", "Are my prices and deals right?"]


def page_ai():
    """After: ask Claude for ideas (what to draw, restock, pricing) based on a summary of the sales."""
    api_key = _secret("anthropic_api_key")
    if not api_key:
        st.info("Get ideas from Claude (Anthropic's AI) based on your sales: what to draw next, what to "
                "restock, pricing and deals. To turn it on, add `anthropic_api_key = \"sk-ant-...\"` to your "
                "secrets (an API key from console.anthropic.com; each request costs a few cents).")
    elif insights.paid(sales).empty:
        st.info("AI ideas are available after your first sales.")
    else:
        scope = st.selectbox("Based on", ["All events"] + events["name"].tolist(), key="ai_scope")
        scoped = sales if scope == "All events" else sales[sales["event"] == scope]
        preset = st.pills("Quick questions", AI_QUESTIONS, key="ai_preset")
        typed = st.text_input("Or ask your own (optional)", key="ai_question",
                              placeholder="e.g. What should I make for Comic Fiesta?")
        question = typed.strip() or preset or ""
        st.caption(f"Sends a summary of {'all your' if scope == 'All events' else scope} sales, stock, deals "
                   "and artworks (no customer details) to Anthropic's Claude. Each request costs a few cents.")
        if st.button("✨ Get suggestions", type="primary", width="stretch"):
            brief = insights.ai_brief(scoped, items, events, deals, freebie_rules, load("artworks"), CURRENCY, scope)
            try:
                text = st.write_stream(chunk.replace("$", r"\$")
                                       for chunk in insights.stream_suggestions(api_key, brief, question))
                st.session_state.ai_answer = text
            except Exception as error:
                st.error(ai_error_message(error))
        elif st.session_state.get("ai_answer"):
            st.markdown(st.session_state.ai_answer)

# ---- Events ----
def page_events():
    """Prep: add events and see sales per event."""
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
        totals = paid_sales.groupby("event")[["qty", "total"]].sum()
        summary = events[["name", "date"]].copy()
        summary["sold"] = summary["name"].map(totals["qty"]).fillna(0).astype(int)
        summary["sales"] = summary["name"].map(totals["total"]).fillna(0.0)
        st.dataframe(summary, hide_index=True, width="stretch",
                     column_config={"name": "Event", "date": "Date", "sold": "Items sold",
                                    "sales": st.column_config.NumberColumn("Sales", format=f"{CURRENCY}%.2f")})

# ---- Kit (booth packing checklist) ----
def page_kit(field):
    """Booth kit checklist for an event. field "packed" = Packing (before), "returned" = Pack up (at the booth)."""
    kit = load("kit")
    if kit.empty:
        st.info("List the things you bring to every booth (tablecloth, stands, card reader...) "
                "and tick them off for each event.")
        st.button("✨ Add starter list", on_click=add_starter_kit, width="stretch")
        st.caption("You can edit, add and remove items afterwards.")
    elif events.empty:
        st.info("Add an event first: 🗓️ Prep → 📅 Events.")
    else:
        kit_event = st.selectbox("Event", events["name"].tolist(), key="kit_event")
        st.caption("Tick things off as they go into your bag." if field == "packed"
                   else "End of the day: tick things off as you pack up, so nothing is left behind.")

        packing = load("packing")
        ticks = packing[packing["event"] == kit_event].set_index("kit_id")[field]
        done = kit["kit_id"].map(ticks).fillna(False).astype(bool)

        verb = "Packed up" if field == "returned" else "Packed"
        if done.all():
            st.success(f"{verb} everything! 🎉")
        else:
            st.markdown(f"**{verb} {int(done.sum())} / {len(kit)}**")
            if (~done).sum() <= 8:
                st.caption("Still to go: " + ", ".join(kit.loc[~done, "name"]))

        starter_order = list(dict.fromkeys(c for c, *_ in KIT_STARTER))
        categories = sorted(kit["category"].unique(),
                            key=lambda c: (starter_order.index(c) if c in starter_order else len(starter_order), c))
        for category in categories:
            st.caption(f"**{category or 'Other'}**")
            group = kit[kit["category"] == category]
            for item, is_done in zip(group.itertuples(), done[group.index]):
                label = item.name + (f" ×{item.qty}" if item.qty > 1 else "")
                if item.notes:
                    label += f" · _{item.notes}_"
                key = f"kit_{field}_{kit_event}_{item.kit_id}"
                st.checkbox(md(label), value=bool(is_done), key=key,
                            on_change=set_tick, args=(kit_event, item.kit_id, field, key))

    if not kit.empty and field == "packed":
        with st.expander("✏️ Edit kit list"):
            st.caption("Add a row at the bottom; select a row and press delete to remove it.")
            edited_kit = st.data_editor(
                kit, num_rows="dynamic", hide_index=True, width="stretch", key="kit_editor",
                column_order=["category", "name", "qty", "notes"],
                column_config={
                    "category": st.column_config.TextColumn("Category"),
                    "name": st.column_config.TextColumn("Item", required=True),
                    "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1),
                    "notes": st.column_config.TextColumn("Notes"),
                },
            )
            if st.button("💾 Save kit list", width="stretch"):
                edited_kit = edited_kit[edited_kit["name"].fillna("").str.strip() != ""].copy()
                new_rows = edited_kit["kit_id"].fillna("") == ""
                edited_kit.loc[new_rows, "kit_id"] = [new_id() for _ in range(new_rows.sum())]
                store.save("kit", edited_kit)
                load.clear()
                st.session_state.flash = ("success", "Kit list saved")
                st.rerun()

# ---- Studio (artworks from idea to finished art, then production into stock) ----
def page_studio():
    """Prep: artworks from idea to finished art, then production batches into stock."""
    artworks = load("artworks")
    batches = load("batches")
    studio_view = st.pills("Studio", ["🎨 Artworks", "🏭 Production"], default="🎨 Artworks",
                           key="studio_view", label_visibility="collapsed")

    if studio_view != "🏭 Production":
        with st.expander("💡 New idea", expanded=artworks.empty):
            with st.form("add_art", clear_on_submit=True):
                title = st.text_input("Title", placeholder="e.g. Psyduck in a raincoat")
                art_fandoms = sorted((set(items["fandom"]) | set(artworks["fandom"])) - {""})
                art_fandom = st.selectbox("Fandom", art_fandoms, index=None, accept_new_options=True,
                                          placeholder="Pick or type a new one")
                target = st.selectbox("For event (optional)", events["name"].tolist(), index=None,
                                      placeholder="No deadline")
                notes = st.text_area("Notes", placeholder="Ideas, colours, size...", height=80)
                link = st.text_input("Reference link (optional)", placeholder="Pinterest, Drive, X post...")
                if st.form_submit_button("💡 Add idea", width="stretch"):
                    if not title.strip():
                        st.error("Title is required")
                    else:
                        store.append("artworks", {"art_id": new_id(), "title": title.strip(),
                                                  "fandom": (art_fandom or "").strip(), "stage": "idea",
                                                  "target_event": target or "", "notes": notes.strip(),
                                                  "link": link.strip(), "created": now()[:10]})
                        load.clear()
                        st.session_state.flash = ("success", f"Added idea: {title.strip()}")
                        st.rerun()

        if not artworks.empty:
            st.caption(" · ".join(f"{label} {int((artworks['stage'] == key).sum())}"
                                  for key, label in STAGES.items()))
            show = st.pills("Show", ["In progress", "✅ Done"], default="In progress", key="art_filter")
            shown = artworks[(artworks["stage"] == "done") == (show == "✅ Done")]
            if shown.empty:
                st.info("Nothing here yet.")
            stages = list(STAGES)
            for key, label in STAGES.items():
                group = shown[shown["stage"] == key]
                if group.empty:
                    continue
                st.caption(f"**{label}**")
                for art in group.sort_values("created").itertuples():
                    heading = art.title + (f" · {art.fandom}" if art.fandom else "")
                    with st.expander(md(heading)):
                        if art.art_id in photos:
                            st.image(photo_bytes(art.art_id), width=200)
                        st.file_uploader("📷 Progress picture" + (" (replace)" if art.art_id in photos else ""),
                                         type=PHOTO_TYPES, key=f"up_{art.art_id}",
                                         on_change=set_photo, args=(art.art_id, f"up_{art.art_id}"))
                        details = [f"📅 for {art.target_event}" if art.target_event else "",
                                   f"added {art.created}"]
                        st.caption(md(" · ".join(d for d in details if d)))
                        if art.notes:
                            st.markdown(md(art.notes))
                        if art.link:
                            st.markdown(f"[🔗 Reference]({art.link})")
                        pos = stages.index(key)
                        with st.container(horizontal=True):
                            st.button("◀ Back", key=f"back_{art.art_id}", disabled=pos == 0,
                                      on_click=move_stage, args=(art.art_id, -1))
                            if pos < len(stages) - 1:
                                st.button(f"Next: {STAGES[stages[pos + 1]]} ▶", key=f"next_{art.art_id}",
                                          type="primary", on_click=move_stage, args=(art.art_id, 1))
                        if st.session_state.get("editing_art") == art.art_id:
                            with st.form(f"artform_{art.art_id}"):
                                new_title = st.text_input("Title", value=art.title)
                                new_fandom = st.text_input("Fandom", value=art.fandom)
                                ev_names = events["name"].tolist()
                                new_target = st.selectbox("For event", ev_names, placeholder="No deadline",
                                                          index=ev_names.index(art.target_event)
                                                          if art.target_event in ev_names else None)
                                new_notes = st.text_area("Notes", value=art.notes, height=80)
                                new_link = st.text_input("Reference link", value=art.link)
                                delete = st.checkbox("🗑️ Delete this artwork")
                                if st.form_submit_button("💾 Save", width="stretch"):
                                    if delete:
                                        artworks = artworks[artworks["art_id"] != art.art_id]
                                    else:
                                        artworks.loc[artworks["art_id"] == art.art_id,
                                                     ["title", "fandom", "target_event", "notes", "link"]] = [
                                            new_title.strip() or art.title, new_fandom.strip(),
                                            new_target or "", new_notes.strip(), new_link.strip()]
                                    store.save("artworks", artworks)
                                    load.clear()
                                    st.session_state.editing_art = None
                                    st.rerun()
                        else:
                            st.button("✏️ Edit", key=f"edit_{art.art_id}", on_click=st.session_state.update,
                                      kwargs={"editing_art": art.art_id})

                        made = batches[batches["art_id"] == art.art_id]
                        for b in made.itertuples():
                            status = METHODS[b.method][1].get(b.status, b.status)
                            st.caption(f"🏭 {b.name} ×{b.qty} · {status}")
                        if key == "done":
                            st.markdown("**🏭 Make merch from this art**")
                            batch_form(f"batch_{art.art_id}", art)

    else:
        with st.expander("➕ Reprint an existing item"):
            batch_form("batch_reprint")

        final = {m: list(steps)[-1] for m, (_, steps) in METHODS.items()}
        is_final = batches["status"] == batches["method"].map(final)
        running = batches[~is_final]
        if running.empty:
            st.info("Nothing in production. Finish an artwork and use **Make merch**, or reprint an item above.")
        for b in running.sort_values("created").itertuples():
            method_label, steps = METHODS[b.method]
            keys = list(steps)
            pos = keys.index(b.status) if b.status in keys else 0
            with st.container(border=True):
                st.markdown(md(f"**{b.name}** ×{b.qty}"))
                per_piece = f" ({money(b.cost / b.qty)} each)" if b.qty else ""
                st.caption(md(f"{method_label} · {b.vendor or 'no shop set'} · {money(b.cost)}{per_piece}"))
                st.caption(" → ".join(f"**{v}**" if k == b.status else v for k, v in steps.items()))
                with st.container(horizontal=True):
                    st.button("◀", key=f"bback_{b.batch_id}", disabled=pos == 0,
                              on_click=advance_batch, args=(b.batch_id, -1))
                    nxt = keys[pos + 1]
                    label = (f"{steps[nxt]}: add {b.qty} to stock" if pos + 1 == len(keys) - 1
                             else f"Next: {steps[nxt]} ▶")
                    st.button(label, key=f"bnext_{b.batch_id}", type="primary",
                              on_click=advance_batch, args=(b.batch_id, 1))

        finished = batches[is_final]
        if not finished.empty:
            st.subheader("Finished batches")
            done_view = finished.assign(per_piece=finished["cost"] / finished["qty"].where(finished["qty"] > 0))
            st.dataframe(done_view.sort_values("received", ascending=False)
                         [["received", "name", "qty", "cost", "per_piece", "vendor"]],
                         hide_index=True, width="stretch",
                         column_config={"received": "Received", "name": "Item", "qty": "Qty",
                                        "cost": st.column_config.NumberColumn("Cost", format=f"{CURRENCY}%.2f"),
                                        "per_piece": st.column_config.NumberColumn("Each",
                                                                                   format=f"{CURRENCY}%.2f"),
                                        "vendor": "Printer / shop"})


# ---- menu: Prep / At the booth / After, each with its own tabs ----
MENU = {
    "🗓️ Prep": [("🎨 Studio", page_studio), ("📦 Inventory", page_inventory), ("📅 Events", page_events),
                  ("🧳 Packing", lambda: page_kit("packed"))],
    "🛒 At the booth": [("🛒 Sell", page_sell), ("🧳 Pack up", lambda: page_kit("returned"))],
    "📈 After": [("📊 Sales", page_sales), ("📈 Insights", page_insights), ("🔮 Restock", page_restock),
                ("✨ AI ideas", page_ai)],
}
with menu_box:
    section = st.pills("Menu", list(MENU), default="🛒 At the booth", key="menu",
                       label_visibility="collapsed") or "🛒 At the booth"
pages = MENU[section]
for tab, (_, page) in zip(st.tabs([name for name, _ in pages]), pages):
    with tab:
        page()
