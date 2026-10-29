"""Art booth tracker: inventory and sales, tagged by event. Built for phone screens."""
import base64
import io
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

import catalog
import insights
import reports
from pricing import price_basket
from storage import TABLES, CsvStore, SheetsStore

# ---- settings ----
CURRENCY = "$"
TIMEZONE = "Asia/Singapore"
LOW_STOCK = 3          # warn when stock is at or below this
# how customers can pay: key saved in the sheet -> button label
PAYMENTS = {"cash": "💵 Cash", "card": "💳 Card", "qr": "📱 QR"}
ORDER_KINDS = ["🛍️ Pre-order", "🎨 Commission"]
# theme tags until you edit the list in ⚙️ Settings → 🏷️ Themes: (name, emoji, from month, to month);
# festive themes have months (their season), all-year ones leave them blank
THEME_STARTER = [("CNY", "🧧", "Jan", "Feb"), ("Halloween", "🎃", "Oct", "Oct"), ("Xmas", "🎄", "Dec", "Dec"),
                 ("Gym", "💪", "", ""), ("Couple", "💕", "", ""), ("Work", "💼", "", "")]
# festive days on the Singapore / SEA calendar, added with "Add festive themes from the calendar" in Settings.
# Hari Raya moves about 11 days earlier each year (Feb-Mar around 2027-2029), and CNY, Easter, Mid-Autumn
# and Deepavali shift by a few weeks, so check their months each year. Summer matsuri = Tanabata / Japanese
# summer festivals; Graduation = Singapore university convocations (mostly July).
HOLIDAY_THEMES = [("Valentine's", "💝", "Feb", "Feb"), ("Hari Raya", "🌙", "Feb", "Mar"),
                  ("Easter", "🐣", "Mar", "Apr"), ("Mother's Day", "💐", "May", "May"),
                  ("Father's Day", "👔", "Jun", "Jun"), ("Summer matsuri", "🎐", "Jul", "Jul"),
                  ("Graduation", "🎓", "Jul", "Jul"), ("National Day", "🇸🇬", "Aug", "Aug"),
                  ("Mid-Autumn", "🥮", "Sep", "Sep"), ("Deepavali", "🪔", "Oct", "Nov")]
SEASON_HEADS_UP_DAYS = 70  # festive season reminders start this many days (10 weeks) before
COST_CATEGORIES = ["Table fee", "Travel", "Food", "Parking", "Accommodation", "Supplies", "Other"]
# public idea page (your app link + ?page=ideas): what visitors see
IDEA_PAGE_TITLE = "✨ Help Kay-chan pick the next sticker!"
IDEA_PAGE_INTRO = ("Which character or fandom would you love as a sticker or print? "
                   "Send Kay-chan your idea, or vote for one below. Popular ideas get drawn first!")
IDEA_PAGE_LIMIT = 5        # ideas one visitor can send per visit
# commission requests on the same page (turn them on/off in 🗓️ Prep → 📝 Orders); private, never shown to others
COMMISSION_INTRO = ("Want something just for you, like your favourite characters from two fandoms together, "
                    "or your OC? Tell Kay-chan about it. Only Kay-chan sees this, and will reply to you "
                    "with a price before anything is made.")
# what you offer until you edit the list in ⚙️ Settings → 🎨 Commission options: (name, details, price from (0 = not shown), open)
COMMISSION_STARTER = [("Square print", "400 × 400 px", 0.0, True)]
COMMISSION_LIMIT = 2       # commission requests one phone can send per day

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

# promo checklist suggestions per event, added with "Add starter list" on the Promo tab: (task, hint)
PROMO_STARTER = [
    ("Announce you'll be at the event", "Date, location, and your booth number once you know it"),
    ("Post your booth number / floor map", ""),
    ("Post the catalog", "Make the images below"),
    ("Sneak peeks of new merch", "Photos or progress shots from 🎨 Studio"),
    ("Share the idea page QR", "🛒 At the booth → 💬 Requests → 📣 Share"),
    ("Reminder post the day before", ""),
    ("Stories from the booth during the event", ""),
    ("Thank-you post after the event", "✨ AI ideas → 📣 Social post can write it"),
]

# Studio: drawing stages in order, and production steps per method (the last step adds stock)
STAGES = {"idea": "💡 Idea", "sketch": "✏️ Sketch", "colour": "🎨 Colour", "shade": "🌗 Shade", "done": "✅ Done"}
METHODS = {
    "order": ("🏭 Order from printer", {"planned": "📝 Planned", "ordered": "📦 Ordered", "received": "🚚 Received"}),
    "self": ("🖨️ Print myself", {"planned": "📝 Planned", "printing": "🖨️ Printing", "cutting": "✂️ Cutting",
                                 "done": "✅ Done"}),
}

ICON = Path(__file__).parent / "assets" / "icon.png"      # round avatar: tab icon and page headers
st.set_page_config(page_title="Booth Tracker", page_icon=str(ICON) if ICON.exists() else "🎨", layout="centered")
st.html(f"<style>{(Path(__file__).parent / 'styles' / 'app.css').read_text(encoding='utf-8')}</style>")

def header(title, size=56):
    """The page title with the round avatar beside it (or a 🎨 when assets/icon.png is missing)."""
    if not ICON.exists():
        st.title(f"🎨 {title}")
        return
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.image(str(ICON), width=size)
        st.title(title)


def icon_b64():
    """The avatar as base64 text for the printable pages, or "" when there's none."""
    return base64.b64encode(ICON.read_bytes()).decode() if ICON.exists() else ""


def _secret(key):
    """Return a value from Streamlit secrets, or None if it isn't set (e.g. running locally)."""
    try:
        return st.secrets[key]
    except Exception:
        return None


# ---- storage ----
@st.cache_resource
def get_store(mode="live"):
    """The data for `mode`: "live" (your real data) or "test" (🧪 Test mode, to try things out).

    live: the Google Sheet at `spreadsheet_url`, or local CSV files in data/ without secrets.
    test: the Google Sheet at `test_spreadsheet_url` if set, otherwise CSV files in data_test/
    (on Streamlit Cloud those are temporary: they're wiped when the app restarts).
    Cached so each connection is made once and shared by all users.
    """
    creds = _secret("gcp_service_account")
    if mode == "test":
        url = _secret("test_spreadsheet_url")
        if url and url == _secret("spreadsheet_url"):
            raise ValueError("test_spreadsheet_url is your real sheet. Make a separate sheet for testing.")
        return SheetsStore(creds, url) if creds and url else CsvStore("data_test")
    url = _secret("spreadsheet_url")
    return SheetsStore(creds, url) if creds and url else CsvStore("data")


def data_mode():
    """"test" while 🧪 Test mode is on for this phone/browser, otherwise "live".

    The public idea page always uses the live data.
    """
    if st.query_params.get("page") == "ideas":
        return "live"
    return "test" if st.session_state.get("test_mode") else "live"


@st.cache_data(ttl=300, show_spinner=False)
def _load(table, mode):
    """Read a table from the live or test data (cached, see load)."""
    return get_store(mode).load(table)


def load(table):
    """Return a table (e.g. "items", "sales") as a DataFrame, from the live or test data.

    Cached for 5 minutes to avoid hitting Google Sheets on every tap. Write with save / append /
    append_rows below: they forget only the table they changed, so the next page only re-reads that one.
    """
    return _load(table, data_mode())


def save(table, df):
    """Replace a whole table, then forget its cached copy."""
    mode = data_mode()
    get_store(mode).save(table, df)
    _load.clear(table, mode)


def append(table, row):
    """Add one row (dict) to a table, then forget its cached copy."""
    mode = data_mode()
    get_store(mode).append(table, row)
    _load.clear(table, mode)


def append_rows(table, rows):
    """Add several rows (list of dicts) to a table, then forget its cached copy."""
    mode = data_mode()
    get_store(mode).append_rows(table, rows)
    _load.clear(table, mode)


def get_setting(key, default=""):
    """A switch saved in the "settings" table (text), or `default` if it was never set."""
    settings = load("settings")
    found = settings.loc[settings["key"] == key, "value"]
    return found.iloc[-1] if not found.empty else default


def set_setting(key, value):
    """Save a switch in the "settings" table."""
    settings = load("settings")
    save("settings", pd.concat([settings[settings["key"] != key],
                                pd.DataFrame([{"key": key, "value": str(value)}])], ignore_index=True))


def theme_list():
    """Your themes (the "themes" table, or THEME_STARTER until you edit the list)."""
    themes = load("themes")
    if themes.empty:
        themes = pd.DataFrame(THEME_STARTER, columns=TABLES["themes"])
    return themes[themes["name"].str.strip() != ""]


def add_holiday_themes():
    """Add the HOLIDAY_THEMES you don't have yet (by name, ignoring case) to your theme list."""
    current = theme_list()
    have = set(current["name"].str.lower())
    new = [t for t in HOLIDAY_THEMES if t[0].lower() not in have]
    save("themes", pd.concat([current, pd.DataFrame(new, columns=TABLES["themes"])], ignore_index=True))
    st.session_state.flash = ("success", "Added " + ", ".join(f"{e} {n}" for n, e, *_ in new))


def theme_label(name, themes):
    """A theme name with its emoji, e.g. "🎄 Xmas"."""
    emoji = dict(zip(themes["name"], themes["emoji"])).get(name, "")
    return f"{emoji} {name}".strip()


def join_tags(value):
    """Chosen themes (a list from a table cell or multiselect) back to sheet text, e.g. "Xmas, Couple"."""
    if isinstance(value, str):
        return value
    try:
        return ", ".join(str(t) for t in value)
    except TypeError:                                   # empty cell (None / NaN)
        return ""


def theme_emojis(cell, themes):
    """Just the emojis of a themes cell, e.g. "Xmas, Couple" -> "🎄💕" (short, for headings)."""
    emoji = dict(zip(themes["name"], themes["emoji"]))
    return "".join(emoji.get(t, "") for t in insights.tags(cell))


def themes_text(cell, themes):
    """A themes cell for display, e.g. "Xmas, Couple" -> "🎄 Xmas · 💕 Couple"."""
    return " · ".join(theme_label(t, themes) for t in insights.tags(cell))


def copy_live_to_test():
    """Replace all test data with a copy of the real data, to try things on realistic data."""
    for table in TABLES:
        get_store("test").save(table, _load(table, "live"))
        _load.clear(table, "test")
    st.session_state.flash = ("success", "🧪 Test data is now a copy of your real data.")


def clear_test_data():
    """Empty every test table, to start testing from scratch."""
    for table in TABLES:
        get_store("test").save(table, pd.DataFrame(columns=TABLES[table]))
        _load.clear(table, "test")
    st.session_state.flash = ("success", "🧪 Test data cleared.")


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


# Price boxes fill from the right like a cash register: typing 1, 2, 5, 0 shows 0.01, 0.12, 1.25, 12.50.
# The script finds every text box whose key starts with "money_" and formats it as you type; it also
# asks phones for the number keypad. It installs itself once per page and watches for new boxes.
MONEY_JS = """<script>
(() => {
  if (window.__moneyBoxes) return;
  window.__moneyBoxes = true;
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  const format = (box) => {
    const digits = box.value.replace(/\\D/g, "").replace(/^0+/, "").slice(0, 9);
    const padded = digits.padStart(3, "0");
    const text = digits ? padded.slice(0, -2) + "." + padded.slice(-2) : "";
    if (box.value !== text) {
      setValue.call(box, text);
      box.dispatchEvent(new Event("input", { bubbles: true }));   // tell Streamlit about the new value
    }
  };
  const attach = () => document.querySelectorAll('[class*="st-key-money_"] input').forEach((box) => {
    if (box.dataset.money) return;
    box.dataset.money = "1";
    box.setAttribute("inputmode", "numeric");
    box.addEventListener("input", () => format(box));
  });
  attach();
  new MutationObserver(attach).observe(document.body, { childList: true, subtree: true });
})();
</script>"""
st.html(MONEY_JS, unsafe_allow_javascript=True)


def parse_money(text):
    """The amount typed in a price box ("12.50", "$1,200") as a float, or None when it's empty or unreadable."""
    cleaned = str(text or "").replace(CURRENCY, "").replace(",", "").strip()
    try:
        return round(float(cleaned), 2) if cleaned else None
    except ValueError:
        return None


def money_input(label, key, value=None, **kwargs):
    """A price box that fills from the right (type 1250 for 12.50), with the number keypad on phones.

    Returns the amount as a float, or None when left empty. The widget's key is "money_<key>".
    """
    text = st.text_input(label, value=f"{value:.2f}" if value else "", key=f"money_{key}",
                         placeholder=kwargs.pop("placeholder", "0.00"), **kwargs)
    return parse_money(text)


def show_table(data, column_config=None, **kwargs):
    """st.dataframe, but every decimal column without its own format shows at most 2 decimals."""
    config = dict(column_config or {})
    for col in data.columns:
        if col not in config and pd.api.types.is_float_dtype(data[col]):
            config[col] = st.column_config.NumberColumn(format="%.2f")
    return st.dataframe(data, column_config=config, **kwargs)


def deal_text(qty, price):
    """Describe a deal, e.g. "3 for $5.00"."""
    return f"{qty} for {money(price)}"


# ---- public idea page (no password; shows nothing from the shop except open idea titles) ----
VOTER_COOKIE = "booth_voter"


