# 🏙️ Bangalore Real Estate Automated Daily Scraper & GSheet Syncer

An automated, **100% zero-cost** real estate intelligence scraper for **Bangalore (Bengaluru), India**. It monitors new residential & commercial launches, pre-launches, RERA registrations, and developer announcements every day at your chosen time, deduplicating records and updating your **Google Sheet**.

---

## ⚡ Zero-Cost Architecture Overview

```
                      ┌───────────────────────────────────────────────┐
                      │    Daily Schedule Trigger (e.g. 8:30 AM IST)  │
                      │   - GitHub Actions Cron (2,000 free mins/mo)  │
                      │   - OR Render Webhook + free cron-job.org     │
                      └──────────────────────┬────────────────────────┘
                                             │
                                             ▼
                      ┌───────────────────────────────────────────────┐
                      │    Hybrid Search Intelligence Layer           │
                      │   - Google Gemini 3.8 Flash (Free Tier)       │
                      │   - Perplexity Sonar Search (Live Citations)  │
                      │   - Karnataka RERA Validator                  │
                      └──────────────────────┬────────────────────────┘
                                             │
                                             ▼
                      ┌───────────────────────────────────────────────┐
                      │         In-Memory Deduplication & Merge       │
                      │   - Keys: RERA Number / Project + Builder     │
                      │   - Enrichment of Price, Amenities, Timelines │
                      └──────────────────────┬────────────────────────┘
                                             │
                                             ▼
                      ┌───────────────────────────────────────────────┐
                      │         Google Sheets Live Sync               │
                      │   - Sheet 1: 'Bangalore_Projects'             │
                      │     (Appends new launches, updates existing)  │
                      │   - Sheet 2: 'Scrape_Run_Logs'                │
                      │     (Timestamp, runtime diagnostics, counts)  │
                      └───────────────────────────────────────────────┘
```

### Why this stack is 100% Zero-Cost:
1. **GitHub Actions**: Provides **2,000 free runner minutes every month** for private and public repositories. A daily 2-minute scraper run consumes only ~60 minutes/month (3% of your free quota).
2. **Google Gemini Flash (Search Grounding)**: Free tier via Google AI Studio allows **15 RPM and 1,500 Requests Per Day** at \$0.
3. **Perplexity API**: Pluggable support for Perplexity developer credits.
4. **Google Cloud Service Account & Sheets API**: Free tier provides 300 read/write requests per minute at \$0 forever.
5. **Render (Optional)**: Free web service tier if you prefer an HTTP webhook API.

---

## 📊 Google Sheets Columns

The scraper automatically formats and manages the following data points in your Google Sheet:

| Column | Header | Description |
|---|---|---|
| A | **Project Name** | Commercial project name (e.g., *Prestige Somerville*, *Sobha Neopolis*) |
| B | **Builder / Developer** | Developer name (Prestige, Brigade, Sobha, Godrej, Assetz, Puravankara, etc.) |
| C | **Locality** | Micro-market (Whitefield, Sarjapur, Devanahalli, Kanakapura Road, etc.) |
| D | **Zone / Sub-Market** | East Bangalore, North Bangalore, South Bangalore, West Bangalore |
| E | **Property Type** | Apartment, Luxury Villa, Plotted Development, Penthouse |
| F | **Configurations (BHK)** | 2 & 3 BHK, 4 BHK Villa, 1200-2400 sq.ft Plots |
| G | **Price Range** | ₹85 L - 1.85 Cr, ₹2.2 Cr onwards, or ₹7,500/sq.ft |
| H | **Project Status** | Newly Launched, Pre-Launch, Under Construction, Ready to Move |
| I | **Karnataka RERA No.** | PRM/KA/RERA/... registration ID |
| J | **Possession Date** | Estimated possession (e.g. Dec 2028, Q3 2027) |
| K | **Units / Land Parcel** | Total acres or units count (e.g. 6.5 Acres / 320 Units) |
| L | **Key Amenities & Highlights** | Metro proximity, lake view, clubhouse size |
| M | **Source URL** | Official launch portal link or developer page |
| N | **Data Source** | Gemini Google Search / Perplexity Sonar |
| O | **First Discovered** | Date & time first logged |
| P | **Last Updated** | Date & time of the latest price or status refresh |

