# 🎨 Booth Tracker

Phone-friendly app for tracking inventory and sales at art booths, tagged by event.
Data is saved in a Google Sheet.

The menu at the top groups everything by when you use it. The app opens on **🛒 At the booth**.

### 🗓️ Prep
- **🎨 Studio**: track drawings from 💡 Idea → ✏️ Sketch → 🎨 Colour → 🌗 Shade → ✅ Done (◀ Back to revise). On a finished artwork, **Make merch** starts a production batch (order from a printer, or print yourself). When the batch is received/done, the item is created in Inventory (or its stock goes up). Batch costs set each item's cost per piece, so the Sales tab can show **profit**. Reprints of existing items are under Production.
- **📦 Inventory**: add items with fandom and type, edit price/stock, untick *For sale* to hide an item from the Sell tab. Low-stock warning at 3 or fewer. Also here:
  - **📷 Item photos** (they show next to items on the Sell tab).
  - **🎁 Freebie** and **📎 Every order** ticks: tick *Freebie* on items that can be given away (the spend rules are in ⚙️ Settings). Tick *Every order* on things that go into every bag (thank-you sticker, name card; untick *For sale*).
  - **🖼️ Price list for your table**: download a printable page of everything for sale, grouped by type or fandom, with deals and photos. Open it and print or save as PDF.
- **📝 Orders**: pre-orders and commissions: customer, contact, what, price, deposit, due date and collect-at event. A pre-order can hold **several items** with a quantity each; the app shows their normal price (with deals) and uses it if you leave the total empty, and writes the description for you. Leave the items empty for a commission. Move them 📝 Taken → ✏️ Making → 📦 Ready, then tap how the balance was paid when collected; it's recorded as a sale (the deposit separately, so Cash up stays right). The Sell tab reminds you of orders ready to hand over at that event (orders due today first). Pre-orders of existing merch **reserve** that stock: the Sell tab shows "🔒 N reserved" and won't sell into it, and Restock counts it. Pick an event under **For event** to see what still has to be made before it; ready orders also appear in 🧳 Packing as **📦 Orders to bring**, and ⏰ Coming up warns about unfinished orders in the 2 weeks before an event.
- **📅 Events**: **⏰ Coming up** shows event days and apply-by / pay-by deadlines (warning within 7 days), and "on now: Day 2 of 3" during a multi-day event. **Multi-day events**: set a *Last day* (when adding, or in the calendar). Sales are split into Day 1, Day 2... automatically from their time: Sell shows today's sales next to the whole event, Cash up is counted per day, and Sales, Insights and the event report show a day-by-day breakdown. Add events, keep the **📅 Convention calendar** (dates, status, deadlines, location), enter **💰 event costs** (table fee, travel, food...) and see sales, costs and profit per event.
- **📣 Promo**: per event, a **✅ promo checklist** (announce, booth number, catalog, sneak peeks, reminder, thank-you post; "Add starter list", editable) and **📸 catalog images**: ready-to-post Instagram post (4:5) or story (9:16) images of what you sell, one per type or fandom, with photos, prices, deal badges, your avatar and a "See you at…" line. Download each or all as a zip.
- **🧳 Packing**: a checklist of booth items that aren't for sale (tablecloth, stands, card reader...). "Add starter list" fills in common items; edit the list under "Edit kit list".
- **⚙️ Settings**: the lists you set up once and change now and then, each in its own section:
  - **🎉 Deals** like "any 3 Small stickers for $5"; a deal covers any mix of items of that type.
  - **🎁 Free gifts**: rules like "spend $15 → 1 free gift" (you pick the gift from the 🎁 Freebie items).
  - **🏷️ Themes**: your theme list and festive seasons (see below).
  - **🎨 Commission options**: what visitors can ask for on the idea page (see below).

