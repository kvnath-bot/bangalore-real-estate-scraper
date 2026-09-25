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
│   ├── scrapers/
│   │   ├── gemini_scraper.py          # Gemini 3.8 Flash search grounding
│   │   ├── perplexity_scraper.py      # Perplexity Sonar search
│   │   ├── krera_scraper.py           # Karnataka RERA validator
│   │   └── aggregator.py              # Multi-zone scan & merge
│   └── main.py                        # Pipeline entrypoint
├── app.py                             # FastAPI webhook trigger for Render
├── render.yaml                        # Render blueprint deployment
├── setup_google_sheets.md             # Free Google Service Account guide
├── requirements.txt                   # Dependencies
└── .env.example                       # Environment template
```
