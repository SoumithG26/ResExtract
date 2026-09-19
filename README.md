# 🎓 OU Results Scraper

A Streamlit web application to bulk-fetch and export Osmania University exam results by hall ticket number range.

#### Live URL -> https://ressniper.streamlit.app/
---

## 📸 Features

- 🔍 **Bulk scraping** — fetch results for an entire batch or branch in one go
- 🎯 **Attribute selection** — choose exactly which columns to extract (Credits, Grade Points, Grade Secured)
- 📊 **Live dashboard** — view results in an interactive table with summary metrics (Avg CGPA, pass count, best SGPA)
- 📥 **Export** — download results as `.xlsx` (Excel) or `.csv`
- 🔁 **Any exam cycle** — just paste the URL for that semester; the format is consistent across all OU results pages

---

## 🔗 Known Results URLs

| Exam Cycle | URL |
|---|---|
| July/August 2026 | https://www.osmania.ac.in/res07/20260655.jsp |
| Dec 2025 / Jan 2026 | https://www.osmania.ac.in/res07/20251290.jsp |
| July / August 2025 | https://www.osmania.ac.in/res07/2025becbcs.jsp |
| Feb / March 2025 | https://www.osmania.ac.in/res07/20250403.jsp |

> The URL format changes each semester. Check the OU results portal for the latest link and paste it into the app.

---

## 🗂️ Project Structure

```
ou-results-scraper/
├── ou_results_scraper.py   # Main Streamlit application
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

---

## ⚙️ Setup & Installation

### Prerequisites

- Python 3.9 or higher
- pip

### 1. Clone / download the project

```bash
git clone https://github.com/yourname/ou-results-scraper.git
cd ou-results-scraper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

```bash
streamlit run ou_results_scraper.py
```

The app will open at `http://localhost:8501` in your browser.

---

## 🚀 How to Use

### Step 1 — Enter the Results URL

Paste the semester's JSP endpoint into the **Results URL** field in the sidebar. Use one of the URLs from the table above, or the latest one from the OU portal.

### Step 2 — Select Attributes

Choose which columns to extract per subject:

- **Credits** — credit hours for the subject
- **Grade Points** — numeric grade points scored
- **Grade Secured** — letter grade (S, A, B, C, D, F)

### Step 3 — Set the Hall Ticket Range

**Option A — Prefix + Range** *(recommended for a whole batch)*

Hall ticket numbers are 12 digits. Split them into a 9-digit prefix and a 3-digit suffix:

```
245324733  +  001 → 060
└─ prefix ─┘  └─ range ─┘
```

The app auto-generates all hall tickets: `245324733001`, `245324733002`, ... `245324733060`.

**Option B — Manual List**

Paste specific hall ticket numbers (one per line or comma-separated):

```
245324733001
245324733005
245324733023
```

### Step 4 — Configure and Fetch

- Set the **delay** between requests (0.5s recommended to avoid getting blocked)
- Hit **🚀 Fetch Results**
- Watch the live log as results come in

### Step 5 — Export

Once the fetch is complete, use the **Download Excel** or **Download CSV** buttons to save the data.

---

## 🛠️ Technical Details

### Why `verify=False`?

Osmania University's web server uses a self-signed / improperly chained SSL certificate that fails Python's default certificate verification. The app disables SSL verification (`verify=False`) and suppresses the associated `urllib3` warning. This is safe in this context since you're deliberately targeting a known university domain.

### Session Handling

The OU results endpoint requires:

1. A **GET** request to the JSP page first — this sets the `JSESSIONID` cookie.
2. A **POST** request with the form payload `mbstatus=SEARCH`, `htno=<hall_ticket>`, `Submit.x`, `Submit.y`.

The app replicates exactly what a browser does, including seeding the `Hst*` analytics cookies that the server's JavaScript normally sets.

### POST Payload (from DevTools)

```
POST https://www.osmania.ac.in/res07/20251290.jsp

mbstatus = SEARCH
htno     = 245324733023
Submit.x = 36
Submit.y = 13
```

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI framework |
| `requests` | HTTP client |
| `beautifulsoup4` | HTML parsing |
| `lxml` | Fast HTML/XML parser backend |
| `pandas` | Data manipulation & export |
| `openpyxl` | Excel (.xlsx) file writing |
| `urllib3` | SSL warning suppression |

---

## ⚠️ Notes & Tips

- **Rate limiting** — keep the delay at ≥ 0.5s. Sending too many requests too fast may result in your IP being temporarily blocked by the server.
- **Hall ticket gaps** — not every number in a range will have a result. The app logs `⚠️ No record found` for missing/invalid hall tickets and skips them gracefully.
- **Branch ranges** — hall tickets are typically assigned in contiguous blocks per branch. Check a few known hall tickets for your branch to determine the correct prefix and numeric range.
- **CGPA column** — the CGPA column will show `-` for students whose CGPA has not been updated yet (common mid-degree). This is the raw value from the server.

---

## 📄 License

MIT — free to use, modify, and distribute.