### 🏷️ Themes and seasons
Tag items and artworks with themes, like 🧧 CNY, 🎃 Halloween, 🎄 Xmas (festive) or 💪 Gym, 💕 Couple, 💼 Work (all-year). An item can have several (e.g. Xmas + Couple).
- **Your theme list** is in 🗓️ Prep → ⚙️ Settings → **🏷️ Themes**: emoji, name, and for festive themes the months they sell in (e.g. CNY Jan–Feb, Xmas Dec–Dec; Nov–Jan works too). Leave the months empty for all-year themes. **📅 Add festive themes from the calendar** adds the ones you don't have yet: 💝 Valentine's (Feb), 🌙 Hari Raya (Feb–Mar), 🐣 Easter (Mar–Apr), 💐 Mother's Day (May), 👔 Father's Day (Jun), 🎐 Summer matsuri (Jul), 🎓 Graduation (Jul, university convocations), 🇸🇬 National Day (Aug), 🥮 Mid-Autumn (Sep), 🪔 Deepavali (Oct–Nov). Hari Raya, CNY, Easter, Mid-Autumn and Deepavali move a little each year, so check their months now and then.
- **Tagging:** in Inventory (the 🏷️ Themes column, or when adding an item) and in 🎨 Studio (new idea / ✏️ Edit). Merch made from an artwork gets the artwork's themes automatically.
- **Sell:** tap a theme under the fandom filter to show only, say, the Xmas items. Search matches themes too.
- **Season heads-up:** from 10 weeks before a festive season (and while it's on), 🎨 Studio and ⏰ Coming up show e.g. "🧧 CNY season in 9 weeks (from 1 Jan): no CNY ideas or merch yet", or how many ideas are still being drawn and how many pieces you have.
- **Restock:** items whose festive themes are out of season at your next event get no reprint suggestion and are marked 💤 (they come back about 6 weeks before their season). All-year and untagged items are always counted.
- **Insights:** sales by theme, and fandom × theme. Themes come from the item, so tagging an item also counts its earlier sales.
- **Promo:** catalog images can be made **one per theme** (e.g. a Xmas collection).
- **AI ideas** knows your themes, what sells in each and which seasons are coming.

### 🛒 At the booth
- **🛒 Sell**: pick the event, tap items to add them to the basket (🔍 search or filter by fandom), add a **🏷️ discount** if needed (friend, damaged, bundle...), then complete the sale by tapping how they paid: **💵 Cash**, **💳 Card** or **📱 QR**. Deals, free gifts and every-order items are applied automatically and stock goes down. **🤝 Trade with another artist** (in the basket) swaps the items instead: they leave stock at $0, you note who and what you got, and Sales lists them as "Traded away" (not sales; their cost counts like free gifts). Tap a basket line to take one out; use "Undo last sale" for mistakes.
- **💬 Requests**: note what customers ask for (what to draw, fandom, merch type). Tap **➕1** when someone asks for the same thing. **📣 Share the idea page** gives you a link and QR code for the public idea page (below). In 🗓️ Prep → 🎨 Studio, *Customer requests* lists them most-asked first: **Make it an idea** adds it to your artworks, or dismiss it. Requests are also included in ✨ AI ideas.
- **💵 Cash up**: end of the day, see takings by Cash / Card / QR, enter your starting float and the cash you counted, and it tells you if the cash box matches, is short or is over. Save the count to keep a record.
- **🧳 Pack up**: at the end of the day, tick off the booth kit again so nothing is left behind.

### 📈 After
- **📊 Sales**: totals by fandom and by item per event or overall, free gifts and discounts given, cost and profit, payment split, the full sales list, CSV download, a printable **📄 event report** (pick one event), remove a wrong sale (restores stock), and **💾 Backup all data** as one Excel file.
- **📈 Insights**: average order, top fandoms, a fandom × product type heatmap (gaps = ideas), events compared and busiest hours.
- **🔮 Restock**: what to bring / reprint for the next event (average sold per event + 25%), and a table of how each item is selling (sold, sell-through, sales, profit).
- **✨ AI ideas** (optional): suggestions from Claude on what to draw next, stock, pricing and deals (tap a quick question or type your own, for all events or one), and **📣 Social post** captions (thank you, see you at, new merch, back in stock) with hashtags, 2 options each. Add `anthropic_api_key` to your secrets to turn it on; each request costs a few cents and sends a sales summary (no customer details) to Anthropic.

### 🌐 Public idea page
Your app link + `?page=ideas` (e.g. `https://your-app.streamlit.app/?page=ideas`) opens a page for customers and friends, **with no password**. At the top they choose:
- **💡 Suggest an idea** (public): suggest what you should draw (idea, fandom, merch type, optional @handle) and 👍 vote for the most-requested ideas.
- **🎨 Ask for a commission** (private): for things made just for them, like two fandoms in one picture or their OC. They describe it and pick what kind (from your list, below), with optional characters/fandoms, budget, needed-by date and a reference link, plus their name and contact (required). **Only you see these**: they never appear in the public vote list. They wait in 🗓️ Prep → 📝 Orders under **📥 Commission requests** (💬 Requests also tells you how many are waiting). Contact them, agree a price, then type the price (and any deposit) and tap **✅ Accept**: it becomes a normal 📝 Taken commission. Or tap **🙅 Decline** (kept under *Cancelled*). Limit: 2 requests per phone per day. When your slots are full, switch off **🌐 Take commission requests on the idea page** in 📝 Orders, and the page only shows ideas.
  - **🎨 Commission options** (in 🗓️ Prep → ⚙️ Settings) is your list of what visitors can ask for: what (e.g. Square print), size/details (e.g. 400 × 400 px), an optional "from" price, and **Open**. Add a row when you start offering something new; untick Open to pause one without deleting it. With one open option the page just tells visitors what you offer; with several they choose one. If nothing is open, the commission choice is hidden. It starts with "Square print, 400 × 400 px".

Visitors see nothing else from the app. Ideas land in your 💬 Requests and 🎨 Studio → Customer requests, marked 🌐, with the @handles so you can tag people. Limits: 5 ideas per phone per day, and one vote per idea per phone, remembered with a small random "voter id" cookie (no personal info), so refreshing doesn't allow voting again. Someone clearing their cookies or using another browser can still vote again; it stops casual repeat votes, not a determined person. Change the page's title and text at the top of `app.py` (`IDEA_PAGE_TITLE`, `IDEA_PAGE_INTRO`). If the QR link looks wrong, set `public_url` in secrets to your app's address.

### 🧪 Test mode (test data vs real data)
Flip **🧪 Test mode** under the title to try things out (new features, practice sales, a friend having a go) without touching your real data. The page turns pale yellow with a "Test mode is on" note so you can't miss it. Each phone/browser has its own switch, so testing on your laptop doesn't affect your phone at the booth. **Test data tools** can copy your real data into test (real data isn't changed) or clear the test data. The public idea page always uses real data.

Where test data is kept:
- **By default:** temporary files (`data_test/`). On Streamlit Cloud they're wiped whenever the app restarts, which is fine for quick tries.
- **To keep it:** make a second Google Sheet (e.g. "Booth Tracker TEST"), share it with the same service-account email as Editor, and add `test_spreadsheet_url = "..."` to your secrets. It must be a different sheet from `spreadsheet_url`.
- **On your computer:** add `start_in_test_mode = true` to `.streamlit/secrets.toml` so local runs start on test data.

**Price boxes work like a cash register:** type digits only and they fill from the right (`4` `5` `0` shows 4.50; `1` `2` `0` `0` shows 12.00), with the number keypad on phones. This applies to item price, batch price and cost, discount, order price and deposit, and the cash count. Prices you edit inside tables (Inventory, Deals, Event costs) are normal number cells.

Free gifts are recorded at $0. Photos (items and artworks) are stored as small 256 px thumbnails in the Google Sheet's `images` tab, so that tab looks like random text; that's normal.

Settings (currency symbol, timezone, low-stock level) are at the top of `app.py`.
Colours and styling (lavender theme, buttons, cards) are in `styles/app.css`.
The logo is `assets/logo.png`; `assets/icon.png` is the round version used for the browser tab, the page headers and the printable pages. Replace `icon.png` (square PNG, transparent corners) to change it.

---

## One-time setup (about 30 minutes)

You need: a Google account and a GitHub account (free).
Everything can be done in your phone's browser. Switch to **"Desktop site"** in the browser menu for the Google Cloud and GitHub pages. It's easier on a computer if you can borrow one once.

### 1. Create the Google Sheet
1. Go to sheets.google.com and create a blank sheet, e.g. "Booth Tracker".
2. Copy its URL. You'll need it in step 4.

The app creates the `items`, `events`, `sales`, `deals`, `freebie_rules`, `kit`, `packing`, `artworks`, `batches`, `images`, `requests`, `event_costs`, `cashups`, `preorders`, `preorder_lines`, `trades`, `promo_tasks`, `commission_options`, `themes` and `settings` tabs by itself.

### 2. Give the app access to Google Sheets
1. Go to console.cloud.google.com and create a new project (any name).
2. Open **APIs & Services → Library**, search for **Google Sheets API** and click **Enable**.
3. Open **IAM & Admin → Service Accounts → Create service account**. Any name works; skip the optional steps.
4. Open the new service account, go to **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
5. Open the `.json` file and copy the `client_email` value (it looks like `...@...iam.gserviceaccount.com`).
6. Back in your Google Sheet, click **Share**, paste that email and give it **Editor** access.

### 3. Put the code on GitHub
1. On github.com, create a **new repository**. Set it to **Private**.
2. Click **Add file → Upload files** and upload `app.py`, `storage.py`, `pricing.py`, `insights.py`, `reports.py`, `catalog.py`, `requirements.txt`,
   `README.md`, and the `styles` and `assets` folders (`app.css` inside `styles`; `logo.png` and `icon.png`
   inside `assets`). `.streamlit/config.toml` isn't needed: the colours are in `styles/app.css`.
   Do **not** upload the `.json` key file, `secrets.toml` or the `data` / `data_test` folders.

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

## Checking that everything still works (tests)
After changing the code, run:
```
py tests\run_all.py
```
It takes about 3–4 minutes and prints PASS/FAIL for each check: selling (deals, free gifts, discounts, trades, undo, cash up), deal pricing, pre-orders and commissions, the public idea page, themes and seasons, test mode, and that every page opens. Add words to run only some, e.g. `py tests\run_all.py selling`.

The tests use a throwaway copy of the app with made-up sample data, never your `data/` folder or Google Sheet. The `tests` folder doesn't need to be uploaded to GitHub (it does no harm if it is).