def voter_id():
    """This phone's random voter id (no personal info), so limits survive refreshing the page.

    Read from the phone's cookie; on the first visit a new id is made and saved in a cookie for a year.
    If the phone blocks cookies, the id only lasts for this visit.
    """
    saved = st.context.cookies.get(VOTER_COOKIE, "")
    if saved.isalnum() and 8 <= len(saved) <= 40:
        return saved
    new = st.session_state.setdefault("new_voter_id", uuid.uuid4().hex)
    st.html(f"<script>document.cookie = '{VOTER_COOKIE}={new}; max-age=31536000; path=/; SameSite=Lax';</script>",
            unsafe_allow_javascript=True)
    return new


def voted_keys(requests, voter):
    """The ideas (grouping keys, as in insights.group_requests) this phone has already asked or voted for."""
    mine = requests[requests["voter"] == voter]
    return set(insights.request_key(mine["subject"], mine["fandom"], mine["type"]))


def vote_for(request_id, key, voter):
    """A visitor's 👍 on an existing idea: one more ask, at most once per idea per phone."""
    requests = load("requests")
    if key in voted_keys(requests, voter):
        return
    original = requests.set_index("request_id").loc[request_id]
    append("requests", {"request_id": new_id(), "timestamp": now(), "event": "", "subject": original["subject"],
                        "fandom": original["fandom"], "type": original["type"], "notes": "", "status": "open",
                        "art_id": "", "source": "online-vote", "contact": "", "voter": voter})


def commission_options():
    """What you offer as commissions (the "commission_options" table, or COMMISSION_STARTER until edited)."""
    options = load("commission_options")
    if options.empty:
        options = pd.DataFrame(COMMISSION_STARTER, columns=TABLES["commission_options"])
    return options


def open_commission_options():
    """The commission options visitors can pick right now (ticked as open, with a name)."""
    options = commission_options()
    return options[options["open"] & options["name"].str.strip().ne("")]


def option_label(o):
    """How a commission option reads on the idea page, e.g. "Square print (400 × 400 px) · from $15.00"."""
    return (o["name"] + (f" ({o['details']})" if o["details"] else "")
            + (f" · from {money(o['price_from'])}" if o["price_from"] else ""))


def commission_form(voter):
    """The public page's private commission request: saved as an order with status "request".

    Only you see it (🗓️ Prep → 📝 Orders), where you accept it with a price or decline it.
    """
    st.write(COMMISSION_INTRO)
    offered = [option_label(o) for _, o in open_commission_options().iterrows()]
    if len(offered) == 1:
        st.markdown(md(f"**Kay-chan offers right now:** {offered[0]}"))
    orders = load("preorders")
    sent = int(((orders["voter"] == voter) & (orders["created"] == now()[:10])).sum())
    if st.session_state.pop("commission_thanks", False):
        st.success("Thank you! Kay-chan will get back to you about it. 💜")
    if sent >= COMMISSION_LIMIT:
        st.info("Your request is in! Kay-chan will contact you soon.")
        return
    # kept on error (so a long description isn't lost); cleared after sending by deleting the cf_ keys
    with st.form("public_commission"):
        what =st.text_area("What would you like?", max_chars=500, height=110, key="cf_what",
                            placeholder="e.g. Gojo and Shinobu having tea together, chibi style")
        fandoms = st.text_input("Characters / fandoms (optional)", max_chars=100, key="cf_fandoms",
                                placeholder="e.g. Jujutsu Kaisen + Demon Slayer")
        fmt = (st.selectbox("What kind?", offered, index=None, placeholder="Choose one", key="cf_kind")
               if len(offered) > 1 else offered[0])
        budget = st.text_input("Budget (optional)", max_chars=40, placeholder=f"e.g. around {CURRENCY}30",
                               key="cf_budget")
        due =st.date_input("Needed by (optional)", value=None, min_value=date.today(), key="cf_due")
        refs = st.text_input("Link to reference pictures (optional)", max_chars=200, key="cf_refs",
                             placeholder="e.g. a Google Drive or Pinterest link")
        name = st.text_input("Your name", max_chars=40, key="cf_name")
        contact = st.text_input("How can Kay-chan reach you?", max_chars=80, key="cf_contact",
                                placeholder="@instagram, email or phone")
        if st.form_submit_button("🎨 Send request", type="primary", width="stretch"):
            if not what.strip() or not name.strip() or not contact.strip() or not fmt:
                st.error("Please fill in what you'd like, " + ("what kind, " if not fmt else "")
                         + "your name and how to reach you 🙂")
                return
            notes = " · ".join(f"{label}: {value.strip()}" for label, value in
                               [("Kind", fmt), ("Fandoms", fandoms), ("Budget", budget), ("Refs", refs)]
                               if value.strip())
            append("preorders", {
                "preorder_id": new_id(), "created": now()[:10], "kind": ORDER_KINDS[1], "customer": name.strip(),
                "contact": contact.strip(), "description": what.strip(), "item_id": "", "qty": 1, "price": 0.0,
                "deposit": 0.0, "due": due.isoformat() if due else "", "collect_event": "", "status": "request",
                "notes": notes, "voter": voter})
            for key in [k for k in st.session_state if str(k).startswith("cf_")]:
                del st.session_state[key]
            st.session_state.commission_thanks = True
            st.rerun()


def public_idea_page():
    """The page visitors see at ?page=ideas: suggest an idea and vote on others (writes to "requests"),
    or, when commissions are open, ask for a commission privately (writes to "preorders")."""
    header(IDEA_PAGE_TITLE, size=72)
    voter = voter_id()
    if get_setting("commissions_open", "TRUE") == "TRUE" and not open_commission_options().empty:
        choice =st.segmented_control("What would you like to do?", ["💡 Suggest an idea", "🎨 Ask for a commission"],
                                      default="💡 Suggest an idea", key="public_mode", width="stretch",
                                      label_visibility="collapsed")
        if choice == "🎨 Ask for a commission":
            commission_form(voter)
            return
    st.write(IDEA_PAGE_INTRO)
    requests = load("requests")
    sent = int(((requests["voter"] == voter) & (requests["source"] == "online")       # ideas from this phone today
                & (requests["timestamp"].str[:10] == now()[:10])).sum())
    if st.session_state.pop("idea_thanks", False):
        st.success("Thank you! Your idea is in. 💜")
    if sent >= IDEA_PAGE_LIMIT:
        st.info("Thanks for all your ideas! You can vote for more below.")
    else:
        types = sorted(t for t in load("items")["type"].unique() if t)
        with st.form("public_idea", clear_on_submit=True):
            subject = st.text_input("What should Kay-chan draw?", max_chars=80,
                                    placeholder="e.g. Gojo eating mochi")
            fandom = st.text_input("Fandom (optional)", max_chars=60, placeholder="e.g. Jujutsu Kaisen")
            mtype = st.selectbox("As what? (optional)", types + ["Something else"], index=None,
                                 placeholder="e.g. Big sticker, A6 print")
            contact = st.text_input("Your name or @handle (optional)", max_chars=40,
                                    placeholder="so Kay-chan can tag you when it's ready")
            notes = st.text_area("Anything else? (optional)", max_chars=200, height=80)
            if st.form_submit_button("💡 Send idea", type="primary", width="stretch"):
                if not subject.strip():
                    st.error("Tell Kay-chan what to draw 🙂")
                else:
                    append("requests", {"request_id": new_id(), "timestamp": now(), "event": "",
                                        "subject": subject.strip(), "fandom": fandom.strip(),
                                        "type": "" if mtype in (None, "Something else") else mtype,
                                        "notes": notes.strip(), "status": "open", "art_id": "",
                                        "source": "online", "contact": contact.strip(), "voter": voter})
                    st.session_state.idea_thanks = True
                    st.rerun()

    requests = load("requests")
    popular = insights.group_requests(requests).head(10)
    if not popular.empty:
        st.subheader("👍 Vote for ideas")
        st.caption("Tap 👍 on the ones you'd buy too. One vote per idea.")
        voted = voted_keys(requests, voter)              # includes ideas this phone suggested itself
        for r in popular.itertuples():
            detail = " · ".join(x for x in [r.fandom, r.type] if x)
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(md(f"**{r.subject}**" + (f"  \n{detail}" if detail else "")), width="stretch")
                st.button("✅" if r.key in voted else "👍", key=f"vote_{r.ids[0]}", disabled=r.key in voted,
                          on_click=vote_for, args=(r.ids[0], r.key, voter))


if st.query_params.get("page") == "ideas":
    public_idea_page()
    st.stop()


# ---- password gate (set app_password in secrets); everything below needs it ----
password = _secret("app_password")
if password and not st.session_state.get("authed"):
    header("Booth Tracker")
    entered = st.text_input("Password", type="password")
    if entered == password:
        st.session_state.authed = True
        st.rerun()
    elif entered:
        st.error("Wrong password")
    st.stop()

# 🧪 Test mode starts off, unless start_in_test_mode = true in secrets (e.g. on your computer)
st.session_state.setdefault("test_mode", bool(_secret("start_in_test_mode")))


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
    st.session_state.money_disc = ""
    st.session_state.disc_reason = None
    st.session_state.trade_partner = ""
    st.session_state.trade_received = ""


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


def quote_basket(basket, items, deals, discount=0.0):
    """Price the basket with deals applied, then an optional discount (amount off the whole order).

    Returns a dict with lines (name, qty, unit_price, discount and the final charge for each item),
    applied deals, subtotal (at single prices), after_deals, discount (capped at after_deals) and total.
    The discount is spread over the lines in proportion to what each costs, so per-item reports stay right.
    """
    by_id = items.set_index("item_id")
    lines = [{"item_id": i, "name": by_id.at[i, "name"], "fandom": by_id.at[i, "fandom"],
              "type": by_id.at[i, "type"], "unit_price": float(by_id.at[i, "price"]), "qty": q}
             for i, q in basket.items() if i in by_id.index]
    charges, applied = price_basket(lines, deals.to_dict("records"))
    after_deals = round(sum(charges.values()), 2)
    off = round(min(max(float(discount or 0), 0.0), after_deals) * 100)      # in cents
    left = off
    for n, line in enumerate(lines):
        cents = round(charges[line["item_id"]] * 100)
        share = left if n == len(lines) - 1 else (off * cents // round(after_deals * 100) if after_deals else 0)
        left -= share
        line["discount"] = share / 100
        line["charge"] = (cents - share) / 100
    return {"lines": lines, "applied": applied,
            "subtotal": sum(line["unit_price"] * line["qty"] for line in lines),
            "after_deals": after_deals, "discount": off / 100, "total": round(after_deals - off / 100, 2)}


DISCOUNT_REASONS = ["🤝 Friend", "🩹 Damaged", "📦 Bundle", "✏️ Other"]


def current_discount():
    """The discount typed into the basket (0 if none)."""
    return parse_money(st.session_state.get("money_disc")) or 0.0


# ---- actions (run as button callbacks, before the page redraws) ----
def checkout(event, payment="cash"):
    """Record the basket as one order at an event: a sales row per item, sharing an order_id.

    payment is a PAYMENTS key ("cash", "card", "qr"), saved on every row of the order, or "trade":
    the items are swapped with another artist, so they leave stock at $0, no free gifts are added, and
    who and what you got back go to the "trades" table.
    Free gifts are recorded as extra rows with freebie = TRUE and total 0.
    Lowers stock, remembers the order for "Undo last sale" and empties the basket.
    Refuses if any item no longer has enough stock (e.g. it was sold on another phone).
    """
    is_trade = payment == "trade"
    items = load("items")
    quote = quote_basket(st.session_state.get("basket") or {}, items, load("deals"),
                         0 if is_trade else current_discount())
    if not quote["lines"]:
        return
    if is_trade:
        for line in quote["lines"]:
            line["charge"], line["discount"] = 0.0, 0.0
        quote["total"] = 0.0
    reason = st.session_state.get("disc_reason") or ("✏️ Other" if quote["discount"] else "")
    by_id = items.set_index("item_id")
    gift_qty = {}
    if not is_trade:
        trim_freebies(freebies_allowed(quote["after_deals"], load("freebie_rules")))
        gift_qty = dict(st.session_state.get("freebies", {}))
        for i, q in auto_gifts(items, st.session_state.get("basket") or {}, gift_qty).items():
            gift_qty[i] = gift_qty.get(i, 0) + q
    gifts = [{"item_id": i, "name": by_id.at[i, "name"], "fandom": by_id.at[i, "fandom"],
              "unit_price": float(by_id.at[i, "price"]), "qty": q, "charge": 0.0, "discount": 0.0}
             for i, q in gift_qty.items() if i in by_id.index]

    needed = {}                                  # item_id -> pieces leaving the table (sold + free)
    for line in quote["lines"] + gifts:
        needed[line["item_id"]] = needed.get(line["item_id"], 0) + line["qty"]
    reserved = insights.reserved_stock(load("preorders"), load("preorder_lines"))   # promised pieces can't be sold
    free_stock = {i: by_id.at[i, "stock"] - reserved.get(i, 0) for i in needed}
    short = [f"{by_id.at[i, 'name']} ({free_stock[i]} left"
             + (f", {reserved[i]} reserved for pre-orders)" if reserved.get(i) else ")")
             for i, q in needed.items() if free_stock[i] < q]
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
                     "unit_cost": float(by_id.at[line["item_id"], "unit_cost"]), "payment": payment,
                     "discount": line["discount"], "discount_reason": reason if line["discount"] else ""})
    append_rows("sales", rows)
    save("items", items)

    count = sum(line["qty"] for line in quote["lines"])
    if is_trade:
        partner = (st.session_state.get("trade_partner") or "").strip() or "another artist"
        gave = ", ".join(f"{line['qty']}× {line['name']}" for line in quote["lines"])
        append("trades", {"trade_id": new_id(), "order_id": order_id, "timestamp": timestamp, "event": event,
                          "partner": partner, "gave": gave,
                          "received": (st.session_state.get("trade_received") or "").strip(),
                          "value": quote["subtotal"]})
        st.session_state.last_order = {"order_id": order_id, "count": count, "free": 0, "total": 0.0,
                                       "timestamp": timestamp}
        clear_basket()
        st.session_state.flash = ("success", f"🤝 Traded {count} item{'s' if count != 1 else ''} with {partner}")
        return
    free_count = sum(g["qty"] for g in gifts)
    st.session_state.last_order = {"order_id": order_id, "count": count, "free": free_count,
                                   "total": quote["total"], "timestamp": timestamp}
    clear_basket()
    gift_text = f" + {free_count} free gift{'s' if free_count != 1 else ''} 🎁" if free_count else ""
    if quote["discount"]:
        gift_text += f", {money(quote['discount'])} off ({reason})"
    st.session_state.flash = ("success", f"Sold {count} item{'s' if count != 1 else ''} "
                                         f"for {money(quote['total'])} ({PAYMENTS[payment]}){gift_text}")


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
    save("items", items)
    save("sales", sales[sales["order_id"] != order_id])
    trades = load("trades")
    if (trades["order_id"] == order_id).any():           # undoing a trade removes its trade record too
        save("trades", trades[trades["order_id"] != order_id])
    if (st.session_state.get("last_order") or {}).get("order_id") == order_id:
        st.session_state.last_order = None
    st.session_state.flash = ("info", f"Removed sale of {int(rows['qty'].sum())} item(s), "
                                      f"{money(rows['total'].sum())} (stock restored)")