---

## 🗺️ Map Pins & Coordinates (`KRERA_Raw_Projects`)

Every K-RERA registration row carries three extra columns so the registry can be
plotted on a map:

| Column | Header | Description |
|---|---|---|
| J | **Latitude** | Geocoded latitude, blank when the project could not be resolved |
| K | **Longitude** | Geocoded longitude, blank when the project could not be resolved |
| L | **Map Pin Link** | Google Maps link — an exact coordinate pin when geocoded, otherwise a name search so the cell is never dead |
| M | **Geocode Status** | What the geocoder last did with the row and when: `resolved via locationiq 2026-09-26` or `unresolved 2026-09-26` |

**How geocoding works**

- Only **Bengaluru-region** districts are geocoded; the rest of Karnataka is out of scope. That's **5,554** of the 8,943 registrations.
- The backend is **auto-detected** from whichever API key is present, so switching providers is a secret change and nothing else:

| Backend | Key needed | Credit card | Free allowance | Use when |
|---|---|---|---|---|
| **LocationIQ** | yes | **no** | ~5k/day | Working through the backlog — **recommended** |
| **Geoapify** | yes | **no** | ~3k/day | Same, alternative provider |
| **Google** | yes | **yes** | — | You already have billing enabled |
| **Nominatim** | no | no | — | Default; small top-ups only (see below) |

- ⚠️ **Nominatim is the public OpenStreetMap endpoint.** It's donated infrastructure and its usage policy **forbids bulk geocoding**, so its per-run budget is deliberately held at 400. Don't raise it to grind through thousands of rows — use a free-tier key instead, or point `NOMINATIM_ENDPOINT` at your own instance where no such limit applies.
- Free tiers are preferred over Google in the auto-detection order, so a stray Maps key can never silently start billing. Force a specific one with `GEOCODE_BACKEND=locationiq|geoapify|google|nominatim`.
- Matches resolving outside the Bengaluru metropolitan bounding box are discarded rather than written, so a same-named project in another state never produces a wrong pin.
- Each run spends at most `GEOCODE_MAX_PER_RUN` lookups. `0` (the default) means *use the chosen backend's own ceiling*, so you don't have to retune it when switching providers. Rows that already have coordinates are skipped, so a large backlog drains over consecutive runs — the sheet itself is the source of truth for what is done.
- A `429` from any provider **ends that run's geocoding** rather than hammering a limited endpoint; the remaining rows are picked up next time.
- **Never-tried rows go first.** Every free provider reads the same OpenStreetMap data, so re-asking about a known miss tomorrow gets the same answer. Column M records each attempt; a row that failed is retried only after `GEOCODE_RETRY_COOLDOWN_DAYS` (default 30), stalest first, and only once every never-tried row has had its turn. The log's `Geocode queue:` line shows the split.
- Each project is tried under up to **three phrasings** before it counts as a miss: the registered name, the name with phase/wing/block noise stripped (`GODREJ FLORENNE PHASE II` → `GODREJ FLORENNE`, which 17.4% of names need), and the cleaned name with a plain `Bengaluru` qualifier. Later variants cost a lookup each; the run log reports `name variants rescued N` so you can see whether they earn it.
- Registrations that cannot be resolved by name keep an empty Latitude/Longitude and are retried on later runs.
- To turn the whole stage off: `GEOCODE_ENABLED=false`.
- With the **google** backend, a miss is retried through **Places Text Search** (`GOOGLE_PLACES_FALLBACK=true`, the default). Geocoding resolves addresses; a K-RERA project name is a POI, so Places is what finds villa communities and small projects — those resolved **0 of 10** on address geocoding. It runs on misses only, and the run log reports `Places fallback: N calls, M rescued` so you can see what it cost.

### Switching to Google

1. Enable **Geocoding API** *and* **Places API** on the Cloud project, with billing active.
2. Add the key as the `GOOGLE_MAPS_API_KEY` secret.
3. Set the repo variable `GEOCODE_BACKEND=google`.

