import streamlit as st
import requests
import urllib3
from bs4 import BeautifulSoup
import pandas as pd
import io
import time
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime

# Suppress SSL warnings (OU site has a broken/self-signed cert)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OU Results Scraper",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

[data-testid="stAppViewContainer"] { background: #0d0f1a !important; color: #e8eaf0 !important; }
[data-testid="stSidebar"]          { background: #13162a !important; border-right: 1px solid #2a2e4a !important; }
h1,h2,h3 { font-family: 'Space Mono', monospace !important; }
p,label,div { font-family: 'DM Sans', sans-serif !important; }

.stTextInput input, .stNumberInput input, .stTextArea textarea {
    background: #1a1e35 !important; border: 1px solid #2a2e4a !important;
    border-radius: 8px !important; color: #e8eaf0 !important;
}
.stButton > button {
    background: linear-gradient(135deg,#4f46e5,#7c3aed) !important;
    color: white !important; border: none !important;
    border-radius: 8px !important; font-family: 'Space Mono',monospace !important;
    width: 100%; transition: all .2s !important;
}
.stButton > button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(79,70,229,.4) !important; }
.metric-card { background:#1a1e35; border:1px solid #2a2e4a; border-radius:12px; padding:1.2rem 1.5rem; text-align:center; }
.metric-card .val { font-family:'Space Mono',monospace; font-size:2rem; font-weight:700; color:#818cf8; }
.metric-card .lbl { font-size:.8rem; color:#6b7280; margin-top:4px; text-transform:uppercase; letter-spacing:.08em; }
.header-banner {
    background: linear-gradient(135deg,#1a1e35 0%,#13162a 100%);
    border: 1px solid #2a2e4a; border-left: 4px solid #4f46e5;
    border-radius: 12px; padding: 1.5rem 2rem; margin-bottom: 2rem;
}
.failed-card {
    background: #1a1e35; border: 1px solid #3b1a1a; border-left: 3px solid #ef4444;
    border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.5rem;
    display: flex; justify-content: space-between; align-items: center;
}
.failed-htno { font-family: 'Space Mono', monospace; color: #f87171; font-weight: 600; }
.failed-err  { color: #6b7280; font-size: 0.85rem; }
.history-row {
    background: #1a1e35; border: 1px solid #2a2e4a; border-radius: 10px;
    padding: 1rem 1.2rem; margin-bottom: 0.6rem;
}
.history-row .ts   { font-family: 'Space Mono', monospace; color: #818cf8; font-size: 0.85rem; }
.history-row .desc { color: #e8eaf0; margin-top: 0.3rem; }
.history-row .stat { color: #6b7280; font-size: 0.82rem; margin-top: 0.2rem; }
.cache-badge {
    display: inline-block; background: #1e293b; border: 1px solid #334155;
    color: #94a3b8; font-size: 0.72rem; padding: 2px 8px; border-radius: 999px;
    margin-left: 6px; font-family: 'Space Mono', monospace;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  LOCAL CACHE & HISTORY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

CACHE_DIR_NAME = ".resextract"

def get_cache_dir() -> Path:
    """Return (and create) ~/.resextract/cache/"""
    d = Path.home() / CACHE_DIR_NAME / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d

def cache_key(htno: str, url: str) -> str:
    """Unique filename for an HTNO+URL pair."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{htno}_{url_hash}"

def save_to_cache(htno: str, url: str, record: dict):
    """Persist a parsed result dict as JSON."""
    fp = get_cache_dir() / f"{cache_key(htno, url)}.json"
    fp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

def load_from_cache(htno: str, url: str):
    """Return the cached dict, or None if not cached."""
    fp = get_cache_dir() / f"{cache_key(htno, url)}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


# ── History ───────────────────────────────────────────────────────────────────

def get_history_path() -> Path:
    d = Path.home() / CACHE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.json"

def load_history() -> list:
    hp = get_history_path()
    if hp.exists():
        try:
            return json.loads(hp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []

def save_history_entry(entry: dict):
    history = load_history()
    history.insert(0, entry)           # newest first
    get_history_path().write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def delete_history_entry(entry_id: str):
    history = load_history()
    history = [h for h in history if h.get("id") != entry_id]
    get_history_path().write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def load_results_from_history(entry: dict) -> pd.DataFrame | None:
    """Reconstruct a DataFrame from cached JSONs for a history entry."""
    url   = entry.get("url", "")
    htnos = entry.get("success_htnos", [])
    records = []
    for htno in htnos:
        rec = load_from_cache(htno, url)
        if rec:
            records.append(rec)
    return pd.DataFrame(records) if records else None


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION / REQUEST HELPERS  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

def make_session(url: str):
    """
    Open a requests.Session with SSL verification OFF, do a GET on the
    results page so the server sets JSESSIONID, then return the session.
    """
    s = requests.Session()
    s.verify = False                          # ← OU has a broken SSL cert
    s.headers.update({
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    })
    try:
        resp = s.get(url, timeout=20)
        # Seed tracking cookies that the server may expect (set by JS normally)
        ts = str(int(time.time() * 1000))
        s.cookies.set("HstCfa2059181", ts,       domain="www.osmania.ac.in")
        s.cookies.set("HstCnv2059181", "1",       domain="www.osmania.ac.in")
        s.cookies.set("HstCns2059181", "1",       domain="www.osmania.ac.in")
        s.cookies.set("HstCla2059181", ts,        domain="www.osmania.ac.in")
        s.cookies.set("HstPn2059181",  "2",       domain="www.osmania.ac.in")
        s.cookies.set("HstPt2059181",  "2",       domain="www.osmania.ac.in")
        s.cookies.set("HstCmu2059181", ts,        domain="www.osmania.ac.in")
        s.cookies.set("c_ref_2059181", "https%3A%2F%2Fwww.google.com%2F", domain="www.osmania.ac.in")
        return s, None
    except Exception as e:
        return None, str(e)


def fetch_one(url: str, htno: str, session: requests.Session):
    origin = "/".join(url.split("/")[:3])   # https://www.osmania.ac.in
    post_headers = {
        "Content-Type":  "application/x-www-form-urlencoded",
        "Referer":        url,
        "Origin":         origin,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }
    payload = {
        "mbstatus": "SEARCH",
        "htno":     htno,
        "Submit.x": "36",
        "Submit.y": "13",
    }
    try:
        resp = session.post(url, data=payload, headers=post_headers,
                            timeout=20, verify=False, allow_redirects=True)
        if resp.status_code == 200:
            return htno, resp.text, None
        return htno, None, f"HTTP {resp.status_code}"
    except requests.exceptions.SSLError       as e: return htno, None, f"SSL Error: {e}"
    except requests.exceptions.ConnectionError as e: return htno, None, f"Connection Error: {e}"
    except requests.exceptions.Timeout:              return htno, None, "Timeout"
    except Exception                          as e:  return htno, None, str(e)


def parse_result(htno: str, html: str, selected_attrs: list):
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text()
    if "No record" in body or "Invalid" in body or "Enter Hall Ticket" in body[:500]:
        return None, "No record found / invalid hall ticket"

    record = {"Hall Ticket No.": htno}

    def find_section_table(keyword):
        for t in soup.find_all("table"):
            if keyword in t.get_text():
                return t
        return None

    # ── Personal Details ──────────────────────────────────────────────────────
    pt = find_section_table("Personal Details")
    if pt:
        for row in pt.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) == 4:
                for k, v in [(cells[0], cells[1]), (cells[2], cells[3])]:
                    if k and k not in ("Personal Details", "Marks Details", "Result"):
                        record[k] = v
            elif len(cells) == 2:
                k, v = cells
                if k and k not in ("Personal Details", "Marks Details", "Result"):
                    record[k] = v

    # ── Marks Details ─────────────────────────────────────────────────────────
    mt = find_section_table("Marks Details")
    if mt:
        rows = mt.find_all("tr")
        header_passed = False
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if "Code" in cells and "Subject" in cells:
                header_passed = True
                continue
            if not header_passed or len(cells) < 3:
                continue
            code, subj = cells[0], cells[1]
            if not code or not code[:1].isdigit():
                continue
            credits       = cells[2] if len(cells) > 2 else ""
            grade_points  = cells[3] if len(cells) > 3 else ""
            grade_secured = cells[4] if len(cells) > 4 else ""
            key = f"{code}|{subj[:18].strip()}"
            if "Credits"       in selected_attrs: record[f"{key}|Credits"] = credits
            if "Grade Points"  in selected_attrs: record[f"{key}|GP"]      = grade_points
            if "Grade Secured" in selected_attrs: record[f"{key}|Grade"]   = grade_secured

    # ── Result / SGPA / CGPA ─────────────────────────────────────────────────
    for t in soup.find_all("table"):
        hdr = t.find(lambda tag: tag.name in ["td","th"] and tag.get_text(strip=True) == "Result")
        if not hdr:
            continue
        for row in t.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) >= 3 and cells[0].isdigit():
                record["Result (SGPA)"] = cells[1]
                record["Semester"]      = cells[0]
                record["Overall CGPA"]  = cells[2]

    if not record.get("Name", "").strip():
        return None, "Could not parse name — page may be empty or blocked"
    return record, None


def generate_htnos(prefix, start, end):
    return [f"{prefix}{str(i).zfill(3)}" for i in range(int(start), int(end) + 1)]


# ══════════════════════════════════════════════════════════════════════════════
#  RETRY HELPER — fetch a list of HTNOs and merge into session state
# ══════════════════════════════════════════════════════════════════════════════

def retry_fetch(htnos_to_retry: list[str], url: str, attrs: list, delay: float, use_cache: bool):
    """
    Re-fetch a list of HTNOs.  Updates st.session_state in place:
      - df_results:    adds newly-successful rows
      - failed_htnos:  removes successes, keeps remaining failures
      - logs:          appends new log lines
    Returns (n_success, n_still_failed).
    """
    with st.spinner("🔗 Re-establishing session with OU server..."):
        session, err = make_session(url)
    if err:
        st.error(f"❌ Could not connect: {err}")
        return 0, len(htnos_to_retry)

    prog = st.progress(0)
    stat = st.empty()
    new_records   = []
    still_failed  = []
    new_logs      = []
    total = len(htnos_to_retry)

    for idx, htno in enumerate(htnos_to_retry):
        stat.markdown(f"`[{idx+1}/{total}]` Retrying **{htno}**...")

        # Check cache first if enabled
        if use_cache:
            cached = load_from_cache(htno, url)
            if cached:
                new_records.append(cached)
                new_logs.append(f"✅ {htno} → (cached) {cached.get('Name','?')}")
                prog.progress((idx + 1) / total)
                continue

        _, html, ferr = fetch_one(url, htno, session)
        if ferr:
            still_failed.append((htno, ferr))
            new_logs.append(f"❌ {htno} → {ferr}")
        elif html:
            record, perr = parse_result(htno, html, attrs)
            if record:
                new_records.append(record)
                save_to_cache(htno, url, record)
                new_logs.append(f"✅ {htno} → {record.get('Name','?')} | {record.get('Result (SGPA)','?')}")
            else:
                still_failed.append((htno, perr or "Parse error"))
                new_logs.append(f"⚠️  {htno} → {perr}")
        else:
            still_failed.append((htno, "Empty response"))
            new_logs.append(f"❌ {htno} → Empty response")

        prog.progress((idx + 1) / total)
        time.sleep(delay)

    stat.empty()
    prog.empty()

    # Merge into session state
    if new_records:
        new_df = pd.DataFrame(new_records)
        if st.session_state.df_results is not None:
            st.session_state.df_results = pd.concat(
                [st.session_state.df_results, new_df], ignore_index=True
            ).drop_duplicates(subset=["Hall Ticket No."], keep="last")
        else:
            st.session_state.df_results = new_df

    st.session_state.failed_htnos = still_failed
    st.session_state.logs.extend(new_logs)

    return len(new_records), len(still_failed)


# ══════════════════════════════════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="header-banner">
  <h1 style="margin:0;font-size:1.8rem;">🎓 OU Results Scraper</h1>
  <p style="margin:.4rem 0 0;color:#9ca3af;font-size:.9rem;">
    Osmania University · Bulk results extractor · Dec-2025 / Jan-2026
  </p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    url = st.text_input("Results URL", value="https://www.osmania.ac.in/res07/20260655.jsp")

    st.markdown("---")
    st.markdown("#### 📋 Attributes to Extract")
    attrs = st.multiselect("Select columns",
                           ["Credits", "Grade Points", "Grade Secured"],
                           default=["Credits", "Grade Points", "Grade Secured"])

    st.markdown("---")
    st.markdown("#### 🎯 Hall Ticket Range")
    mode = st.radio("Input mode", ["Prefix + Range", "Manual list"], horizontal=True)

    if mode == "Prefix + Range":
        st.caption("9-digit prefix + numeric suffix, e.g. `245324733` + 001–060")
        prefix  = st.text_input("9-digit Prefix", value="245324733")
        c1, c2  = st.columns(2)
        start_n = c1.number_input("Start", 1, 999, 1)
        end_n   = c2.number_input("End",   1, 999, 60)
    else:
        manual_input = st.text_area("Hall tickets (one per line or comma-separated)",
                                    placeholder="245324733001\n245324733002")

    st.markdown("---")
    st.markdown("#### 💾 Cache Settings")
    use_cache = st.toggle("Use cached results", value=True,
                          help="Skip network requests for HTNOs already saved locally.")
    delay = st.slider("Delay between requests (s)", 0.0, 3.0, 0.10, 0.1)
    run_btn = st.button("🚀 Fetch Results", use_container_width=True)


# ── Session state ─────────────────────────────────────────────────────────────
if "df_results" not in st.session_state:
    st.session_state.df_results   = None
    st.session_state.logs         = []
    st.session_state.failed_htnos = []   # list of (htno, error_msg)
    st.session_state.last_url     = ""
    st.session_state.last_attrs   = []


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN FETCH
# ══════════════════════════════════════════════════════════════════════════════
if run_btn:
    if not url.strip():
        st.error("Please enter a valid URL.")
        st.stop()

    if mode == "Prefix + Range":
        if len(prefix.strip()) != 9:
            st.error("Prefix must be exactly 9 digits.")
            st.stop()
        htnos = generate_htnos(prefix.strip(), start_n, end_n)
    else:
        raw   = manual_input.replace(",", "\n").split("\n")
        htnos = [h.strip() for h in raw if h.strip()]

    if not htnos:
        st.error("No hall ticket numbers to process.")
        st.stop()

    # Establish session
    with st.spinner("🔗 Initialising session with OU server..."):
        session, err = make_session(url)

    if err:
        st.error(f"❌ Could not connect to OU server: {err}")
        st.info("Make sure you're online and the URL is reachable.")
        st.stop()

    st.success("✅ Session established — fetching results...")

    prog   = st.progress(0)
    stat   = st.empty()
    logbox = st.empty()

    records, logs, failed = [], [], []
    success_htnos = []
    total = len(htnos)

    for idx, htno in enumerate(htnos):
        stat.markdown(f"`[{idx+1}/{total}]` Fetching **{htno}**...")

        # ── Check cache first ─────────────────────────────────────────────
        if use_cache:
            cached = load_from_cache(htno, url)
            if cached:
                records.append(cached)
                success_htnos.append(htno)
                logs.append(f"✅ {htno} → (cached) {cached.get('Name','?')}")
                prog.progress((idx + 1) / total)
                logbox.code("\n".join(logs[-25:]), language=None)
                continue

        # ── Network fetch ─────────────────────────────────────────────────
        _, html, ferr = fetch_one(url, htno, session)

        if ferr:
            failed.append((htno, ferr))
            logs.append(f"❌ {htno} → {ferr}")
        elif html:
            record, perr = parse_result(htno, html, attrs)
            if record:
                records.append(record)
                success_htnos.append(htno)
                save_to_cache(htno, url, record)
                logs.append(f"✅ {htno} → {record.get('Name','?')} | {record.get('Result (SGPA)','?')}")
            else:
                failed.append((htno, perr or "Parse error"))
                logs.append(f"⚠️  {htno} → {perr}")
        else:
            failed.append((htno, "Empty response"))
            logs.append(f"❌ {htno} → Empty response")

        prog.progress((idx + 1) / total)
        logbox.code("\n".join(logs[-25:]), language=None)
        time.sleep(delay)

    stat.success(f"Done — **{len(records)}** valid records out of {total}.")
    st.session_state.df_results   = pd.DataFrame(records) if records else None
    st.session_state.logs         = logs
    st.session_state.failed_htnos = failed
    st.session_state.last_url     = url
    st.session_state.last_attrs   = attrs

    # ── Save history entry ────────────────────────────────────────────────
    entry_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{hashlib.md5(url.encode()).hexdigest()[:6]}"
    history_entry = {
        "id":             entry_id,
        "timestamp":      datetime.now().isoformat(),
        "url":            url,
        "prefix":         prefix.strip() if mode == "Prefix + Range" else "manual",
        "range":          f"{start_n}–{end_n}" if mode == "Prefix + Range" else f"{len(htnos)} HTNOs",
        "total":          total,
        "success":        len(records),
        "failed":         len(failed),
        "success_htnos":  success_htnos,
        "failed_htnos":   [h for h, _ in failed],
        "attrs":          attrs,
    }
    save_history_entry(history_entry)


# ══════════════════════════════════════════════════════════════════════════════
#  DISPLAY RESULTS
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.df_results is not None:
    df = st.session_state.df_results
    st.markdown("---")

    def mcard(val, lbl):
        return f'<div class="metric-card"><div class="val">{val}</div><div class="lbl">{lbl}</div></div>'

    m1, m2, m3, m4 = st.columns(4)
    cgpa_cols = [c for c in df.columns if "CGPA" in c]
    sgpa_cols = [c for c in df.columns if "Result" in c or "SGPA" in c]

    avg_cgpa  = "N/A"
    if cgpa_cols:
        nums = pd.to_numeric(df[cgpa_cols[0]], errors="coerce").dropna()
        if len(nums): avg_cgpa = f"{nums.mean():.2f}"

    passed    = "N/A"
    best_sgpa = "N/A"
    if sgpa_cols:
        passed = df[sgpa_cols[0]].str.contains("PASS", case=False, na=False).sum()
        nums   = pd.to_numeric(df[sgpa_cols[0]].str.extract(r'([\d.]+)')[0], errors="coerce").dropna()
        if len(nums): best_sgpa = f"{nums.max():.2f}"

    m1.markdown(mcard(len(df),    "Records"),   unsafe_allow_html=True)
    m2.markdown(mcard(avg_cgpa,   "Avg CGPA"),  unsafe_allow_html=True)
    m3.markdown(mcard(passed,     "Passed"),    unsafe_allow_html=True)
    m4.markdown(mcard(best_sgpa,  "Best SGPA"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    all_cols  = list(df.columns)
    
    if "Result (SGPA)" in all_cols:
        all_cols.remove("Result (SGPA)")
        fn_col = next((c for c in all_cols if "father" in c.lower()), None)
        if fn_col:
            all_cols.insert(all_cols.index(fn_col), "Result (SGPA)")
        elif "Name" in all_cols:
            all_cols.insert(all_cols.index("Name") + 1, "Result (SGPA)")
        else:
            all_cols.insert(1, "Result (SGPA)")
        df = df[all_cols]
        
    exclude_exact = {"Course", "Semester", "Sub Code", "Credits", "Subject", "Grade", "Medium"}
    def is_default(c):
        if "|" in c or c in exclude_exact: return False
        if c.isdigit(): return False
        if len(c) <= 5 and any(ch.isdigit() for ch in c): return False
        return True

    default_cols = [c for c in all_cols if is_default(c)]
    show_cols = st.multiselect("Columns to display", all_cols,
                               default=default_cols)
    if show_cols:
        st.dataframe(df[show_cols], use_container_width=True, height=500)

    # ── Export ────────────────────────────────────────────────────────────
    st.markdown("### 📥 Export")
    e1, e2 = st.columns(2)
    with e1:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Results")
        buf.seek(0)
        st.download_button("⬇️ Download Excel (.xlsx)", buf, "ou_results.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    with e2:
        st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode(),
                           "ou_results.csv", "text/csv", use_container_width=True)

    with st.expander("🪵 Full Fetch Log"):
        st.code("\n".join(st.session_state.logs), language=None)


# ══════════════════════════════════════════════════════════════════════════════
#  FAILED FETCHES — RETRY UI
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.failed_htnos:
    st.markdown("---")
    n_failed = len(st.session_state.failed_htnos)
    st.markdown(f"### ❌ Failed Fetches ({n_failed})")

    retry_url   = st.session_state.get("last_url", url)
    retry_attrs = st.session_state.get("last_attrs", attrs)

    # Bulk retry button
    if st.button("🔄 Retry All Failed", key="retry_all", use_container_width=True):
        all_failed_htnos = [h for h, _ in st.session_state.failed_htnos]
        n_ok, n_fail = retry_fetch(all_failed_htnos, retry_url, retry_attrs, delay, use_cache)
        if n_ok:
            st.success(f"✅ Recovered {n_ok} result(s)!")
        if n_fail:
            st.warning(f"⚠️ {n_fail} still failed.")
        st.rerun()

    # Individual failed entries
    for i, (htno, err_msg) in enumerate(st.session_state.failed_htnos):
        col_info, col_btn = st.columns([5, 1])
        with col_info:
            st.markdown(
                f'<div class="failed-card">'
                f'<span class="failed-htno">{htno}</span>'
                f'<span class="failed-err">{err_msg}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        with col_btn:
            if st.button("🔄", key=f"retry_{htno}_{i}", help=f"Retry {htno}"):
                n_ok, n_fail = retry_fetch([htno], retry_url, retry_attrs, delay, use_cache)
                if n_ok:
                    st.success(f"✅ {htno} recovered!")
                else:
                    st.error(f"❌ {htno} still failed.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  FETCH HISTORY
# ══════════════════════════════════════════════════════════════════════════════
history = load_history()
if history:
    st.markdown("---")
    with st.expander(f"📜 Fetch History ({len(history)} sessions)", expanded=False):
        for entry in history:
            ts_raw   = entry.get("timestamp", "")
            try:
                ts_fmt = datetime.fromisoformat(ts_raw).strftime("%d %b %Y  %H:%M")
            except Exception:
                ts_fmt = ts_raw

            eid      = entry.get("id", ts_raw)
            pfx      = entry.get("prefix", "?")
            rng      = entry.get("range", "?")
            n_total  = entry.get("total", 0)
            n_ok     = entry.get("success", 0)
            n_fail   = entry.get("failed", 0)
            h_url    = entry.get("url", "")

            st.markdown(
                f'<div class="history-row">'
                f'  <div class="ts">🕒 {ts_fmt}</div>'
                f'  <div class="desc">Prefix <code>{pfx}</code> · Range <code>{rng}</code></div>'
                f'  <div class="stat">✅ {n_ok} succeeded · ❌ {n_fail} failed · 📊 {n_total} total</div>'
                f'  <div class="stat" style="word-break:break-all;">🔗 {h_url}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

            hc1, hc2 = st.columns(2)
            with hc1:
                if st.button("📂 Load Results", key=f"load_{eid}", use_container_width=True):
                    loaded_df = load_results_from_history(entry)
                    if loaded_df is not None and not loaded_df.empty:
                        st.session_state.df_results = loaded_df
                        st.session_state.logs = [f"Loaded {len(loaded_df)} records from history ({ts_fmt})"]
                        st.session_state.failed_htnos = [
                            (h, "Previously failed")
                            for h in entry.get("failed_htnos", [])
                        ]
                        st.session_state.last_url   = h_url
                        st.session_state.last_attrs = entry.get("attrs", [])
                        st.success(f"Loaded {len(loaded_df)} records!")
                        st.rerun()
                    else:
                        st.warning("No cached data found for this session. The cache may have been cleared.")
            with hc2:
                if st.button("🗑️ Delete", key=f"del_{eid}", use_container_width=True):
                    delete_history_entry(eid)
                    st.success("History entry removed.")
                    st.rerun()

            st.markdown("")  # spacer


# ── Empty state ───────────────────────────────────────────────────────────────
elif st.session_state.df_results is None and not run_btn:
    st.markdown("""
    <div style="text-align:center;padding:4rem 2rem;color:#4b5563;">
        <div style="font-size:3rem;">📊</div>
        <p style="font-family:'Space Mono',monospace;margin-top:1rem;">
            Configure the sidebar and hit <strong style="color:#818cf8;">Fetch Results</strong>
        </p>
        <p style="font-size:.85rem;">
            Hall ticket format: <code style="background:#1a1e35;padding:2px 6px;border-radius:4px;">245324733001</code>
        </p>
    </div>
    """, unsafe_allow_html=True)
