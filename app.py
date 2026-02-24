import streamlit as st
import requests
import pandas as pd
from bs4 import BeautifulSoup
import io
import time
import urllib3

# Suppress the insecure request warnings since we are bypassing SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="OU Results Extractor", layout="wide")

st.title("🎓 Osmania University Results Extractor")
st.markdown("Extract results for a batch/branch and download them directly as an Excel file.")

# Sidebar inputs
st.sidebar.header("Input Parameters")

# 1. URL Input
url = st.sidebar.text_input(
    "Results URL", 
    value="https://www.osmania.ac.in/res07/20251290.jsp",
    help="The exact URL where the results are hosted."
)

# 2. Hall Ticket Configuration (Branch and Range)
st.sidebar.subheader("Hall Ticket Details")
htno_prefix = st.sidebar.text_input(
    "HTNO Prefix (CollegeCode + Year + BranchCode)", 
    value="160121733",
    help="Example: 160121733 for CSE branch in a specific college."
)

col1, col2 = st.sidebar.columns(2)
start_range = col1.number_input("Start Roll No", min_value=1, value=1, step=1)
end_range = col2.number_input("End Roll No", min_value=1, value=60, step=1)

# Format for roll numbers (e.g., 3 digits: 001, 002)
roll_digits = st.sidebar.number_input("Roll Number Digits", min_value=1, value=3, step=1, help="If roll numbers are like 001, 002, use 3")

# 3. Attributes to Extract
st.sidebar.subheader("Extraction Settings")
available_attributes = [
    "Subject Code", 
    "Subject Name", 
    "Credits", 
    "Grade Secured", 
    "Grade Points"
]

selected_attributes = st.sidebar.multiselect(
    "Select Attributes to Extract", 
    options=available_attributes,
    default=["Subject Name", "Credits", "Grade Secured"]
)

def fetch_result(htno, url):
    """Diagnostic version to fetch and parse the result (SSL Bypass Added)"""
    try:
        session = requests.Session()
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.osmania.ac.in",
            "Referer": url,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # 1. Establish session - ADD verify=False
        session.get(url, headers=headers, timeout=15, verify=False)
        
        # 2. Send payload
        payload = {
            'mbstatus': 'SEARCH',
            'htno': htno,
            'Submit.x': '36',
            'Submit.y': '13'
        }
        
        # 3. POST request - ADD verify=False
        response = session.post(url, data=payload, headers=headers, timeout=15, verify=False)
        
        print(f"\n--- Testing HTNO: {htno} ---")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print("❌ Failed: Server returned an error code.")
            return None
            
        if "Enter Hall Ticket No" in response.text:
            print("❌ Failed: Server just reloaded the search form (Invalid HTNO).")
            return None
            
        try:
            tables = pd.read_html(io.StringIO(response.text))
            print(f"✅ Success: Fetched page and found {len(tables)} tables.")
            
            for i, df in enumerate(tables):
                temp_cols = [str(c).strip().title() for c in df.columns]
                print(f"   -> Table {i} Columns: {temp_cols}")
                
                if any("Subject" in col or "Sub" in col for col in temp_cols) or any("Grade" in col or "Result" in col for col in temp_cols):
                    df.columns = temp_cols
                    df['HTNO'] = htno
                    print("🎉 Found the correct marks table!")
                    return df
                    
            print("❌ Failed: Could not find a table with 'Subject' or 'Grade' columns.")
            return None
            
        except ValueError as e:
            print(f"❌ Failed: Pandas could not find any HTML tables on the page. Error: {e}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return None
    
if st.sidebar.button("Extract Results", type="primary"):
    if not selected_attributes:
        st.error("Please select at least one attribute to extract.")
    else:
        all_results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_students = (end_range - start_range) + 1
        
        for idx, roll_no in enumerate(range(start_range, end_range + 1)):
            # Format the roll number (e.g., 1 -> '001')
            formatted_roll = str(roll_no).zfill(roll_digits)
            current_htno = f"{htno_prefix}{formatted_roll}"
            
            status_text.text(f"Fetching results for HTNO: {current_htno}...")
            
            # Fetch data
            student_df = fetch_result(current_htno, url)
            
            if student_df is not None and not student_df.empty:
                all_results.append(student_df)
                
            # Update progress
            progress_bar.progress((idx + 1) / total_students)
            
            # Small delay to prevent overwhelming the university server
            time.sleep(0.5)
            
        status_text.text("Extraction Complete!")
        
        if all_results:
            # Combine all student DataFrames into one
            final_df = pd.concat(all_results, ignore_index=True)
            
            # Standardize column names to match requested attributes
            final_df.columns = [col.replace("\n", " ").strip() for col in final_df.columns]
            
            # Filter only the selected columns (+ HTNO)
            columns_to_keep = ['HTNO'] + [col for col in selected_attributes if col in final_df.columns]
            final_df = final_df[columns_to_keep]
            
            st.success(f"Successfully extracted results for {len(final_df['HTNO'].unique())} students!")
            
            # Display on website
            st.dataframe(final_df, use_container_width=True)
            
            # Create Excel File in Memory
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False, sheet_name='OU_Results')
            excel_data = output.getvalue()
            
            # Download Button
            st.download_button(
                label="📥 Download as Excel",
                data=excel_data,
                file_name=f"OU_Results_{htno_prefix}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("No results found. Please check if the URL, HTNO Prefix, or Range is correct.")