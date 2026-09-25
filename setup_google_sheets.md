# 📋 Step-by-Step Google Sheets Setup Guide (100% Free)

This guide shows you how to connect your Bangalore Real Estate Scraper to Google Sheets using a **Google Cloud Service Account** at zero cost.

---

## 1. Create a Free Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top left, then click **New Project**.
3. Name it `Bangalore-Real-Estate-Tracker` and click **Create**.

---

## 2. Enable Required APIs

1. In the search bar at the top, search for **Google Drive API** and click **Enable**.
2. Next, search for **Google Sheets API** and click **Enable**.

---

## 3. Create a Service Account (Free Robot Identity)

1. Open the left navigation menu (`☰`) → **IAM & Admin** → **Service Accounts**.
2. Click **+ CREATE SERVICE ACCOUNT** at the top.
3. Enter details:
   - **Service account name**: `gsheet-scraper`
   - **Service account ID**: `gsheet-scraper` (auto-filled)
4. Click **Create and Continue**.
5. (Optional) For Role, select **Editor** or **Basic > Editor**. Click **Continue** and then **Done**.
6. Find your new service account in the list and copy its email address (it will look like: `gsheet-scraper@bangalore-real-estate-tracker.iam.gserviceaccount.com`).

---

## 4. Generate the Service Account JSON Key

1. Click on the newly created service account email.
2. Go to the **Keys** tab at the top.
3. Click **Add Key** → **Create new key**.
4. Select **JSON** and click **Create**.
5. A JSON file will automatically download to your computer.

---

## 5. Share Your Google Sheet

1. Create a new Google Sheet at [sheets.new](https://sheets.new) or name your sheet:
   ```
   Bangalore Real Estate Projects Tracker
   ```
2. Click the green **Share** button in the top right.
3. Paste the **Service Account Email** you copied in Step 3.
4. Give it **Editor** permissions and uncheck "Notify people", then click **Share**.

---

## 6. Configure Credentials

### For Local Machine Testing:
- Rename the downloaded JSON file to `service_account.json` and place it in this project folder (`c:\Users\Karthik Viswanathan\OneDrive\Desktop\Karthi Anti Gravity\service_account.json`).

### For GitHub Actions (Daily Automated Runs):
1. Open the downloaded JSON file in a text editor (Notepad, VS Code).
2. Copy the entire contents of the file.
3. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**.
4. Click **New repository secret**:
   - **Name**: `GCP_SERVICE_ACCOUNT_KEY`
   - **Secret**: Paste the copied JSON text.
5. Click **Add secret**.