Step 3 is required: free-tier providers outrank Google in auto-detection precisely so billing never starts by accident, so Google is only used when you ask for it by name.

**Clearing the 5,554-row backlog without any billing**

1. Sign up at [locationiq.com/register](https://locationiq.com/register) — email only, no card.
2. Add the token as the `LOCATIONIQ_API_KEY` repo secret (or put it in `.env` locally).
3. That's it. The next run switches backend automatically and works through ~4,500 rows, finishing the rest the following day.

Verify the provider's current published free limit before raising `GEOCODE_MAX_PER_RUN` beyond the built-in ceiling — these allowances change.

### The `Map_Pins` tab — what agents actually use

Every run rebuilds a **`Map_Pins`** worksheet containing only the projects that have
real coordinates, with `Project Name · Promoter · District · Latitude · Longitude ·
RERA No. · Map Pin Link`. Unresolved projects are deliberately left out — a pin that
isn't a real location has no place on a map.

To publish it:

1. [mymaps.google.com](https://www.google.com/mymaps) → create a map → **Import**
2. Pick the tracker spreadsheet and the **`Map_Pins`** tab
3. Position markers by **Latitude** and **Longitude**; title them by **Project Name**
4. Style by **District / Region** to colour by area, then **Share** the map with your agents

Re-import after a run to refresh, since My Maps takes a snapshot rather than a live feed.

---

## 👥 Sharing the Sheet

Set `SHARE_WITH_EMAILS` to a comma-separated list of Gmail / Workspace addresses
and the pipeline grants them access at the end of each run:

```bash
SHARE_WITH_EMAILS=someone@gmail.com,someone.else@gmail.com
SHARE_ROLE=writer      # reader | commenter | writer
SHARE_NOTIFY=false     # true sends a Drive notification email
```

In GitHub Actions, add `SHARE_WITH_EMAILS` as a repository **secret**; `SHARE_ROLE`
and `SHARE_NOTIFY` are read from repository **variables**. Sharing is idempotent —
re-granting an existing permission is a no-op, and one bad address never blocks
the others.

---

## 🧹 Cleaning Up Existing Duplicate Rows

Rows written *before* the deduplication fix can still be duplicated: the old
keying identified a project by **either** its RERA number **or** its
name + builder, never both, so the same project discovered once with a
registration number and once without became two rows. The pipeline no longer
does this, but historical rows need a one-off pass.

```bash
# 1. Dry run — reads only, writes nothing, prints exactly what would change
python scripts/dedupe_sheet.py

# 2. Apply it
python scripts/dedupe_sheet.py --apply
```

Safety properties:

- **Dry run is the default.** Nothing is merged or deleted without `--apply`.
- **A timestamped JSON backup** of every row is written to `backups/` before anything is touched (`--no-backup` is refused together with `--apply`).
- **Merging reuses `RealEstateAggregator._deduplicate_and_merge`** — the same code the live pipeline runs — so the cleanup cannot drift from pipeline behaviour.
- **The earliest row survives**, preserving its original *First Discovered* date; the cluster's latest *Last Updated* is kept.
- The survivor **absorbs the richer values** from the rows being removed: a real RERA number over a placeholder, a real price over `On Request`, a real possession date over `TBA`, the longest amenities string, and a portal URL over none.
- Rows are deleted **bottom-up in contiguous blocks**, so earlier deletions never shift later row indices.
- Any cluster that does not collapse to exactly one record is **reported and skipped** rather than guessed at.
- Re-running is a **no-op** once the sheet is clean.

Sample dry-run output:

```
[Godrej Athena]
  keep   row 2
  remove row 4
  remove row 6
  survivor gains:
    - price_range: 'On Request' -> '2.5 Cr onwards'
    - rera_number: 'Pending' -> 'PRM/KA/RERA/1251/310/PR/230123/005655'
    - possession_date: 'TBA' -> 'Dec 2028'
```

The raw K-RERA registry can be cleaned the same way, matched on exact
registration number instead:

```bash
python scripts/dedupe_sheet.py --worksheet KRERA_Raw_Projects
```

---

## 🚀 Quickstart: Automated Setup with GitHub Actions (Recommended)

### Step 1: Clone or Push this Repo to GitHub
Create a GitHub repository (public or private) and push this folder to GitHub.

### Step 2: Get Your Free API Keys
1. **Google Gemini API Key**: Visit [Google AI Studio](https://aistudio.google.com/app/apikey) and click **Create API Key** (Free).
2. **Perplexity API Key** *(Optional)*: Get your API key from [Perplexity Settings](https://www.perplexity.ai/settings/api).
3. **Google Service Account**: Follow the 5-minute walkthrough in [`setup_google_sheets.md`](setup_google_sheets.md).

### Step 3: Add Secrets to GitHub
In your GitHub repo:
1. Go to **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** and add:
   - `GEMINI_API_KEY`: Your Gemini API key.
   - `PERPLEXITY_API_KEY`: *(Optional)* Your Perplexity API key.
   - `GCP_SERVICE_ACCOUNT_KEY`: Paste the full raw JSON content from your Google Service Account key file.
   - `GOOGLE_SHEET_NAME`: `Bangalore Real Estate Projects Tracker`

### Step 4: Run the Scraper!
- **Automatic daily run**: Runs every morning at **8:30 AM IST (03:00 UTC)** via [`.github/workflows/daily_real_estate_scraper.yml`](.github/workflows/daily_real_estate_scraper.yml).
- **Manual trigger**: Go to the **Actions** tab in GitHub, select **Daily Bangalore Real Estate Scraper**, and click **Run workflow**.

---

## 💻 Local Testing & Development

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

If testing with a local Google Service Account, save your key as `service_account.json` in the root folder.

### 3. Run Pipeline
```bash
python src/main.py
```
*Note: If no Google Sheet credentials are provided, the script runs in safe offline mode and exports all scraped records to `scraped_projects_latest.json`.*

---

## 🌐 Optional: Hosting on Render Free Web Service

If you prefer an HTTP webhook endpoint to trigger scrapes on Render:
1. Create a free account at [render.com](https://render.com).
2. Click **New +** → **Blueprint** and connect your GitHub repo (it uses [`render.yaml`](render.yaml)).
3. Under Environment Variables in Render, add your `GEMINI_API_KEY` and `GCP_SERVICE_ACCOUNT_KEY`.
4. Trigger on a daily schedule using [cron-job.org](https://cron-job.org/) (100% free):
   - **URL**: `https://<your-render-app>.onrender.com/scrape`
   - **Method**: `POST`
   - **Schedule**: Every day at your preferred time.
   - **Header**: `Authorization: Bearer <CRON_SECRET>`

---

## ⏰ Changing the Daily Run Time

To change when the daily scraper runs, edit the cron expression in [`.github/workflows/daily_real_estate_scraper.yml`](.github/workflows/daily_real_estate_scraper.yml):

```yaml
schedule:
  - cron: '30 2 * * *' # Runs at 08:00 AM IST (02:30 UTC)
```
*(Cron uses UTC time. IST is UTC + 5:30).*

---

## 🛠️ Project Structure

```
├── .github/workflows/
│   └── daily_real_estate_scraper.yml  # GitHub Actions cron workflow
├── src/
│   ├── config.py                      # Configurations & micro-markets
│   ├── models.py                      # Pydantic data schemas
│   ├── gsheet_manager.py              # Google Sheets client & deduplication
│   ├── geocoder.py                    # Cached Nominatim / Google geocoding
│   ├── scrapers/
│   │   ├── gemini_scraper.py          # Gemini 3.8 Flash search grounding
│   │   ├── perplexity_scraper.py      # Perplexity Sonar search
│   │   ├── krera_scraper.py           # Karnataka RERA validator
│   │   └── aggregator.py              # Multi-zone scan & merge
│   └── main.py                        # Pipeline entrypoint
├── scripts/
│   └── dedupe_sheet.py                # One-off duplicate-row cleanup
├── app.py                             # FastAPI webhook trigger for Render
├── render.yaml                        # Render blueprint deployment
├── setup_google_sheets.md             # Free Google Service Account guide
├── requirements.txt                   # Dependencies
└── .env.example                       # Environment template
```
