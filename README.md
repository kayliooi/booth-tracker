# 🎨 Booth Tracker

Phone-friendly app for tracking inventory and sales at art booths, tagged by event.
Data is saved in a Google Sheet.

The menu at the top groups everything by when you use it. The app opens on **🛒 At the booth**.

### 🗓️ Prep
- **🎨 Studio**: track drawings from 💡 Idea → ✏️ Sketch → 🎨 Colour → 🌗 Shade → ✅ Done (◀ Back to revise). On a finished artwork, **Make merch** starts a production batch (order from a printer, or print yourself). When the batch is received/done, the item is created in Inventory (or its stock goes up). Batch costs set each item's cost per piece, so the Sales tab can show **profit**. Reprints of existing items are under Production.
- **📦 Inventory**: add items with fandom and type, edit price/stock, untick *For sale* to hide an item from the Sell tab. Low-stock warning at 3 or fewer. Also here:
  - **📷 Item photos** (they show next to items on the Sell tab).
  - **🎉 Deals** like "any 3 Small stickers for $5"; a deal covers any mix of items of that type.
  - **🎁 Free gifts**: tick *Freebie* on items that can be given away and set rules like "spend $15 → 1 free gift". Tick **📎 Every order** on things that go into every bag (thank-you sticker, name card; untick *For sale*).
- **📅 Events**: add events and see sales per event.
- **🧳 Packing**: a checklist of booth items that aren't for sale (tablecloth, stands, card reader...). "Add starter list" fills in common items; edit the list under "Edit kit list".

### 🛒 At the booth
- **🛒 Sell**: pick the event, tap items to add them to the basket (filter by fandom), then **Complete sale**. Deals, free gifts and every-order items are applied automatically and stock goes down. Tap a basket line to take one out; use "Undo last sale" for mistakes.
- **🧳 Pack up**: at the end of the day, tick off the booth kit again so nothing is left behind.

### 📈 After
- **📊 Sales**: totals by fandom and by item per event or overall, free gifts given, cost and profit, the full sales list, CSV download, remove a wrong sale (restores stock).
- **📈 Insights**: average order, top fandoms, a fandom × product type heatmap (gaps = ideas), events compared and busiest hours.
- **🔮 Restock**: what to bring / reprint for the next event (average sold per event + 25%), and a table of how each item is selling (sold, sell-through, sales, profit).
- **✨ AI ideas** (optional): suggestions from Claude on what to draw next, stock, pricing and deals. Tap a quick question or type your own, for all events or one. Add `anthropic_api_key` to your secrets to turn it on; each request costs a few cents and sends a sales summary (no customer details) to Anthropic.

Free gifts are recorded at $0. Photos (items and artworks) are stored as small 256 px thumbnails in the Google Sheet's `images` tab, so that tab looks like random text; that's normal.

Settings (currency symbol, timezone, low-stock level) are at the top of `app.py`.
Colours and styling (lavender theme, buttons, cards) are in `styles/app.css`.

---

## One-time setup (about 30 minutes)

You need: a Google account and a GitHub account (free).
Everything can be done in your phone's browser. Switch to **"Desktop site"** in the browser menu for the Google Cloud and GitHub pages. It's easier on a computer if you can borrow one once.

### 1. Create the Google Sheet
1. Go to sheets.google.com and create a blank sheet, e.g. "Booth Tracker".
2. Copy its URL. You'll need it in step 4.

The app creates the `items`, `events`, `sales`, `deals`, `freebie_rules`, `kit`, `packing`, `artworks`, `batches` and `images` tabs by itself.

### 2. Give the app access to Google Sheets
1. Go to console.cloud.google.com and create a new project (any name).
2. Open **APIs & Services → Library**, search for **Google Sheets API** and click **Enable**.
3. Open **IAM & Admin → Service Accounts → Create service account**. Any name works; skip the optional steps.
4. Open the new service account, go to **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
5. Open the `.json` file and copy the `client_email` value (it looks like `...@...iam.gserviceaccount.com`).
6. Back in your Google Sheet, click **Share**, paste that email and give it **Editor** access.

### 3. Put the code on GitHub
1. On github.com, create a **new repository**. Set it to **Private**.
2. Click **Add file → Upload files** and upload `app.py`, `storage.py`, `pricing.py`, `insights.py`, `requirements.txt`,
   the `styles` folder and `.streamlit/config.toml` (keep it inside a `.streamlit` folder).
   Do **not** upload the `.json` key file or `secrets.toml`.

### 4. Deploy on Streamlit Community Cloud (free)
1. Go to share.streamlit.io and sign in with GitHub.
2. Click **Create app**, choose your repository, and set the main file to `app.py`.
3. Open **Advanced settings → Secrets** and paste the contents of `.streamlit/secrets.toml.example`, filled in:
   - `app_password`: a password to open the app (anyone with the link could otherwise edit your data)
   - `spreadsheet_url`: the sheet URL from step 1
   - `[gcp_service_account]`: copy each value from the `.json` file. For `private_key`, copy it exactly, including the `\n` parts.
4. Click **Deploy**. After a minute you get a link like `https://your-app.streamlit.app`.

### 5. Add it to your phone's home screen
Open the link and choose **Add to Home screen** in the browser menu (Safari: Share button → Add to Home Screen). It then opens like an app.

---

## Good to know
- **It needs internet.** Mobile data is fine. Convention Wi-Fi is often bad, so make sure you have data.
- **Open it before the event starts.** Free apps go to sleep after a period of no use and take about 30 seconds to wake up.
- **Your data is safe in the Google Sheet.** You can view it any time, and restarting or redeploying the app doesn't lose anything.
- **To update the app,** upload the changed file to GitHub. Streamlit redeploys automatically.

## Trying it on a computer (optional)
```
pip install -r requirements.txt
streamlit run app.py
```
Without secrets, it saves to local CSV files in a `data/` folder.