def add_starter_kit():
    """Fill an empty kit list with KIT_STARTER suggestions."""
    append_rows("kit", [{"kit_id": new_id(), "category": c, "name": n, "qty": q, "notes": notes}
                              for c, n, q, notes in KIT_STARTER])


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
    save("packing", packing)


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
    save("images", images)
    st.session_state.flash = ("success", "Photo saved")


def remove_photo(owner_id):
    """Delete the photo of an item or artwork."""
    images = load("images")
    save("images", images[images["owner_id"] != owner_id])


# ---- customer requests ----
def ask_again(request_id, event):
    """Record one more ask for the same thing as an existing request (the ➕1 button)."""
    requests = load("requests")
    original = requests[requests["request_id"] == request_id].iloc[0]
    append("requests", {**original.to_dict(), "request_id": new_id(), "timestamp": now(), "event": event,
                        "notes": "", "status": "open", "art_id": "", "source": "booth", "contact": "",
                        "voter": ""})
    st.session_state.flash = ("success", f"➕1 for {original['subject']}")


def set_request_status(ids, status, art_id=""):
    """Mark a group of request rows as "idea" (with the new artwork's id) or "dismissed"."""
    requests = load("requests")
    rows = requests["request_id"].isin(ids)
    requests.loc[rows, "status"] = status
    requests.loc[rows, "art_id"] = art_id
    save("requests", requests)


def request_to_idea(ids, subject, fandom, mtype, asks, notes, contacts=""):
    """Turn a customer request into a 💡 Idea artwork in Studio, noting how many asked and who (to tag later)."""
    art_id = new_id()
    note = (f"Customer request, asked {asks}×" + (f" for {mtype}" if mtype else "") + (f". {notes}" if notes else "")
            + (f". Tag when ready: {contacts}" if contacts else ""))
    append("artworks", {"art_id": art_id, "title": subject, "fandom": fandom, "stage": "idea",
                        "target_event": "", "notes": note, "link": "", "created": now()[:10]})
    set_request_status(ids, "idea", art_id)
    st.session_state.flash = ("success", f"Added idea: {subject}")


def move_stage(art_id, step):
    """Move an artwork one drawing stage forward (step=1) or back to revise (step=-1)."""
    artworks = load("artworks")
    i = artworks.index[artworks["art_id"] == art_id][0]
    stages = list(STAGES)
    pos = stages.index(artworks.at[i, "stage"]) if artworks.at[i, "stage"] in stages else 0
    artworks.at[i, "stage"] = stages[max(0, min(len(stages) - 1, pos + step))]
    save("artworks", artworks)


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
            artworks = load("artworks")                    # new merch gets its artwork's themes
            art_themes = artworks.loc[artworks["art_id"] == b["art_id"], "themes"]
            items = pd.concat([items, pd.DataFrame([{
                "item_id": item_id, "fandom": b["fandom"], "type": b["type"], "name": b["name"],
                "price": b["price"], "stock": b["qty"], "active": True, "freebie": False,
                "every_order": False, "unit_cost": round(unit, 4),
                "themes": art_themes.iloc[0] if b["art_id"] and not art_themes.empty else ""}])],
                ignore_index=True)
            batches.at[i, "item_id"] = item_id
            images = load("images")
            art_photo = images[(images["owner_id"] == b["art_id"]) & (b["art_id"] != "")]
            if not art_photo.empty:                        # new merch starts with its artwork's picture
                append("images", {"owner_id": item_id, "data": art_photo.iloc[0]["data"],
                                        "updated": now()})
        batches.at[i, "received"] = now()[:10]
        save("items", items)
        st.session_state.flash = ("success", f"Added {b['qty']} × {b['name']} to stock "
                                             f"({money(unit)} each to make)")
    save("batches", batches)


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
            price = money_input(f"Selling price ({CURRENCY})", f"sell_{key}") or 0.0
        qty = st.number_input("Quantity", min_value=1, step=1, value=10)
        cost = money_input(f"Total cost ({CURRENCY})", f"cost_{key}",
                           help="What the whole batch cost: printing, shipping, materials") or 0.0
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
            append("batches", {**row, "batch_id": new_id(), "qty": int(qty), "cost": cost,
                                     "vendor": vendor.strip(), "method": method, "status": "planned",
                                     "created": now()[:10], "received": ""})
            st.session_state.flash = ("success", f"Added {int(qty)} × {row['name']} to production")
            st.rerun()


# ---- page ----
header("Booth Tracker")
st.toggle("🧪 Test mode", key="test_mode", on_change=clear_basket,       # a basket never crosses over
          help="Try things out on test data. Sales, stock and edits in test mode never touch your real data.")
