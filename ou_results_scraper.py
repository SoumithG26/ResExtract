import streamlit as st
import requests
import urllib3
from bs4 import BeautifulSoup
import pandas as pd
import io
import time

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
</style>
""", unsafe_allow_html=True)

# ── Session / request helpers ─────────────────────────────────────────────────
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
                record["Semester"]      = cells[0]
                record["Result (SGPA)"] = cells[1]
                record["Overall CGPA"]  = cells[2]

    if not record.get("Name", "").strip():
        return None, "Could not parse name — page may be empty or blocked"
    return record, None


def generate_htnos(prefix, start, end):
    return [f"{prefix}{str(i).zfill(3)}" for i in range(int(start), int(end) + 1)]


# ── UI ────────────────────────────────────────────────────────────────────────
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
    url = st.text_input("Results URL", value="https://www.osmania.ac.in/res07/20251290.jsp")

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
    delay = st.slider("Delay between requests (s)", 0.0, 3.0, 0.5, 0.1)
    run_btn = st.button("🚀 Fetch Results", use_container_width=True)


# ── Session state ─────────────────────────────────────────────────────────────
if "df_results" not in st.session_state:
    st.session_state.df_results = None
    st.session_state.logs       = []

# ── Run ───────────────────────────────────────────────────────────────────────
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

    records, logs = [], []
    total = len(htnos)

    for idx, htno in enumerate(htnos):
        stat.markdown(f"`[{idx+1}/{total}]` Fetching **{htno}**...")
        _, html, err = fetch_one(url, htno, session)

        if err:
            logs.append(f"❌ {htno} → {err}")
        elif html:
            record, perr = parse_result(htno, html, attrs)
            if record:
                records.append(record)
                logs.append(f"✅ {htno} → {record.get('Name','?')} | {record.get('Result (SGPA)','?')}")
            else:
                logs.append(f"⚠️  {htno} → {perr}")
        else:
            logs.append(f"❌ {htno} → Empty response")

        prog.progress((idx + 1) / total)
        logbox.code("\n".join(logs[-25:]), language=None)
        time.sleep(delay)

    stat.success(f"Done — **{len(records)}** valid records out of {total}.")
    st.session_state.df_results = pd.DataFrame(records) if records else None
    st.session_state.logs       = logs

# ── Display ───────────────────────────────────────────────────────────────────
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
    show_cols = st.multiselect("Columns to display", all_cols,
                               default=all_cols[:min(15, len(all_cols))])
    if show_cols:
        st.dataframe(df[show_cols], use_container_width=True, height=500)

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

elif not run_btn:
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
