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
    "items": ["item_id", "fandom", "type", "name", "price", "stock", "active"],
    "events": ["event_id", "name", "date"],
    # one row per item sold; items bought together share an order_id
    "sales": ["sale_id", "order_id", "timestamp", "event", "item_id", "item", "fandom",
              "qty", "unit_price", "total"],
    # "qty for price" deals on any mix of items of one type, e.g. Small sticker, 3, 5
    "deals": ["type", "qty", "price"],
}


def _num(s):
    """Convert a column to numbers, ignoring thousands commas. Unreadable values become NaN."""
    return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")


def _coerce(table, df):
    """Put columns in a fixed order with the right types."""
    # missing columns (e.g. data saved before a column existed) start as blank text
    df = df.reindex(columns=TABLES[table], fill_value="").reset_index(drop=True)
    if table == "items":
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
        df["stock"] = _num(df["stock"]).fillna(0).astype(int)
        df["active"] = df["active"].map(lambda v: str(v).strip().upper() in ("TRUE", "1", "YES")).astype(bool)
    elif table == "sales":
        df["qty"] = _num(df["qty"]).fillna(0).astype(int)
        df["unit_price"] = _num(df["unit_price"]).fillna(0.0).astype(float)
        df["total"] = _num(df["total"]).fillna(0.0).astype(float)
    elif table == "deals":
        df["qty"] = _num(df["qty"]).fillna(0).astype(int)
        df["price"] = _num(df["price"]).fillna(0.0).astype(float)
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