if data_mode() == "test":
    st.html("<style>.stApp, [data-testid='stHeader'] {background: #FFF4D6 !important;}</style>")
    with st.container(border=True, key="test_banner"):
        st.markdown("🧪 **Test mode is on.** Everything you do here goes to **test data**, not your real data. "
                    "Turn it off before selling for real.")
        if not _secret("test_spreadsheet_url") and _secret("spreadsheet_url"):
            st.caption("Test data is temporary: it's wiped when the app restarts. To keep it, make a second "
                       "Google Sheet, share it with the app's email and add `test_spreadsheet_url` to secrets.")
        with st.expander("Test data tools"):
            st.button("📋 Copy my real data into test", on_click=copy_live_to_test, width="stretch",
                      help="Replaces all test data with your real items, events, sales... Real data isn't changed.")
            st.button("🧹 Clear test data", on_click=clear_test_data, width="stretch",
                      help="Empties all test data. Real data isn't changed.")
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
themes = theme_list()
paid_sales = insights.paid(sales)                 # free gifts and trades don't count as items sold
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
        first, last = insights.event_dates(events, event)
        today = now()[:10]
        c1, c2 = st.columns(2)
        if first and first != last and first <= today <= last:          # during a multi-day event
            todays = ev_sales[ev_sales["timestamp"].str[:10] == today]
            c1.metric(f"Today · Day {insights.day_number(today, first)}", money(todays["total"].sum()))
            c2.metric("Whole event", money(ev_sales["total"].sum()))
            st.caption(f"{int(todays['qty'].sum())} items sold today, {int(ev_sales['qty'].sum())} in total")
        else:
            c1.metric("Event sales", money(ev_sales["total"].sum()))
            c2.metric("Items sold", int(ev_sales["qty"].sum()))

        preorders = load("preorders")
        to_collect = preorders[(preorders["status"] == "ready") & (preorders["collect_event"] == event)]
        if not to_collect.empty:
            describe = lambda df: ", ".join(f"{o.customer} ({o.description}, balance {money(o.price - o.deposit)})"
                                            for o in df.itertuples())
            due_today = to_collect[to_collect["due"] == today]
            others = to_collect[to_collect["due"] != today]
            lines = ([f"📦 **Collecting today:** {describe(due_today)}"] if not due_today.empty else []) + \
                    ([f"📦 {'Also ready' if not due_today.empty else 'Orders to hand over here'}: {describe(others)}"]
                     if not others.empty else [])
            st.info(md("  \n".join(lines) + "  \nMark them collected in 🗓️ Prep → 📝 Orders."))
        reserved = insights.reserved_stock(preorders, load("preorder_lines"))   # promised: not for sale here

        basket = st.session_state.setdefault("basket", {})
        quote = quote_basket(basket, items, deals, current_discount()) if basket else None
        # free gifts go by the price before any discount, so a friend price doesn't cost them their gift
        allowed = freebies_allowed(quote["after_deals"], freebie_rules) if quote else 0
        trim_freebies(allowed)                     # e.g. an item was taken out, so fewer gifts are earned
        freebies = st.session_state.freebies
        auto = auto_gifts(items, basket, freebies)
        by_id = items.set_index("item_id")

        def left_of(item_id):
            """Stock that can still be sold: not in the basket (sold or free) and not reserved for pre-orders."""
            return (by_id.at[item_id, "stock"] - basket.get(item_id, 0) - freebies.get(item_id, 0)
                    - auto.get(item_id, 0) - reserved.get(item_id, 0))

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
                    more = freebie_rules[freebie_rules["min_spend"] > quote["after_deals"] + 0.005]
                    more = more[more["count"] > allowed]
                    if not more.empty:
                        gap = more["min_spend"].min() - quote["after_deals"]
                        st.caption(md(f"🎁 Spend {money(gap)} more for {'another' if allowed else 'a'} free gift"))

                with st.expander("🏷️ Discount", expanded=bool(quote["discount"])):
                    money_input(f"Amount off ({CURRENCY})", "disc")
                    st.pills("Reason", DISCOUNT_REASONS, key="disc_reason")
                if quote["discount"]:
                    reason = st.session_state.get("disc_reason") or "✏️ Other"
                    st.caption(md(f"🏷️ Discount ({reason}): −{money(quote['discount'])} "
                                  f"from {money(quote['after_deals'])}"))

                st.markdown(md(f"### Total {money(quote['total'])}"))
                st.caption("✅ Complete sale, paid by:")
                with st.container(horizontal=True):
                    for key, label in PAYMENTS.items():
                        st.button(label, key=f"pay_{key}", type="primary", width="stretch",
                                  on_click=checkout, args=(event, key))
                with st.expander("🤝 Trade with another artist"):
                    st.caption("Swap these items instead of selling them: they leave your stock, no money "
                               "is recorded.")
                    st.text_input("Traded with", key="trade_partner", max_chars=60,
                                  placeholder="Artist name or @handle")
                    st.text_input("You got (optional)", key="trade_received", max_chars=120,
                                  placeholder="e.g. 2 charms + a print")
                    st.button("🤝 Record trade", key="pay_trade", width="stretch",
                              on_click=checkout, args=(event, "trade"))
                st.button("Clear basket", width="stretch", on_click=clear_basket)

        last = st.session_state.get("last_order")
        if last and not basket:
            gifts = f" + {last['free']} 🎁" if last.get("free") else ""
            st.caption(md(f"Last sale: {last['count']} item(s){gifts} · {money(last['total'])} · "
                          f"{last['timestamp'][11:16]}"))
            st.button("↩️ Undo last sale", on_click=delete_order, args=(last["order_id"],),
                      width="stretch")

        search = st.text_input("Search", key="sell_search", placeholder="🔍 Search items, e.g. shinobu",
                               label_visibility="collapsed").strip().lower()
        fandoms = sorted(f for f in active["fandom"].unique() if f)
        pick = st.pills("Fandom", fandoms, key="fandom_filter") if len(fandoms) > 1 else None
        used = {t for cell in active["themes"] for t in insights.tags(cell)}
        theme_names = [t for t in themes["name"] if t in used]
        theme_pick = st.pills("Theme", theme_names, key="theme_filter", label_visibility="collapsed",
                              format_func=lambda t: theme_label(t, themes)) if theme_names else None
        show_photos = active["item_id"].isin(photos.keys()).any() and st.checkbox(
            "📷 Show photos", value=True, key="show_photos")
        shown = active if not pick else active[active["fandom"] == pick]
        if theme_pick:
            shown = shown[shown["themes"].map(lambda cell: theme_pick in insights.tags(cell)).astype(bool)]
        if search:                                   # match name, fandom, type or theme
            text = (shown["name"] + " " + shown["fandom"] + " " + shown["type"]
                    + " " + shown["themes"]).str.lower()
            shown = shown[text.str.contains(search, regex=False)]
            if shown.empty:
                st.caption(f"No items match \"{search}\".")

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
                held = f" · 🔒{reserved[item.item_id]} reserved" if reserved.get(item.item_id) else ""
                label = f"{item.name} · {money(item.price)}{deal} · {left} left{held}{warn}"
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
            price = money_input(f"Single price ({CURRENCY})", "item_price") or 0.0
            stock = st.number_input("Stock", min_value=0, step=1)
            for_sale = st.checkbox("For sale", value=True)
            freebie = st.checkbox("🎁 Can be chosen as a free gift")
            every_order = st.checkbox("📎 Give free with every order",
                                      help="e.g. thank-you sticker or name card: untick For sale, tick this")
            item_themes = st.multiselect("Themes (optional)", themes["name"].tolist(),
                                         format_func=lambda t: theme_label(t, themes),
                                         placeholder="e.g. Xmas, Couple")
            if st.form_submit_button("Add item", width="stretch"):
                name = name.strip()
                if not name:
                    st.error("Merch name is required")
                elif name.lower() in items["name"].str.lower().tolist():
                    st.error(f"'{name}' already exists. Edit it below instead")
                else:
                    append("items", {"item_id": new_id(), "fandom": (fandom or "").strip(),
                                           "type": (item_type or "").strip(), "name": name,
                                           "price": price, "stock": int(stock), "active": for_sale,
                                           "freebie": freebie, "every_order": every_order,
                                           "themes": ", ".join(item_themes)})
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
        theme_options = list(dict.fromkeys(themes["name"].tolist()
                                           + [t for cell in items["themes"] for t in insights.tags(cell)]))
        edited = st.data_editor(
            items.sort_values(["fandom", "type", "name"]).set_index("item_id")
            # items without a photo get an invisible 1-pixel image (empty cells would show "None")
            .assign(photo=lambda df: [f"data:image/jpeg;base64,{photos[i]}" if i in photos else BLANK_IMAGE
                                      for i in df.index],
                    themes=lambda df: df["themes"].map(insights.tags)),     # "Xmas, Couple" -> chips
            column_order=["photo", "fandom", "type", "name", "themes", "price", "stock", "unit_cost", "active",
                          "freebie", "every_order"],
            disabled=["photo"],
            column_config={
                "photo": st.column_config.ImageColumn("📷", width="small"),
                "fandom": st.column_config.TextColumn("Fandom"),
                "type": st.column_config.TextColumn("Type"),
                "name": st.column_config.TextColumn("Merch name", required=True),
                "themes": st.column_config.MultiselectColumn("🏷️ Themes", options=theme_options,
                                                             format_func=lambda t: theme_label(t, themes)),
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
                save("items", edited.reset_index().assign(themes=lambda df: df["themes"].map(join_tags)))
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

        with st.expander("🖼️ Price list for your table"):
            st.caption("Makes a printable page of everything for sale, with deals and photos. Open the file, "
                       "then print it or save it as PDF.")
            pl_title = st.text_input("Title", value="Price list", key="pl_title")
            pl_sub = st.text_input("Line under the title (optional)", key="pl_sub",
                                   placeholder="e.g. @your_handle · Cash, card & PayNow accepted")
            pl_group = st.pills("Group by", ["Type", "Fandom"], default="Type", key="pl_group") or "Type"
            pl_photos = st.checkbox("Include photos", value=True, key="pl_photos")
            pl_hide = st.checkbox("Leave out sold-out items", value=True, key="pl_hide")
            st.download_button("⬇️ Download price list", reports.price_list_html(
                items, deals, photos, CURRENCY, pl_title, pl_sub, pl_group.lower(), pl_photos, pl_hide,
                logo_b64=icon_b64()),
                "price-list.html", "text/html", width="stretch")

    st.caption("🎉 Deals, 🎁 free gift rules and 🏷️ the theme list are in 🗓️ Prep → ⚙️ Settings.")


# ---- Settings (lists you set up once and change now and then) ----
def page_settings():
    """Prep: deals, free gift rules, the theme list and commission options, in one place."""
    st.caption("Things you set up once and change now and then. Open a section, edit the table, then save.")
    type_options = sorted(t for t in items["type"].unique() if t)

    with st.expander("🎉 Deals"):
        if not type_options:
            st.info("Give items a **Type** (e.g. Small sticker) in 📦 Inventory to set up deals like 3 for $5.")
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
                save("deals", edited_deals[complete])
                st.session_state.flash = ("success", "Deals saved")
                st.rerun()

    with st.expander("🎁 Free gifts"):
        gift_names = items.loc[items["freebie"], "name"].tolist()
        st.caption(md(f"When a basket reaches **Spend at least**, you choose that many free gifts from the "
                      f"🎁 Freebie items. {CURRENCY}0 means every purchase gets one. Add rows for tiers, "
                      f"e.g. {CURRENCY}15 → 1 and {CURRENCY}30 → 2."))
        if gift_names:
            st.caption("Freebie items now: " + ", ".join(gift_names))
        else:
            st.caption("No items ticked as 🎁 Freebie yet (tick them in 📦 Inventory).")
        edited_rules = st.data_editor(
            freebie_rules, num_rows="dynamic", hide_index=True, width="stretch", key="freebie_editor",
            column_config={
                "min_spend": st.column_config.NumberColumn(f"Spend at least ({CURRENCY})", min_value=0,
                                                           format="%.2f", required=True),
                "count": st.column_config.NumberColumn("Free gifts", min_value=1, step=1, required=True),
            },
        )
        if st.button("💾 Save free gift rules", width="stretch"):
            save("freebie_rules", edited_rules.dropna(subset=["min_spend", "count"]))
            st.session_state.flash = ("success", "Free gift rules saved")
            st.rerun()

    with st.expander("🏷️ Themes"):
        st.caption("Tags for items and artworks, like 🎄 Xmas or 💪 Gym. Give festive themes the months they "
                   "sell in (their season): you get a heads-up 10 weeks before, in ⏰ Coming up and 🎨 Studio, "
                   "and 🔮 Restock won't suggest reprinting them out of season. Leave the months empty for "
                   "all-year themes. Renaming a theme doesn't rename it on items already tagged.")
        edited_themes = st.data_editor(
            themes, num_rows="dynamic", hide_index=True, width="stretch", key="themes_editor",
            column_order=["emoji", "name", "from_month", "to_month"],
            column_config={
                "emoji": st.column_config.TextColumn("Emoji", width="small"),
                "name": st.column_config.TextColumn("Theme", required=True),
                "from_month": st.column_config.SelectboxColumn("Season from", options=insights.MONTHS),
                "to_month": st.column_config.SelectboxColumn("to", options=insights.MONTHS),
            })
        if st.button("💾 Save themes", width="stretch"):
            keep = edited_themes[edited_themes["name"].fillna("").str.strip() != ""].fillna("")
            half = (keep["from_month"] == "") != (keep["to_month"] == "")
            if half.any():
                st.error("Set both months (e.g. Dec to Dec) or neither for: " + ", ".join(keep.loc[half, "name"]))
            else:
                save("themes", keep.assign(name=keep["name"].str.replace(",", " ").str.strip()))
                st.session_state.flash = ("success", "Themes saved")
                st.rerun()
        missing = [t for t in HOLIDAY_THEMES if t[0].lower() not in set(themes["name"].str.lower())]
        if missing:
            st.button("📅 Add festive themes from the calendar", on_click=add_holiday_themes, width="stretch",
                      help="Adds: " + ", ".join(f"{e} {n} ({m1}–{m2})" if m1 != m2 else f"{e} {n} ({m1})"
                                                for n, e, m1, m2 in missing)
                           + ". Remove any you don't want, or adjust their months.")
            st.caption("Adds " + ", ".join(f"{e} {n}" for n, e, *_ in missing)
                       + ". Hari Raya, CNY, Easter, Mid-Autumn and Deepavali move a little each year, so check "
                         "their months.")

    with st.expander("🎨 Commission options"):
        st.caption("What visitors can ask for on your idea page. They pick one of the ✅ open ones. Add a row "
                   "for something new (e.g. A5 print, chibi sticker); untick Open to pause one without deleting "
                   "it. Leave *From* empty to not show a price. Switch requests on/off in 📝 Orders.")
        edited = st.data_editor(
            commission_options(), num_rows="dynamic", hide_index=True, width="stretch", key="commission_editor",
            column_config={
                "name": st.column_config.TextColumn("What", required=True),
                "details": st.column_config.TextColumn("Size / details"),
                "price_from": st.column_config.NumberColumn(f"From ({CURRENCY})", min_value=0, format="%.2f"),
                "open": st.column_config.CheckboxColumn("Open", default=True),
            })
        if st.button("💾 Save commission options", width="stretch"):
            save("commission_options", edited[edited["name"].fillna("").str.strip().ne("")])
            st.session_state.flash = ("success", "Commission options saved")
            st.rerun()
        if open_commission_options().empty:
            st.warning("Nothing is open, so the idea page only shows ideas.")


# ---- Sales ----
def page_sales():
    """After: totals, by fandom/item, free gifts given, all sales, remove a wrong sale."""
    choice = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="sales_filter")
    everything = sales if choice == "All events" else sales[sales["event"] == choice]
    view, gifts = insights.paid(everything), everything[everything["freebie"]]
    trades_given = insights.traded(everything)

    c1, c2 = st.columns(2)
    c1.metric("Total sales", money(view["total"].sum()))
    c2.metric("Items sold", int(view["qty"].sum()))

    # cost of everything that left the table (free gifts included), and costs of doing the event(s)
    everything = everything.assign(cost=everything["qty"] * everything["unit_cost"])
    view = view.assign(cost=view["qty"] * view["unit_cost"])
    ev_costs = load("event_costs")
    ev_costs = ev_costs if choice == "All events" else ev_costs[ev_costs["event"] == choice]
    goods, spent = everything["cost"].sum(), ev_costs["amount"].sum()
    if goods > 0 or spent > 0:
        c3, c4 = st.columns(2)
        c3.metric("Cost to make", money(goods))
        c4.metric("Event costs", money(spent))
        st.metric("Profit after costs", money(view["total"].sum() - goods - spent))
        st.caption("Cost to make uses each item's cost per piece (Inventory or Studio batches; free gifts "
                   "included). Event costs (table fee, travel...) are added in 🗓️ Prep → 📅 Events.")

    if not view.empty:
        by_pay = insights.by_payment(view)
        paid_by = dict(zip(by_pay["payment"], by_pay["revenue"]))
        st.caption(md("Paid by: " + " · ".join(f"{label} {money(paid_by.get(key, 0.0))}"
                                                for key, label in PAYMENTS.items())
                      + (f" · order deposits {money(paid_by['deposit'])}" if paid_by.get("deposit") else "")
                      + (f" · before tracking {money(paid_by['unknown'])}" if paid_by.get("unknown") else "")))
        if view["discount"].sum() > 0:
            by_reason = view[view["discount"] > 0].groupby("discount_reason")["discount"].sum()
            st.caption(md(f"🏷️ Discounts given: {money(view['discount'].sum())} ("
                          + ", ".join(f"{r or 'Other'} {money(v)}" for r, v in by_reason.items()) + ")"))

    if everything.empty:
        st.info("No sales yet.")
    else:
        total_col = st.column_config.NumberColumn("Total", format=f"{CURRENCY}%.2f")

        first, last = insights.event_dates(events, choice)
        if choice != "All events" and first != last:
            st.subheader("By day")
            show_table(insights.by_day(view, first)[["label", "date", "revenue", "orders", "sold"]],
                         hide_index=True, width="stretch",
                         column_config={"label": "Day", "date": "Date", "revenue": total_col, "orders": "Orders",
                                        "sold": "Items"})

        if view["fandom"].ne("").any():
            st.subheader("By fandom")
            by_fandom = (view.assign(fandom=view["fandom"].replace("", "Other"))
                         .groupby("fandom", as_index=False)[["qty", "total"]].sum()
                         .sort_values("total", ascending=False))
            show_table(by_fandom, hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "qty": "Sold", "total": total_col})

        st.subheader("By item")
        by_item = (view.groupby("item", as_index=False)[["qty", "total", "cost"]].sum()
                   .sort_values("total", ascending=False))
        by_item["profit"] = by_item["total"] - by_item["cost"]
        show_table(by_item, hide_index=True, width="stretch",
                     column_order=["item", "qty", "total"] + (["profit"] if view["cost"].sum() > 0 else []),
                     column_config={"item": "Item", "qty": "Sold", "total": total_col,
                                    "profit": st.column_config.NumberColumn("Profit", format=f"{CURRENCY}%.2f")})

        if not trades_given.empty:
            st.subheader(f"🤝 Traded away: {int(trades_given['qty'].sum())}")
            trades = load("trades")
            trades = trades[trades["order_id"].isin(trades_given["order_id"])].sort_values("timestamp", ascending=False)
            st.caption(md(f"Normal price of what you traded: {money(trades['value'].sum())}. "
                          "It counts as cost to make, like free gifts, not as sales."))
            show_table(trades[["timestamp", "event", "partner", "gave", "received"]], hide_index=True,
                         width="stretch",
                         column_config={"timestamp": "Time", "event": "Event", "partner": "With",
                                        "gave": "You gave", "received": "You got"})

        if not gifts.empty:
            st.subheader(f"🎁 Free gifts given: {int(gifts['qty'].sum())}")
            by_gift = (gifts.assign(value=gifts["unit_price"] * gifts["qty"])
                       .groupby("item", as_index=False)[["qty", "value"]].sum()
                       .sort_values("qty", ascending=False))
            show_table(by_gift, hide_index=True, width="stretch",
                         column_config={"item": "Item", "qty": "Given",
                                        "value": st.column_config.NumberColumn("Normal price",
                                                                               format=f"{CURRENCY}%.2f")})

        st.subheader("All sales")
        recent = everything.sort_values("timestamp", ascending=False)
        show_table(recent[["timestamp", "event", "fandom", "item", "qty", "total", "freebie"]],
                     hide_index=True, width="stretch",
                     column_config={"timestamp": "Time", "event": "Event", "fandom": "Fandom",
                                    "item": "Item", "qty": "Qty", "total": total_col,
                                    "freebie": st.column_config.CheckboxColumn("🎁")})

        st.download_button("⬇️ Download CSV", recent.to_csv(index=False), "sales.csv",
                           "text/csv", width="stretch")
        if choice != "All events":
            st.download_button("📄 Event report (printable)", reports.event_report_html(
                choice, sales, items, events, load("event_costs"), load("requests"), CURRENCY,
                logo_b64=icon_b64()),
                f"report-{choice}.html", "text/html", width="stretch")

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

    st.divider()
    st.download_button("💾 Backup all data (Excel)", backup_workbook(),
                       f"booth-{'TEST-' if data_mode() == 'test' else ''}backup-{now()[:10]}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    st.caption("Every table in one Excel file, one sheet each. Photos aren't included; they stay in the "
               "Google Sheet.")


