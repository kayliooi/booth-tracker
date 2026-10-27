"""Data storage: Google Sheets when configured, otherwise local CSV files.

Both backends expose the same methods:
    load(table)               -> DataFrame
    append(table, row)        -> add one row (dict)
    append_rows(table, rows)  -> add several rows (list of dicts) in one go
    save(table, df)           -> replace the whole table
"""
from pathlib import Path

import pandas as pd

TABLES = {
    # active = for sale on the Sell tab; freebie = can be chosen as a free gift;
    # every_order = added free to every order automatically (thank-you sticker, name card)
    # unit_cost = what one piece cost to make (average over received batches)
    "items": ["item_id", "fandom", "type", "name", "price", "stock", "active", "freebie", "every_order",
              "unit_cost"],
    # date = event day; apply_by / pay_by = convention deadlines; status: interested/applied/accepted/paid/rejected
    "events": ["event_id", "name", "date", "location", "status", "apply_by", "pay_by", "notes"],
    # pre-orders (of an existing item) and commissions taken from customers; the full price is
    # recorded as a sale when collected. status: taken/making/ready/collected/cancelled
    "preorders": ["preorder_id", "created", "kind", "customer", "contact", "description", "item_id", "qty",
                  "price", "deposit", "due", "collect_event", "status", "notes"],
    # one row per item sold; items bought together share an order_id. Free gifts have
    # freebie = TRUE and total 0 (unit_price keeps the normal price). unit_cost is copied
    # from the item at the time of sale, for profit.
    "sales": ["sale_id", "order_id", "timestamp", "event", "item_id", "item", "fandom",
              "qty", "unit_price", "total", "freebie", "unit_cost", "payment", "discount", "discount_reason"],
    # money spent to do an event (table fee, travel, food...), for profit after costs
    "event_costs": ["cost_id", "event", "category", "amount", "note"],
    # end-of-day cash counts: expected = float + cash sales; difference = counted - expected
    "cashups": ["cashup_id", "timestamp", "event", "float", "cash_sales", "counted", "difference"],
    # drawings from idea to finished art (stage: idea/sketch/colour/shade/done)
    "artworks": ["art_id", "title", "fandom", "stage", "target_event", "notes", "link", "created"],
    # production runs: art_id is blank for reprints; item_id is filled in once received
    # method: order (from a printer) or self (print myself); status follows that method's steps
    "batches": ["batch_id", "art_id", "item_id", "name", "fandom", "type", "price", "qty", "cost",
                "vendor", "method", "status", "created", "received"],
    # what customers asked for, one row per ask (asking again / voting = another row);
    # status: open, idea (turned into an artwork, art_id set) or dismissed;
    # source: booth (typed in at the booth) or online (the public idea page); contact: optional name/@handle
    "requests": ["request_id", "timestamp", "event", "subject", "fandom", "type", "notes", "status", "art_id",
                 "source", "contact"],
    # one small JPEG thumbnail per item or artwork (owner_id = item_id or art_id), base64 text
    # so it fits in a single Google Sheets cell (max 50,000 characters)
    "images": ["owner_id", "data", "updated"],
    # "qty for price" deals on any mix of items of one type, e.g. Small sticker, 3, 5
    "deals": ["type", "qty", "price"],
    # spend at least min_spend (after deals) -> count free gifts; the highest rule reached applies
    "freebie_rules": ["min_spend", "count"],
    # booth kit (display, decor, tools...): things to bring, not for sale
    "kit": ["kit_id", "category", "name", "qty", "notes"],
    # checklist ticks per event: packed = before leaving, returned = packed up at the end
    "packing": ["event", "kit_id", "packed", "returned"],
}


def _num(s):
    """Convert a column to numbers, ignoring thousands commas. Unreadable values become NaN."""
    return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")


def _bool(s):
    """Convert a column of TRUE/FALSE (or 1/0, yes/no) text to booleans."""
    return s.map(lambda v: str(v).strip().upper() in ("TRUE", "1", "YES")).astype(bool)