def backup_workbook():
    """All tables except photos as one Excel file (bytes), one sheet per table."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as workbook:
        for table in TABLES:
            if table != "images":              # thumbnails are too long for Excel cells
                load(table).to_excel(workbook, sheet_name=table, index=False)
    return buf.getvalue()

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
            show_table(fd, hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "revenue": money_col("Sales"), "sold": "Pieces"})

        st.subheader("Fandom × product type")
        ft = insights.fandom_by_type(scoped, items)
        st.caption("Darker = more sales. Empty squares are combinations you haven't sold yet: "
                   "a gap, or an idea.")
        st.altair_chart(insights.heatmap(ft, CURRENCY), width="stretch", theme=None)
        with st.expander("📋 Numbers"):
            show_table(ft.sort_values("revenue", ascending=False), hide_index=True, width="stretch",
                         column_config={"fandom": "Fandom", "type": "Type", "revenue": money_col("Sales"),
                                        "sold": "Pieces"})

        by_theme = insights.by_theme(scoped, items)
        if not by_theme.empty:
            st.subheader("Themes")
            st.caption("Sales of items tagged with each theme (an item with two themes counts in both). "
                       "Tag items in 📦 Inventory; their earlier sales count too.")
            labelled = by_theme.assign(theme=by_theme["theme"].map(lambda t: theme_label(t, themes)))
            st.altair_chart(insights.bar_chart(labelled, "theme", "revenue", CURRENCY, "Sales"),
                            width="stretch", theme=None)
            fth = insights.fandom_by_theme(scoped, items)
            if fth["fandom"].nunique() > 1 and fth["theme"].nunique() > 1:
                st.caption("Fandom × theme: which fandoms sell in which themes. Empty squares are untried mixes.")
                st.altair_chart(insights.heatmap(fth, CURRENCY, column="theme"), width="stretch", theme=None)
            with st.expander("📋 Numbers"):
                show_table(labelled, hide_index=True, width="stretch",
                           column_config={"theme": "Theme", "revenue": money_col("Sales"), "sold": "Pieces"})

        ev = insights.by_event(scoped, events, load("event_costs"))
        if scope == "All events" and len(ev) > 1:
            st.subheader("Events compared")
            has_costs = (ev["costs"] > 0).any() or (ev["goods"] > 0).any()
            measure, title = ("profit", "Profit after costs") if has_costs else ("revenue", "Sales")
            if has_costs:
                st.caption("Profit = sales − cost to make − event costs (table fee, travel...).")
            st.altair_chart(insights.bar_chart(ev, "event", measure, CURRENCY, title,
                                               order=ev["event"].tolist()), width="stretch", theme=None)
            with st.expander("📋 Numbers"):
                show_table(ev[["event", "date", "revenue", "costs", "profit", "sold", "orders", "avg_order"]],
                             hide_index=True, width="stretch",
                             column_config={"event": "Event", "date": "Date", "revenue": money_col("Sales"),
                                            "costs": money_col("Event costs"), "profit": money_col("Profit"),
                                            "sold": "Pieces", "orders": "Orders",
                                            "avg_order": money_col("Avg order")})

        first, last = insights.event_dates(events, scope)
        days = insights.by_day(scoped, first) if scope != "All events" and first != last else None
        if days is not None and len(days) > 1:
            st.subheader("Day by day")
            st.altair_chart(insights.bar_chart(days, "label", "revenue", CURRENCY, "Sales",
                                               order=days["label"].tolist()), width="stretch", theme=None)
            with st.expander("📋 Numbers"):
                show_table(days[["label", "date", "revenue", "orders", "sold"]], hide_index=True, width="stretch",
                             column_config={"label": "Day", "date": "Date", "revenue": money_col("Sales"),
                                            "orders": "Orders", "sold": "Pieces"})

        hours = insights.by_hour(scoped)
        if len(hours) > 1:
            st.subheader("Busiest hours")
            st.caption("When orders happened. Handy for planning breaks and restocking the table.")
            st.altair_chart(insights.hour_chart(hours), width="stretch", theme=None)


# ---- Requests (what customers ask for at the booth) ----
def page_requests():
    """At the booth: note what customers ask for, and tap ➕1 when someone asks for the same thing."""
    requests = load("requests")
    waiting = int((load("preorders")["status"] == "request").sum())
    if waiting:
        st.info(f"🎨 {waiting} commission request{'s' if waiting > 1 else ''} from your idea page waiting for "
                "an answer: 🗓️ Prep → 📝 Orders.")
    names = events["name"].tolist()
    if not names:
        st.info("Add an event first: 🗓️ Prep → 📅 Events.")
        return
    selling = st.session_state.get("event")                 # default to the event chosen on the Sell tab
    req_event = st.selectbox("Event", names, key="req_event",
                             index=names.index(selling) if selling in names else 0)

    with st.form("add_request", clear_on_submit=True):
        subject = st.text_input("What do they want?", placeholder="e.g. Gojo, Anya eating peanuts")
        known_fandoms = sorted((set(items["fandom"]) | set(requests["fandom"])) - {""})
        req_fandom = st.selectbox("Fandom", known_fandoms, index=None, accept_new_options=True,
                                  placeholder="Pick or type a new one")
        known_types = sorted((set(items["type"]) | set(requests["type"])) - {""})
        req_type = st.selectbox("Merch type (optional)", known_types, index=None, accept_new_options=True,
                                placeholder="e.g. Big sticker, A6 print")
        req_notes = st.text_input("Notes (optional)", placeholder="e.g. would buy 2, wants holo")
        if st.form_submit_button("💬 Save request", width="stretch"):
            if not subject.strip():
                st.error("Write what they asked for")
            else:
                append("requests", {"request_id": new_id(), "timestamp": now(), "event": req_event,
                                    "subject": subject.strip(), "fandom": (req_fandom or "").strip(),
                                    "type": (req_type or "").strip(), "notes": req_notes.strip(),
                                    "status": "open", "art_id": "", "source": "booth", "contact": ""})
                st.session_state.flash = ("success", f"Saved request: {subject.strip()}")
                st.rerun()

    with st.expander("📣 Share the idea page (QR code)"):
        link = idea_page_link()
        st.caption("Customers and friends can suggest and vote on ideas here, without a password. "
                   "They only see the idea form and the most-requested ideas, nothing else. "
                   "Their ideas show up in this list, marked 🌐.")
        st.code(link, language=None)
        st.image(qr_png(link), width=220)
        st.download_button("⬇️ Download QR code", qr_png(link, scale=16), "idea-page-qr.png", "image/png",
                           width="stretch")

    asked = insights.group_requests(requests)
    if asked.empty:
        st.caption("Requests you save show up here. Tap ➕1 when another customer asks for the same thing.")
        return
    st.subheader("Most requested")
    st.caption("Tap ➕1 when someone asks for the same thing. Turn requests into ideas in 🗓️ Prep → 🎨 Studio.")
    for r in asked.head(15).itertuples():
        detail = " · ".join(x for x in [r.fandom, r.type, f"🌐 {r.online} online" if r.online else ""] if x)
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(md(f"**{r.subject}** ×{r.asks}" + (f"  \n{detail}" if detail else "")), width="stretch")
            st.button("➕1", key=f"again_{r.ids[0]}", on_click=ask_again, args=(r.ids[0], req_event))


def idea_page_link():
    """The public idea page's address: secrets public_url if set, else this app's own address + ?page=ideas."""
    base = _secret("public_url") or str(st.context.url or "").split("?")[0]
    return base.rstrip("/") + "/?page=ideas"


def qr_png(text, scale=8):
    """A QR code for `text` as PNG bytes (deep plum on white, easy to scan)."""
    import segno
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2, dark="#2E1A47", light="#FFFFFF")
    return buf.getvalue()


# ---- Cash up (end-of-day check of the takings) ----
def save_cashup(event, float_key, counted_key, cash_sales):
    """Save an end-of-day cash count for an event (float, cash sales, counted, difference)."""
    flt = parse_money(st.session_state.get(f"money_{float_key}")) or 0.0
    counted = parse_money(st.session_state.get(f"money_{counted_key}")) or 0.0
    append("cashups", {"cashup_id": new_id(), "timestamp": now(), "event": event, "float": flt,
                             "cash_sales": cash_sales, "counted": counted,
                             "difference": round(counted - flt - cash_sales, 2)})
    st.session_state.flash = ("success", "Cash count saved")


def page_cashup():
    """At the booth: end-of-day check of cash, card and QR takings for an event."""
    names = events["name"].tolist()
    if not names:
        st.info("Add an event first: 🗓️ Prep → 📅 Events.")
        return
    selling = st.session_state.get("event")
    ev = st.selectbox("Event", names, key="cash_event", index=names.index(selling) if selling in names else 0)
    ev_sales = sales[sales["event"] == ev]
    first, last = insights.event_dates(events, ev)
    day = None                                                       # multi-day events are counted per day
    if first and first != last:
        days = pd.date_range(first, last).strftime("%Y-%m-%d").tolist()
        labels = {d: f"Day {i} · {pd.Timestamp(d).strftime('%a %d %b')}" for i, d in enumerate(days, 1)}
        today = now()[:10]
        day = st.pills("Day", days, format_func=labels.get, key=f"cash_day_{ev}",
                       default=today if today in days else days[0]) or (today if today in days else days[0])
        st.caption("Multi-day event: count the cash at the end of each day, with that morning's float.")
        ev_sales = ev_sales[ev_sales["timestamp"].str[:10] == day]
    by_pay = insights.by_payment(ev_sales)
    taken = dict(zip(by_pay["payment"], by_pay["revenue"]))          # e.g. {"cash": 120.0, "qr": 64.0}

    st.subheader("Takings by payment")
    cols = st.columns(len(PAYMENTS))
    for col, (key, label) in zip(cols, PAYMENTS.items()):
        col.metric(label, money(taken.get(key, 0.0)))
    if taken.get("unknown"):
        st.caption(md(f"Plus {money(taken['unknown'])} from sales recorded before payment methods existed."))
    if taken.get("deposit"):
        st.caption(md(f"Plus {money(taken['deposit'])} of order deposits taken earlier (not in today's cash)."))
    st.caption("Check 💳 Card against your card reader app and 📱 QR against your bank app.")

    st.subheader("💵 Count the cash")
    counts = load("cashups")
    counts = counts[counts["event"] == ev].sort_values("timestamp")
    last_float = float(counts.iloc[-1]["float"]) if not counts.empty else 0.0       # last float used, any day
    if day:
        counts = counts[counts["timestamp"].str[:10] == day]
    cash_sales = float(taken.get("cash", 0.0))
    float_key, counted_key = f"float_{ev}_{day or ''}", f"counted_{ev}_{day or ''}"
    flt = money_input(f"Starting float ({CURRENCY}): cash you brought for change", float_key,
                      value=last_float) or 0.0
    counted = money_input(f"Cash counted now ({CURRENCY})", counted_key, placeholder="Count the cash box")
    expected = flt + cash_sales
    st.markdown(md(f"Expected in the cash box: **{money(expected)}**  \n"
                   f"{money(flt)} float + {money(cash_sales)} cash sales"))
    if counted is not None:
        diff = round(counted - expected, 2)
        if abs(diff) < 0.005:
            st.success("✅ The cash matches.")
        elif diff < 0:
            st.warning(md(f"⚠️ Short by {money(-diff)}. Check for a sale tapped as Cash that was paid by card or "
                          "QR, or change given wrongly."))
        else:
            st.info(md(f"Over by {money(diff)}. Maybe a sale wasn't recorded, or was tapped as Card/QR."))
        st.button("💾 Save cash count", width="stretch", on_click=save_cashup,
                  args=(ev, float_key, counted_key, cash_sales))
    if not counts.empty:
        st.caption("Saved counts for this day" if day else "Saved counts for this event")
        show_table(counts[["timestamp", "float", "cash_sales", "counted", "difference"]], hide_index=True,
                     width="stretch",
                     column_config={"timestamp": "Time", **{c: st.column_config.NumberColumn(
                         t, format=f"{CURRENCY}%.2f") for c, t in [("float", "Float"), ("cash_sales", "Cash sales"),
                                                                  ("counted", "Counted"), ("difference", "Diff")]}})


# ---- Restock (what to bring next event, and how each item is doing) ----
def page_restock():
    """After: what to bring / reprint for the next event, and sales per item."""
    if insights.paid(sales).empty:
        st.info("Restock suggestions appear here after your first sales.")
        return
    money_col = lambda title: st.column_config.NumberColumn(title, format=f"{CURRENCY}%.2f")

    st.subheader("🔮 Next event: what to bring")
    # seasons are judged on the next event's date (today if none is planned)
    today = date.today().isoformat()
    upcoming = events[(events["date"] >= today) & (events["status"].str.lower() != "rejected")]
    next_event = upcoming.sort_values("date").iloc[0] if not upcoming.empty else None
    on_day = date.fromisoformat(str(next_event["date"])[:10]) if next_event is not None else date.today()
    off = insights.off_season_items(items, themes, on_day)
    forecast = insights.restock_forecast(sales, items[items["active"]], events,
                                         reserved=insights.reserved_stock(load("preorders"),
                                                                          load("preorder_lines")),
                                         off_season=off)
    st.caption("Based on the average sold per event so far (all events), plus 25% extra, on top of pieces "
               "reserved for pre-orders. A rough guide from past sales, not a promise.")
    need = forecast[forecast["reprint"] > 0]
    if need.empty:
        st.success("You have enough stock of everything that has sold before.")
    else:
        st.warning("Reprint before the next event: " + ", ".join(
            f"{r.name} (+{int(r.reprint)})" for r in need.itertuples()))
    resting = forecast[forecast["off_season"]]
    if not resting.empty:
        st.info(md(f"💤 Off-season {'at ' + next_event['name'] if next_event is not None else 'now'}, "
                   "so no reprint suggested: " + ", ".join(resting["name"])
                   + ". Bring a few if you like; they're back in the list near their season."))
    show_table(forecast.assign(name=[("💤 " if o else "") + n for n, o in zip(forecast["name"],
                                                                              forecast["off_season"])])
               [["name", "avg_per_event", "bring", "stock", "reserved", "reprint"]], hide_index=True,
                 width="stretch",
                 column_order=["name", "avg_per_event", "bring", "stock"]
                 + (["reserved"] if forecast["reserved"].sum() else []) + ["reprint"],
                 column_config={"name": "Item", "avg_per_event": st.column_config.NumberColumn(
                     "Avg / event", format="%.1f"), "bring": "Bring", "stock": "In stock",
                     "reserved": "🔒 Reserved", "reprint": "Reprint"})

    st.subheader("Items")
    scope = st.selectbox("Show", ["All events"] + events["name"].tolist(), key="restock_scope")
    scoped = sales if scope == "All events" else sales[sales["event"] == scope]
    perf = insights.item_performance(scoped, items[items["active"]])
    st.caption("Sold through = share of the pieces you had that sold (sold ÷ (sold + stock left)).")
    show_table(perf[["name", "sold", "revenue", "profit", "stock", "sell_through"]], hide_index=True,
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


PLATFORMS = ["Instagram", "X / Twitter", "Threads", "Facebook", "TikTok"]


def stream_into_page(chunks, state_key):
    """Show Claude's reply as it streams in, keep it in session state; show a friendly message on errors."""
    try:
        st.session_state[state_key] = st.write_stream(chunk.replace("$", r"\$") for chunk in chunks)
    except Exception as error:
        st.error(ai_error_message(error))


def page_ai():
    """After: ask Claude for ideas (what to draw, restock, pricing) or to write a social media post."""
    api_key = _secret("anthropic_api_key")
    if not api_key:
        st.info("Get ideas and social posts from Claude (Anthropic's AI) based on your sales: what to draw "
                "next, what to restock, pricing and deals. To turn it on, add `anthropic_api_key = \"sk-ant-...\"` "
                "to your secrets (an API key from console.anthropic.com; each request costs a few cents).")
        return
    mode = st.pills("Mode", ["💡 Ideas", "📣 Social post"], default="💡 Ideas", key="ai_mode",
                    label_visibility="collapsed") or "💡 Ideas"

    if mode == "📣 Social post":
        kind = st.pills("What's the post about?", list(insights.POST_KINDS), default="thanks", key="post_kind",
                        format_func=insights.POST_KINDS.get) or "thanks"
        platform = st.selectbox("Platform", PLATFORMS, key="post_platform")
        names = events["name"].tolist()
        selling = st.session_state.get("event")
        post_event = st.selectbox("Event (optional)", names, key="post_event", placeholder="No event",
                                  index=names.index(selling) if selling in names else None)
        details = st.text_area("Anything to mention? (optional)", key="post_details", height=80,
                               placeholder="e.g. booth B12, new holo stickers, PayNow accepted")
        st.caption("Sends the post type, event, your merch list and these details to Anthropic's Claude "
                   "(no sales figures or customer details).")
        if st.button("✨ Write post", type="primary", width="stretch"):
            brief = insights.post_brief(kind, platform, details, events, items, sales, post_event)
            stream_into_page(insights.stream_post(api_key, brief), "ai_post")
        elif st.session_state.get("ai_post"):
            st.markdown(st.session_state.ai_post)
        return

    if insights.paid(sales).empty:
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
            brief = insights.ai_brief(scoped, items, events, deals, freebie_rules, load("artworks"), CURRENCY, scope,
                                      load("requests"), load("event_costs"), themes)
            stream_into_page(insights.stream_suggestions(api_key, brief, question), "ai_answer")
        elif st.session_state.get("ai_answer"):
            st.markdown(st.session_state.ai_answer)

# ---- Events ----
EVENT_STATUSES = ["Interested", "Applied", "Accepted", "Paid", "Rejected"]


def coming_up(events, days=60):
    """Upcoming event days and deadlines (apply by / pay by) within `days`, soonest first.

    Deadlines that no longer matter are skipped (e.g. "apply by" once applied, "pay by" once paid).
    Returns a list of (date, days_away, text).
    """
    today = date.today()
    found = []
    for e in events.itertuples():
        status = (e.status or "").lower()
        first, last = insights.event_dates(events, e.name)
        n_days = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1 if first else 1
        checks = [(e.date, f"🎪 {e.name}" + (f" ({n_days} days)" if n_days > 1 else "")
                   + (f" @ {e.location}" if e.location else ""))]
        if first and first < today.isoformat() <= last and status != "rejected":     # a multi-day event is on now
            day_now = (today - date.fromisoformat(first)).days + 1
            found.append((today, 0, f"🎪 {e.name} is on now: Day {day_now} of {n_days}"))
        if status in ("", "interested"):
            checks.append((e.apply_by, f"📝 Apply for {e.name}"))
        if status not in ("paid", "rejected"):
            checks.append((e.pay_by, f"💳 Pay for {e.name}"))
        for when, text in checks:
            try:
                d = date.fromisoformat(str(when)[:10])
            except ValueError:
                continue
            if 0 <= (d - today).days <= days and status != "rejected":
                found.append((d, (d - today).days, text))
    # pre-orders that still need making within 2 weeks of the event they're collected at
    orders = load("preorders")
    unfinished = orders[orders["status"].isin(["taken", "making"])].groupby("collect_event").size()
    for event, n in unfinished.items():
        first, _ = insights.event_dates(events, event)
        if first and 0 <= (date.fromisoformat(first) - today).days <= 14:
            d = date.fromisoformat(first)
            found.append((d, (d - today).days, f"📝 {n} order{'s' if n > 1 else ''} for {event} not ready yet"))
    return sorted(found)


def season_reminders():
    """Heads-ups for festive themes in season now or starting within SEASON_HEADS_UP_DAYS, with what you
    have for them: ideas still being drawn and pieces in stock. A list of Markdown lines, soonest first."""
    artworks = load("artworks")
    lines = []
    for s in insights.season_status(themes, date.today(), SEASON_HEADS_UP_DAYS):
        # astype(bool): an empty table's map() isn't boolean, and pandas would read it as column names
        tagged = lambda df: df[df["themes"].map(lambda cell: s["name"] in insights.tags(cell)).astype(bool)]
        drawing = len(tagged(artworks[artworks["stage"] != "done"]))
        pieces = int(tagged(items[items["active"]])["stock"].clip(lower=0).sum())
        label = theme_label(s["name"], themes)
        soon = f"{s['days'] // 7} weeks" if s["days"] >= 14 else f"{s['days']} day{'s' if s['days'] != 1 else ''}"
        when = (f"**{label} season is on** (until {s['end'].day} {s['end']:%b})" if s["now"] else
                f"**{label} season in {soon}** (from {s['start'].day} {s['start']:%b})")
        have = [f"{drawing} idea{'s' if drawing != 1 else ''} still being drawn" if drawing else "",
                f"{pieces} pieces in stock" if pieces else ""]
        lines.append(when + ": " + (" · ".join(h for h in have if h)
                                    or f"no {s['name']} ideas or merch yet"))
    return lines