def _coerce(table, df):
    """Put columns in a fixed order with the right types."""
    # missing columns (e.g. data saved before a column existed) start as blank text
    df = df.reindex(columns=TABLES[table], fill_value="").reset_index(drop=True)
    if table == "items":
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
        df["stock"] = _num(df["stock"]).fillna(0).astype(int)
        df["active"] = _bool(df["active"])
        df["freebie"] = _bool(df["freebie"])
        df["every_order"] = _bool(df["every_order"])
        df["unit_cost"] = _num(df["unit_cost"]).fillna(0.0).astype(float)
    elif table == "sales":
        df["qty"] = _num(df["qty"]).fillna(0).astype(int)
        df["unit_price"] = _num(df["unit_price"]).fillna(0.0).astype(float)
        df["total"] = _num(df["total"]).fillna(0.0).astype(float)
        df["freebie"] = _bool(df["freebie"])
        df["unit_cost"] = _num(df["unit_cost"]).fillna(0.0).astype(float)
        df["discount"] = _num(df["discount"]).fillna(0.0).astype(float)
    elif table == "preorders":
        df["qty"] = _num(df["qty"]).fillna(1).astype(int)
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
        df["deposit"] = _num(df["deposit"]).fillna(0.0).astype(float)
    elif table == "event_costs":
        df["amount"] = _num(df["amount"]).fillna(0.0).astype(float)
    elif table == "cashups":
        for col in ("float", "cash_sales", "counted", "difference"):
            df[col] = _num(df[col]).fillna(0.0).astype(float)
    elif table == "batches":
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
        df["qty"] = _num(df["qty"]).fillna(0).astype(int)
        df["cost"] = _num(df["cost"]).fillna(0.0).astype(float)
    elif table == "freebie_rules":
        df["min_spend"] = _num(df["min_spend"]).fillna(0.0).astype(float)
        df["count"] = _num(df["count"]).fillna(0).astype(int)
    elif table == "deals":
        df["qty"] = _num(df["qty"]).fillna(0).astype(int)
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
    elif table == "kit":
        df["qty"] = _num(df["qty"]).fillna(1).astype(int)
    elif table == "packing":
        df["packed"] = _bool(df["packed"])
        df["returned"] = _bool(df["returned"])
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str)
    if table == "sales":
        # sales from before baskets existed are each their own order
        df["order_id"] = df["order_id"].where(df["order_id"] != "", df["sale_id"])
    return df


class CsvStore:
    """Local CSV files, for testing on a computer."""

    def __init__(self, folder="data"):
        """Use CSV files in `folder`, creating the folder if needed."""
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def _path(self, table):
        """Return the CSV file path for a table."""
        return self.folder / f"{table}.csv"

    def load(self, table):
        """Read a table from its CSV file; an empty table if the file doesn't exist yet."""
        path = self._path(table)
        if path.exists():
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        else:
            df = pd.DataFrame(columns=TABLES[table])
        return _coerce(table, df)

    def save(self, table, df):
        """Overwrite the table's CSV file with `df`."""
        _coerce(table, df).to_csv(self._path(table), index=False)

    def append(self, table, row):
        """Add one row (dict) to the end of the table."""
        self.append_rows(table, [row])

    def append_rows(self, table, rows):
        """Add several rows (list of dicts) to the end of the table."""
        df = pd.concat([self.load(table), pd.DataFrame(rows)], ignore_index=True)
        self.save(table, df)


class SheetsStore:
    """One Google Sheet, one worksheet (tab) per table. Tabs are created if missing."""

    def __init__(self, creds, spreadsheet_url):
        """Log in with the service account `creds` (dict from secrets) and open the sheet at `spreadsheet_url`."""
        import gspread
        self._gspread = gspread
        self.sh = gspread.service_account_from_dict(dict(creds)).open_by_url(spreadsheet_url)
        self._ws = {}

    def _sheet(self, table):
        """Return the worksheet for a table, creating it with a header row if missing. Cached per table.

        If the header row is out of date (e.g. the app gained a column), the tab is rewritten with
        the current columns so newly appended rows line up with the header.
        """
        if table not in self._ws:
            cols = TABLES[table]
            try:
                ws = self.sh.worksheet(table)
            except self._gspread.WorksheetNotFound:
                ws = self.sh.add_worksheet(title=table, rows=1000, cols=len(cols))
                ws.append_row(cols)
            self._ws[table] = ws
            if ws.row_values(1) != cols:
                if ws.col_count < len(cols):
                    ws.add_cols(len(cols) - ws.col_count)
                self.save(table, self.load(table))
        return self._ws[table]

    def load(self, table):
        """Read a whole worksheet into a DataFrame (first row is the header)."""
        values = self._sheet(table).get_all_values()
        if len(values) <= 1:
            df = pd.DataFrame(columns=TABLES[table])
        else:
            df = pd.DataFrame(values[1:], columns=values[0])
        return _coerce(table, df)

    def save(self, table, df):
        """Overwrite the worksheet with `df`."""
        ws = self._sheet(table)
        rows = [TABLES[table]] + _coerce(table, df).astype(str).values.tolist()
        # Write first, then clear leftover rows below, so a failed write never wipes data
        ws.update(values=rows, range_name="A1", value_input_option="RAW")
        ws.batch_clear([f"A{len(rows) + 1}:Z"])

    def append(self, table, row):
        """Add one row (dict) to the bottom of the worksheet, stored as plain text."""
        self.append_rows(table, [row])

    def append_rows(self, table, rows):
        """Add several rows (list of dicts) to the bottom of the worksheet in one request."""
        self._sheet(table).append_rows([[str(row.get(c, "")) for c in TABLES[table]] for row in rows],
                                       value_input_option="RAW")