def page_events():
    """Prep: convention calendar (deadlines), add events, event costs, and sales/profit per event."""
    upcoming = coming_up(events)
    seasons = season_reminders()
    st.subheader("⏰ Coming up")
    if not upcoming and not seasons:
        st.caption("Nothing in the next 60 days. Add apply-by and pay-by dates in the calendar below.")
    for d, away, text in upcoming:
        when = "today" if away == 0 else "tomorrow" if away == 1 else f"in {away} days"
        line = f"**{text}** · {when} ({d.strftime('%a %d %b')})"
        (st.warning if away <= 7 else st.markdown)(md(line))
    for line in seasons:
        st.markdown(md(line))

    with st.expander("➕ Add event", expanded=events.empty):
        with st.form("add_event", clear_on_submit=True):
            ev_name = st.text_input("Event name", placeholder="e.g. Comic Fiesta 2026")
            ev_date = st.date_input("Date (first day)", value=date.today())
            ev_end = st.date_input("Last day (only for multi-day events)", value=None)
            ev_place = st.text_input("Location (optional)", placeholder="e.g. Suntec City Hall 401")
            ev_status = st.selectbox("Status", EVENT_STATUSES, index=0)
            if st.form_submit_button("➕ Add event", width="stretch"):
                ev_name = ev_name.strip()
                if not ev_name:
                    st.error("Event name is required")
                elif ev_name.lower() in events["name"].str.lower().tolist():
                    st.error(f"'{ev_name}' already exists")
                elif ev_end and ev_end < ev_date:
                    st.error("The last day can't be before the first day")
                else:
                    append("events", {"event_id": new_id(), "name": ev_name, "date": ev_date.isoformat(),
                                      "end_date": ev_end.isoformat() if ev_end and ev_end > ev_date else "",
                                      "location": ev_place.strip(), "status": ev_status, "apply_by": "",
                                      "pay_by": "", "notes": ""})
                    st.session_state.pending_event = ev_name     # select it on the Sell tab
                    st.session_state.flash = ("success", f"Added event {ev_name}")
                    st.rerun()

    if events.empty:
        return

    st.subheader("📅 Convention calendar")
    st.caption("Edit dates, deadlines and status, then save. (Event names can't be changed here, "
               "because sales are filed under them.)")
    date_cols = ("date", "end_date", "apply_by", "pay_by")
    as_dates = events.assign(**{c: pd.to_datetime(events[c], errors="coerce") for c in date_cols})
    edited_events = st.data_editor(
        as_dates.set_index("event_id"), hide_index=True, width="stretch", key="calendar_editor",
        column_order=["name", "date", "end_date", "status", "apply_by", "pay_by", "location", "notes"],
        disabled=["name"],
        column_config={
            "name": "Event", "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "end_date": st.column_config.DateColumn("Last day", format="YYYY-MM-DD",
                                                    help="Only for multi-day events; leave empty for one day"),
            "status": st.column_config.SelectboxColumn("Status", options=EVENT_STATUSES),
            "apply_by": st.column_config.DateColumn("Apply by", format="YYYY-MM-DD"),
            "pay_by": st.column_config.DateColumn("Pay by", format="YYYY-MM-DD"),
            "location": "Location", "notes": "Notes"})
    if st.button("💾 Save calendar", width="stretch"):
        saved = edited_events.reset_index()
        for c in date_cols:
            saved[c] = pd.to_datetime(saved[c], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        saved.loc[saved["end_date"] <= saved["date"], "end_date"] = ""        # same day or earlier = one day
        save("events", saved)
        st.session_state.flash = ("success", "Calendar saved")
        st.rerun()
    costs = load("event_costs")

    st.subheader("💰 Event costs")
    names = events["name"].tolist()
    cost_event = st.selectbox("Event", names, key="cost_event")
    st.caption("Table fee, travel, food... Add a row at the bottom; select a row and press delete to remove it.")
    edited_costs = st.data_editor(
        costs[costs["event"] == cost_event].reset_index(drop=True), num_rows="dynamic", hide_index=True,
        width="stretch", key=f"costs_editor_{cost_event}", column_order=["category", "amount", "note"],
        column_config={
            "category": st.column_config.SelectboxColumn("What", options=COST_CATEGORIES, required=True),
            "amount": st.column_config.NumberColumn(f"Amount ({CURRENCY})", min_value=0, format="%.2f",
                                                    required=True),
            "note": st.column_config.TextColumn("Note"),
        })
    if st.button("💾 Save costs", width="stretch"):
        keep = edited_costs.dropna(subset=["category", "amount"]).copy()
        new_rows = keep["cost_id"].fillna("") == ""
        keep.loc[new_rows, "cost_id"] = [new_id() for _ in range(new_rows.sum())]
        keep["event"] = cost_event
        save("event_costs", pd.concat([costs[costs["event"] != cost_event], keep], ignore_index=True))
        st.session_state.flash = ("success", f"Costs saved for {cost_event}")
        st.rerun()

    st.subheader("All events")
    per_event = insights.by_event(sales, events, costs).set_index("event")   # only events with sales
    summary = events[["name", "date"]].copy()
    summary["sold"] = summary["name"].map(per_event["sold"]).fillna(0).astype(int)
    summary["revenue"] = summary["name"].map(per_event["revenue"]).fillna(0.0)
    summary["costs"] = summary["name"].map(costs.groupby("event")["amount"].sum()).fillna(0.0)
    goods = summary["name"].map(per_event["goods"]).fillna(0.0)
    summary["profit"] = summary["revenue"] - goods - summary["costs"]
    money_col = lambda title: st.column_config.NumberColumn(title, format=f"{CURRENCY}%.2f")
    show_table(summary, hide_index=True, width="stretch",
                 column_config={"name": "Event", "date": "Date", "sold": "Items sold",
                                "revenue": money_col("Sales"), "costs": money_col("Event costs"),
                     "profit": money_col("Profit")})
    st.caption("Profit = sales − cost to make (incl. free gifts) − event costs.")

# ---- Orders (pre-orders and commissions) ----
ORDER_STEPS = {"taken": "📝 Taken", "making": "✏️ Making", "ready": "📦 Ready", "collected": "✅ Collected"}


def move_preorder(preorder_id, step):
    """Move an order one step along Taken → Making → Ready (step=1), or back (step=-1)."""
    preorders = load("preorders")
    i = preorders.index[preorders["preorder_id"] == preorder_id][0]
    steps = ["taken", "making", "ready"]
    pos = steps.index(preorders.at[i, "status"]) if preorders.at[i, "status"] in steps else 0
    preorders.at[i, "status"] = steps[max(0, min(len(steps) - 1, pos + step))]
    save("preorders", preorders)


def cancel_preorder(preorder_id):
    """Mark an order as cancelled (nothing is recorded as a sale)."""
    preorders = load("preorders")
    preorders.loc[preorders["preorder_id"] == preorder_id, "status"] = "cancelled"
    save("preorders", preorders)
    st.session_state.flash = ("info", "Order cancelled")


def accept_commission(preorder_id):
    """Accept a commission request from the public page: it becomes a 📝 Taken order with your price."""
    ss = st.session_state
    price = parse_money(ss.get(f"money_cprice_{preorder_id}"))
    if not price:
        ss.flash = ("error", "Enter the price you agreed before accepting")
        return
    preorders = load("preorders")
    i = preorders.index[preorders["preorder_id"] == preorder_id][0]
    preorders.loc[i, ["price", "deposit", "status"]] = [price, parse_money(ss.get(f"money_cdep_{preorder_id}")) or 0.0,
                                                      "taken"]
    save("preorders", preorders)
    ss.flash = ("success", f"Accepted {preorders.at[i, 'customer']}'s commission ({money(price)}). "
                           "It's in your open orders.")


def decline_commission(preorder_id):
    """Decline a commission request (kept under "Cancelled" so you have a record)."""
    preorders = load("preorders")
    preorders.loc[preorders["preorder_id"] == preorder_id, "status"] = "declined"
    save("preorders", preorders)
    st.session_state.flash = ("info", "Request declined")


def commission_requests_box(preorders):
    """Orders tab: the on/off switch for public commission requests, and the requests waiting for an answer."""
    is_on = get_setting("commissions_open", "TRUE") == "TRUE"
    st.toggle("🌐 Take commission requests on the idea page", value=is_on, key="commissions_open",
              on_change=lambda: set_setting("commissions_open", "TRUE" if st.session_state.commissions_open
                                            else "FALSE"),
              help="Visitors to your idea page can send you a private commission request. "
                   "Turn off when your commission slots are full.")
    offered = open_commission_options()
    if offered.empty:
        st.warning("No commission options are open, so the idea page only shows ideas. "
                   "Open one in 🗓️ Prep → ⚙️ Settings.")
    else:
        st.caption(md("Offering: " + ", ".join(option_label(o) for _, o in offered.iterrows())
                      + ". Change this in ⚙️ Settings."))
    waiting = preorders[preorders["status"] == "request"].sort_values("created")
    if waiting.empty:
        return
    st.subheader(f"📥 Commission requests ({len(waiting)})")
    st.caption("Sent from your idea page. Contact them, agree a price, then accept (or decline).")
    for o in waiting.itertuples():
        with st.container(border=True):
            st.markdown(md(f"**{o.customer}** · {o.contact}  \n{o.description}"))
            st.caption(md(" · ".join(d for d in [f"sent {o.created}", f"needed by {o.due}" if o.due else "", o.notes]
                                     if d)))
            c1, c2 = st.columns(2)
            with c1:
                money_input(f"Agreed price ({CURRENCY})", f"cprice_{o.preorder_id}")
            with c2:
                money_input(f"Deposit paid ({CURRENCY})", f"cdep_{o.preorder_id}")
            with st.container(horizontal=True):
                st.button("✅ Accept", key=f"caccept_{o.preorder_id}", type="primary", width="stretch",
                          on_click=accept_commission, args=(o.preorder_id,))
                st.button("🙅 Decline", key=f"cdecline_{o.preorder_id}", width="stretch",
                          on_click=decline_commission, args=(o.preorder_id,))
    st.divider()


def split_cents(amount, weights):
    """Split an amount over parts in proportion to weights, in whole cents that add up exactly."""
    total_cents, total_weight = round(amount * 100), sum(weights) or 1
    shares = [total_cents * w // total_weight for w in weights[:-1]]
    shares = [int(s) for s in shares]
    return [s / 100 for s in shares + [total_cents - sum(shares)]]


def collect_preorder(preorder_id, payment):
    """The customer collected their order: record the full price as a sale and mark it collected.

    The sale goes to the order's collect-at event (or the event chosen on the Sell tab). Each item in a
    pre-order is taken out of stock and gets its own sale lines; the order's price is split over the items
    in proportion to their normal prices. A commission (no items) is one line.
    """
    preorders, items = load("preorders"), load("items")
    i = preorders.index[preorders["preorder_id"] == preorder_id][0]
    o = preorders.loc[i]
    names = load("events")["name"].tolist()
    event = (o["collect_event"] if o["collect_event"] in names
             else st.session_state.get("event") if st.session_state.get("event") in names else names[0])

    by_id = items.set_index("item_id")
    lines = insights.order_lines(preorders, load("preorder_lines"))
    lines = lines[(lines["preorder_id"] == preorder_id) & lines["item_id"].isin(by_id.index)]
    if lines.empty:                                      # commission, or the item no longer exists
        parts = [{"item_id": o["item_id"], "item": f"{o['kind'].split(' ', 1)[-1]}: {o['description']}",
                  "fandom": "", "qty": max(int(o["qty"]), 1), "unit_cost": 0.0, "weight": 1.0}]
    else:
        parts = [{"item_id": l.item_id, "item": by_id.at[l.item_id, "name"], "fandom": by_id.at[l.item_id, "fandom"],
                  "qty": int(l.qty), "unit_cost": float(by_id.at[l.item_id, "unit_cost"]),
                  "weight": float(by_id.at[l.item_id, "price"]) * int(l.qty) or 1.0} for l in lines.itertuples()]
        for part in parts:
            items.loc[items["item_id"] == part["item_id"], "stock"] -= part["qty"]
        save("items", items)

    # Per item, two rows: the deposit share (taken earlier, payment "deposit", so it doesn't count towards
    # today's cash) and the balance share paid now. The pieces sit on the balance row.
    balance = split_cents(o["price"] - o["deposit"], [p["weight"] for p in parts])
    deposit = split_cents(o["deposit"], [p["weight"] for p in parts])
    order_id, timestamp = new_id(), now()
    rows = []
    for part, paid_now, paid_before in zip(parts, balance, deposit):
        row = {"order_id": order_id, "timestamp": timestamp, "event": event, "item_id": part["item_id"],
               "item": part["item"], "fandom": part["fandom"],
               "unit_price": round((paid_now + paid_before) / part["qty"], 2), "freebie": False,
               "unit_cost": part["unit_cost"], "discount": 0.0, "discount_reason": ""}
        rows.append({**row, "sale_id": new_id(), "qty": part["qty"], "total": paid_now, "payment": payment})
        if paid_before:
            rows.append({**row, "sale_id": new_id(), "qty": 0, "total": paid_before, "payment": "deposit"})
    append_rows("sales", rows)
    preorders.at[i, "status"] = "collected"
    save("preorders", preorders)
    st.session_state.flash = ("success", f"{o['customer']} collected: {money(o['price'])} recorded at {event} "
                                         f"(balance {money(o['price'] - o['deposit'])} paid by {PAYMENTS[payment]})")


def order_summary(qtys, names):
    """A short description of an order's items, e.g. "2× Small sticker - Shinobu, 1× Hashira sheet"."""
    return ", ".join(f"{q}× {names.get(i, '?')}" for i, q in qtys.items())


def save_preorder():
    """Save the "New order" form (read from its widgets): the order, plus one line per item, then clear the form.

    An empty total uses the normal price of the items (with deals); an empty description lists the items.
    """
    ss = st.session_state
    items = load("items")
    names = dict(zip(items["item_id"], items["name"]))
    qtys = {i: int(ss.get(f"po_qty_{i}", 1)) for i in ss.get("po_items", [])}
    normal_price = quote_basket(qtys, items, load("deals"))["total"] if qtys else 0.0
    customer = (ss.get("po_customer") or "").strip()
    description = (ss.get("po_desc") or "").strip() or order_summary(qtys, names)
    if not customer or not description:
        ss.flash = ("error", "Add the customer's name and what they ordered")
        return
    price = parse_money(ss.get("money_order_price"))
    preorder_id = new_id()
    append("preorders", {
        "preorder_id": preorder_id, "created": now()[:10], "kind": ss.get("po_kind", ORDER_KINDS[0]),
        "customer": customer, "contact": (ss.get("po_contact") or "").strip(), "description": description,
        "item_id": "", "qty": sum(qtys.values()) or 1,
        "price": price if price is not None else (normal_price if qtys else 0.0),
        "deposit": parse_money(ss.get("money_order_deposit")) or 0.0,
        "due": ss["po_due"].isoformat() if ss.get("po_due") else "", "collect_event": ss.get("po_collect") or "",
        "status": "taken", "notes": (ss.get("po_notes") or "").strip()})
    if qtys:
        append_rows("preorder_lines", [{"preorder_id": preorder_id, "item_id": i, "qty": q} for i, q in qtys.items()])
    for key in ("po_customer", "po_contact", "po_desc", "po_notes", "money_order_price", "money_order_deposit"):
        ss[key] = ""
    ss["po_items"], ss["po_due"], ss["po_collect"] = [], None, None
    ss.flash = ("success", f"Saved order for {customer}")


def page_orders():
    """Prep: pre-orders and commissions, from taken to collected."""
    preorders = load("preorders")
    commission_requests_box(preorders)
    preorders = preorders[preorders["status"] != "request"]
    with st.expander("➕ New order", expanded=preorders.empty):
        st.selectbox("Kind", ORDER_KINDS, key="po_kind")
        st.text_input("Customer name", key="po_customer")
        st.text_input("Contact (optional)", key="po_contact", placeholder="e.g. @insta_handle or phone")
        names = dict(zip(items["item_id"], items["name"]))
        picked = st.multiselect("Items they ordered", sorted(names, key=names.get), format_func=names.get,
                                key="po_items", placeholder="Choose merch you sell (leave empty for a commission)")
        qtys = {i: st.number_input(f"How many: {names[i]}", min_value=1, step=1, value=1, key=f"po_qty_{i}")
                for i in picked}
        normal = quote_basket(qtys, items, deals)["total"] if qtys else 0.0
        if qtys:
            st.caption(md(f"Normal price, with deals: **{money(normal)}**. Leave the total empty to use it."))
        st.text_input("What they ordered" + (" (optional)" if qtys else ""), key="po_desc",
                      placeholder=order_summary(qtys, names) if qtys else "e.g. A5 bust commission of their OC")
        money_input(f"Total price ({CURRENCY})", "order_price", placeholder=f"{normal:.2f}" if qtys else "0.00")
        money_input(f"Deposit paid ({CURRENCY})", "order_deposit")
        st.date_input("Due (optional)", value=None, key="po_due")
        st.selectbox("Collect at event (optional)", events["name"].tolist(), index=None, key="po_collect",
                     placeholder="Choose an event")
        st.text_input("Notes (optional)", key="po_notes")
        st.button("📝 Save order", type="primary", width="stretch", on_click=save_preorder)

    if preorders.empty:
        st.caption("Orders you take show up here, from 📝 Taken to ✅ Collected.")
        return
    is_open = preorders["status"].isin(insights.OPEN_ORDER_STATUSES)
    owed = (preorders.loc[is_open, "price"] - preorders.loc[is_open, "deposit"]).sum()
    st.caption(md(f"{int(is_open.sum())} open · {money(owed)} still to collect"))

    # prepare for one event: what still has to be made before it, what's ready to pack
    with_event = [e for e in events["name"] if (preorders.loc[is_open, "collect_event"] == e).any()]
    for_event = st.selectbox("For event", ["All events"] + with_event, key="order_event",
                             help="Show only the orders to hand over at one event")
    if for_event != "All events":
        mine = preorders[is_open & (preorders["collect_event"] == for_event)]
        counts = mine["status"].value_counts()
        first, _ = insights.event_dates(events, for_event)
        days_left = (date.fromisoformat(first) - date.today()).days if first else None
        summary = (f"**{for_event}**" + (f" (in {days_left} days)" if days_left and days_left > 0 else "") + ": "
                   + " · ".join(f"{int(counts.get(k, 0))} {label.split(' ', 1)[1].lower()}"
                                for k, label in ORDER_STEPS.items() if k != "collected"))
        not_ready = mine[mine["status"] != "ready"]
        (st.warning if not not_ready.empty and days_left is not None and days_left <= 14 else st.markdown)(
            md(summary + (f"  \nStill to finish: " + ", ".join(f"{o.customer} ({o.description})"
                                                              for o in not_ready.itertuples())
                          if not not_ready.empty else "  \n✅ Everything is ready. Pack them in 🧳 Packing.")))
        preorders = preorders[preorders["collect_event"] == for_event]
        is_open = preorders["status"].isin(insights.OPEN_ORDER_STATUSES)
    show = st.pills("Show", ["Open", "Collected", "Cancelled"], default="Open", key="order_filter") or "Open"
    shown = {"Open": preorders[is_open], "Collected": preorders[preorders["status"] == "collected"],
             "Cancelled": preorders[preorders["status"].isin(["cancelled", "declined"])]}[show]
    if shown.empty:
        st.info("Nothing here.")
    for o in shown.sort_values(["due", "created"]).itertuples():
        with st.container(border=True):
            what = o.description + (f" ×{o.qty}" if o.item_id and o.qty > 1 else "")   # new orders list items
            st.markdown(md(f"**{o.customer}** · {o.kind}  \n{what}"))
            details = [ORDER_STEPS.get(o.status, o.status.title()), f"due {o.due}" if o.due else "",
                       f"collect at {o.collect_event}" if o.collect_event else "", o.contact]
            st.caption(md(" · ".join(d for d in details if d)))
            st.markdown(md(f"{money(o.price)} · deposit {money(o.deposit)} · **balance {money(o.price - o.deposit)}**"))
            if o.notes:
                st.caption(md(o.notes))
            if o.status in ("taken", "making", "ready"):
                with st.container(horizontal=True):
                    st.button("◀", key=f"oback_{o.preorder_id}", disabled=o.status == "taken",
                              on_click=move_preorder, args=(o.preorder_id, -1))
                    if o.status != "ready":
                        nxt = "making" if o.status == "taken" else "ready"
                        st.button(f"Next: {ORDER_STEPS[nxt]} ▶", key=f"onext_{o.preorder_id}", type="primary",
                                  on_click=move_preorder, args=(o.preorder_id, 1))
                    st.button("❌ Cancel", key=f"ocancel_{o.preorder_id}", on_click=cancel_preorder,
                              args=(o.preorder_id,))
                if o.status == "ready":
                    st.caption("✅ Collected, balance paid by:")
                    with st.container(horizontal=True):
                        for key, label in PAYMENTS.items():
                            st.button(label, key=f"collect_{key}_{o.preorder_id}", type="primary", width="stretch",
                                      on_click=collect_preorder, args=(o.preorder_id, key))


# ---- Promo (social media checklist per event + catalog images) ----
def add_starter_promo():
    """Fill an empty promo checklist with PROMO_STARTER suggestions."""
    append_rows("promo_tasks", [{"task_id": new_id(), "task": t, "hint": h} for t, h in PROMO_STARTER])


def page_promo():
    """Prep: tick off social media posts per event, and make catalog images to post."""
    if events.empty:
        st.info("Add an event first: 🗓️ Prep → 📅 Events.")
        return
    names = events["name"].tolist()
    promo_event = st.selectbox("Event", names, key="promo_event")
    tasks = load("promo_tasks")

    st.subheader("✅ Promo checklist")
    if tasks.empty:
        st.caption("A list of posts to do for each event: announce, booth number, catalog, thank-you...")
        st.button("✨ Add starter list", key="promo_starter", on_click=add_starter_promo, width="stretch")
    else:
        packing = load("packing")
        ticks = packing[packing["event"] == promo_event].set_index("kit_id")["packed"]
        done = tasks["task_id"].map(lambda t: bool(ticks.get(f"promo_{t}", False)))
        st.markdown(f"**Done {int(done.sum())} / {len(tasks)}**" + (" 🎉" if done.all() else ""))
        for task, is_done in zip(tasks.itertuples(), done):
            tick_id = f"promo_{task.task_id}"
            key = f"kit_promo_{promo_event}_{task.task_id}"            # "kit_" prefix: crossed out when ticked
            st.checkbox(md(task.task + (f" · _{task.hint}_" if task.hint else "")), value=is_done, key=key,
                        on_change=set_tick, args=(promo_event, tick_id, "packed", key))
        with st.expander("✏️ Edit checklist"):
            edited_tasks = st.data_editor(
                tasks, num_rows="dynamic", hide_index=True, width="stretch", key="promo_editor",
                column_order=["task", "hint"],
                column_config={"task": st.column_config.TextColumn("Task", required=True),
                               "hint": st.column_config.TextColumn("Hint")})
            if st.button("💾 Save checklist", width="stretch"):
                keep = edited_tasks[edited_tasks["task"].fillna("").str.strip() != ""].copy()
                new_rows = keep["task_id"].fillna("") == ""
                keep.loc[new_rows, "task_id"] = [new_id() for _ in range(new_rows.sum())]
                save("promo_tasks", keep)
                st.session_state.flash = ("success", "Checklist saved")
                st.rerun()
    st.caption("Need captions? 📈 After → ✨ AI ideas → 📣 Social post.")

    st.subheader("📸 Catalog images")
    st.caption("Ready-to-post images of what you sell: photos, prices and deals, with your avatar.")
    fmt = st.pills("Size", ["post", "story"], default="post", key="cat_fmt",
                   format_func={"post": "Post (4:5)", "story": "Story (9:16)"}.get) or "post"
    group = st.pills("One image per", ["type", "fandom", "theme"], default="type", key="cat_group",
                     format_func=str.title) or "type"
    if group == "theme":
        st.caption("One collection per theme, e.g. a Xmas catalog. Items without themes are left out.")
    title = st.text_input("Title", value="My merch", key="cat_title", max_chars=40)
    subtitle = st.text_input("Line under the title", key="cat_sub", max_chars=60,
                             placeholder="e.g. @your_handle | Cash, card & PayNow")
    first, last = insights.event_dates(events, promo_event)
    when = ""
    if first:
        a, b = pd.Timestamp(first), pd.Timestamp(last)
        when = a.strftime("%d %b") if a == b else f"{a.strftime('%d')}-{b.strftime('%d %b')}"
    place = events.set_index("name").at[promo_event, "location"]
    footer = st.text_input("Bottom line", key=f"cat_footer_{promo_event}", max_chars=70,
                           value=" · ".join(x for x in [f"See you at {promo_event}", when, place] if x))
    hide_out = st.checkbox("Leave out sold-out items", value=True, key="cat_hide")
    if st.button("🖼️ Make catalog images", type="primary", width="stretch"):
        st.session_state.catalog = catalog.catalog_pages(
            items, deals, photos, CURRENCY, title, subtitle, footer, fmt, group,
            ICON.read_bytes() if ICON.exists() else None, hide_out)
    pages = st.session_state.get("catalog") or []
    if pages:
        st.caption(f"{len(pages)} image{'s' if len(pages) != 1 else ''}: post them as one carousel. "
                   "Tap Download under each, or get them all at once.")
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as z:
            for n, png in enumerate(pages, 1):
                z.writestr(f"catalog-{n}.png", png)
        st.download_button("⬇️ Download all (zip)", zipped.getvalue(), "catalog.zip", "application/zip",
                           width="stretch")
        for n, png in enumerate(pages, 1):
            st.image(png, width=280)
            st.download_button(f"⬇️ Image {n}", png, f"catalog-{n}.png", "image/png", key=f"cat_dl_{n}")


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

        if field == "packed":
            # pre-orders to hand over at this event go in the bag too (ticks saved like kit items)
            orders = load("preorders")
            orders = orders[orders["status"].isin(insights.OPEN_ORDER_STATUSES) & (orders["collect_event"] == kit_event)]
            if not orders.empty:
                st.caption("**📦 Orders to bring**")
                for o in orders.sort_values("customer").itertuples():
                    tick_id = f"order_{o.preorder_id}"
                    label = f"{o.customer}: {o.description}" + (f" ×{o.qty}" if o.item_id and o.qty > 1 else "")
                    if o.status != "ready":
                        label += f" · ⚠️ _not ready yet ({ORDER_STEPS[o.status].split(' ', 1)[1].lower()})_"
                    key = f"kit_{field}_{kit_event}_{tick_id}"
                    st.checkbox(md(label), value=bool(ticks.get(tick_id, False)), key=key,
                                on_change=set_tick, args=(kit_event, tick_id, field, key))

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
                save("kit", edited_kit)
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
        seasons = season_reminders()
        if seasons:
            st.info(md("  \n".join(seasons)))
        with st.expander("💡 New idea", expanded=artworks.empty):
            with st.form("add_art", clear_on_submit=True):
                title = st.text_input("Title", placeholder="e.g. Psyduck in a raincoat")
                art_fandoms = sorted((set(items["fandom"]) | set(artworks["fandom"])) - {""})
                art_fandom = st.selectbox("Fandom", art_fandoms, index=None, accept_new_options=True,
                                          placeholder="Pick or type a new one")
                art_themes = st.multiselect("Themes (optional)", themes["name"].tolist(),
                                            format_func=lambda t: theme_label(t, themes),
                                            placeholder="e.g. Halloween, Couple")
                target = st.selectbox("For event (optional)", events["name"].tolist(), index=None,
                                      placeholder="No deadline")
                notes = st.text_area("Notes", placeholder="Ideas, colours, size...", height=80)
                link = st.text_input("Reference link (optional)", placeholder="Pinterest, Drive, X post...")
                if st.form_submit_button("💡 Add idea", width="stretch"):
                    if not title.strip():
                        st.error("Title is required")
                    else:
                        append("artworks", {"art_id": new_id(), "title": title.strip(),
                                                  "fandom": (art_fandom or "").strip(), "stage": "idea",
                                                  "target_event": target or "", "notes": notes.strip(),
                                                  "link": link.strip(), "created": now()[:10],
                                                  "themes": ", ".join(art_themes)})
                        st.session_state.flash = ("success", f"Added idea: {title.strip()}")
                        st.rerun()

        asked = insights.group_requests(load("requests"))
        if not asked.empty:
            with st.expander(f"💬 Customer requests ({len(asked)})"):
                st.caption("Most asked first. Make it an idea to start drawing it, or dismiss it.")
                for r in asked.itertuples():
                    with st.container(border=True):
                        detail = " · ".join(x for x in [r.fandom, r.type, f"asked {r.asks}×",
                                                        f"🌐 {r.online} online" if r.online else "",
                                                        f"at {r.events}" if r.events else ""] if x)
                        st.markdown(md(f"**{r.subject}**  \n{detail}"))
                        if r.notes:
                            st.caption(md(r.notes))
                        if r.contacts:
                            st.caption(md(f"🙋 Asked by: {r.contacts}"))
                        with st.container(horizontal=True):
                            st.button("💡 Make it an idea", key=f"reqidea_{r.ids[0]}", type="primary",
                                      on_click=request_to_idea,
                                      args=(r.ids, r.subject, r.fandom, r.type, r.asks, r.notes, r.contacts))
                            st.button("✖ Dismiss", key=f"reqdis_{r.ids[0]}",
                                      on_click=set_request_status, args=(r.ids, "dismissed"))

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
                    emojis = theme_emojis(art.themes, themes)
                    heading = art.title + (f" · {art.fandom}" if art.fandom else "") + (f" {emojis}" if emojis else "")
                    with st.expander(md(heading)):
                        if art.art_id in photos:
                            st.image(photo_bytes(art.art_id), width=200)
                        st.file_uploader("📷 Progress picture" + (" (replace)" if art.art_id in photos else ""),
                                         type=PHOTO_TYPES, key=f"up_{art.art_id}",
                                         on_change=set_photo, args=(art.art_id, f"up_{art.art_id}"))
                        details = [themes_text(art.themes, themes),
                                   f"📅 for {art.target_event}" if art.target_event else "",
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
                                current = insights.tags(art.themes)
                                new_themes = st.multiselect(
                                    "Themes", list(dict.fromkeys(themes["name"].tolist() + current)),
                                    default=current, format_func=lambda t: theme_label(t, themes))
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
                                                     ["title", "fandom", "target_event", "notes", "link",
                                                      "themes"]] = [
                                            new_title.strip() or art.title, new_fandom.strip(),
                                            new_target or "", new_notes.strip(), new_link.strip(),
                                            ", ".join(new_themes)]
                                    save("artworks", artworks)
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
            show_table(done_view.sort_values("received", ascending=False)
                         [["received", "name", "qty", "cost", "per_piece", "vendor"]],
                         hide_index=True, width="stretch",
                         column_config={"received": "Received", "name": "Item", "qty": "Qty",
                                        "cost": st.column_config.NumberColumn("Cost", format=f"{CURRENCY}%.2f"),
                                        "per_piece": st.column_config.NumberColumn("Each",
                                                                                   format=f"{CURRENCY}%.2f"),
                                        "vendor": "Printer / shop"})


# ---- menu: Prep / At the booth / After, each with its own tabs ----
MENU = {
    "🗓️ Prep": [("🎨 Studio", page_studio), ("📦 Inventory", page_inventory), ("📝 Orders", page_orders),
                ("📅 Events", page_events), ("📣 Promo", page_promo),
                ("🧳 Packing", lambda: page_kit("packed")), ("⚙️ Settings", page_settings)],
    "🛒 At the booth": [("🛒 Sell", page_sell), ("💬 Requests", page_requests), ("💵 Cash up", page_cashup),
                       ("🧳 Pack up", lambda: page_kit("returned"))],
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
