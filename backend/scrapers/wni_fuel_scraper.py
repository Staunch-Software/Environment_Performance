import logging
import re
import pandas as pd
import os
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright

# Configure logging to show only structured progress messages cleanly
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Suppress verbose third-party logging from playwright/urllib
logging.getLogger("playwright").setLevel(logging.WARNING)

from app.config import get_settings
from scrapers.sync_database import get_sync_session
from app.models.fuel_consumption import FuelConsumption

settings = get_settings()

# --- HELPER FUNCTIONS FOR CSV PROCESSING ---

def clean_header(text):
    """Cleans artifacts from CSV headers."""
    text = str(text).replace("_x000D_", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" '\"").strip()

def get_wni_headers(csv_path):
    """Extracts and merges double headers from the temporary WNI CSV file."""
    hdr = pd.read_csv(csv_path, nrows=2, header=None)
    groups = hdr.iloc[0].ffill().fillna("")
    items = hdr.iloc[1].fillna("")
    
    combined = []
    for g, i in zip(groups, items):
        g_c, i_c = clean_header(g), clean_header(i)
        if g_c and i_c and g_c.lower() != i_c.lower():
            combined.append(f"{g_c}_{i_c}")
        else:
            combined.append(i_c or g_c)
    return combined

def calculate_total_fuel(row):
    """Calculates Total Fuel = ME + AE + Boiler using mentor's exact logic."""
    def val(col_name):
        v = row.get(col_name)
        v_num = pd.to_numeric(v, errors='coerce')
        return float(v_num) if pd.notna(v_num) else 0.0

    # 1. Main Engine (ME) - Logic: VLSFO or ULSFO + all Distillates
    me_hfo = val("M/E Fuel Consumption_VLSFO (HFO/LFO) (mt)") or val("M/E Fuel Consumption_ULSFO (mt)")
    me_dist = sum([val(f"M/E Fuel Consumption_{c} (mt)") for c in [
        "MGO (>0.5%)", "MGO (≤0.5%)", "MGO (>0.1%)", "LSMGO", 
        "MDO (>0.5%)", "MDO (≤0.5%)", "MDO (>0.1%)", "LSMDO"
    ]])
    
    # 2. Aux Engine (AE) - Logic: VLSFO or ULSFO + all Distillates
    ae_hfo = val("A/E Fuel Consumption_VLSFO (HFO/LFO) (mt)") or val("A/E Fuel Consumption_ULSFO (mt)")
    ae_dist = sum([val(f"A/E Fuel Consumption_{c} (mt)") for c in [
        "MGO (>0.5%)", "MGO (≤0.5%)", "MGO (>0.1%)", "LSMGO", 
        "MDO (>0.5%)", "MDO (≤0.5%)", "MDO (>0.1%)", "LSMDO"
    ]])

    # 3. Boiler (BL) - Logic: VLSFO (HFO) or VLSFO (LFO) + LSMGO
    bl_hfo = val("Boiler Fuel Consumption_VLSFO (HFO) (mt)") or val("Boiler Fuel Consumption_VLSFO (LFO) (mt)")
    bl_dist = val("Boiler Fuel Consumption_LSMGO (mt)")

    total = me_hfo + me_dist + ae_hfo + ae_dist + bl_hfo + bl_dist
    return round(total, 2)

# --- DATE PICKER AUTOMATION MECHANICS ---

def navigate_to_month(page, target_year, target_month):
    """Navigates the Logbook+ month picker to the target year/month safely."""
    MONTH_MAP = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    max_clicks = 24
    clicks = 0

    while clicks < max_clicks:
        label = page.locator(r'text=/[A-Z][a-z]{2} \d{4}/').first.inner_text()
        parts = label.strip().split()
        current_month = MONTH_MAP.get(parts[0], 0)
        current_year = int(parts[1])

        # If we are already exactly matching the targeted month, stop and succeed
        if current_year == target_year and current_month == target_month:
            return True  

        current_total = current_year * 12 + current_month
        target_total  = target_year  * 12 + target_month

        if target_total < current_total:
            back_btn = page.locator("button:has-text('<'), button[aria-label*='prev'], .month-prev").first
            try:
                back_btn.wait_for(state="visible", timeout=2000)
                if not back_btn.is_enabled():
                    return False
                back_btn.click(timeout=2000)
            except Exception:
                return False
        else:
            next_btn = page.locator("button:has-text('>'), button[aria-label*='next'], .month-next").first
            try:
                next_btn.wait_for(state="visible", timeout=2000)
                if not next_btn.is_enabled():
                    return False  
                next_btn.click(timeout=2000)
            except Exception:
                return False

        page.wait_for_timeout(800)
        clicks += 1

    return True

# --- SCRAPER LOGIC ---

def select_vessel_by_name(page, vessel_name):
    """Selects vessel from the Logbook+ typeahead dropdown."""
    target_prefix = f"{vessel_name.strip().upper()} /"
    v_input = page.locator("input.simple-typeahead-input")
    v_input.fill("")
    v_input.type(vessel_name, delay=50)
    page.wait_for_timeout(1500) 
    
    options = page.locator(".simple-typeahead-list > *")
    for i in range(options.count()):
        if options.nth(i).inner_text().upper().startswith(target_prefix):
            options.nth(i).click()
            page.wait_for_timeout(2500) 
            return
    raise RuntimeError(f"Vessel '{vessel_name}' not found in dropdown.")

def run_wni_fuel_scraper():
    vessels_file = Path(settings.WNI_VESSELS_FILE)
    if not vessels_file.exists():
        logger.error(f"Vessels file not found at {vessels_file}")
        return
    
    with open(vessels_file, "r") as f:
        vessel_names = [l.strip() for l in f if l.strip()]

    # Sort to process vessels alphabetically
    vessel_names = sorted(vessel_names)

    # Define historical boundaries
    HISTORICAL_START_DATE = datetime(2025, 6, 1)
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Build target months chronologically from oldest history up to present month
    month_ranges = []
    cursor = HISTORICAL_START_DATE
    while cursor <= end_date:
        month_ranges.append(cursor)
        cursor += relativedelta(months=1)

    db = get_sync_session()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        
        try:
            # 1. Login Stage
            page.goto(settings.WNI_LOGIN_URL)
            page.locator("#login_buttom").click()
            page.get_by_role("textbox", name="Username").fill(settings.WNI_USERNAME)
            page.get_by_role("button", name="Continue").click()
            page.get_by_role("textbox", name="Password").fill(settings.WNI_PASSWORD)
            page.get_by_role("button", name="Continue").click()
            page.wait_for_load_state("networkidle")

            # 2. Open Logbook+ Exactly Once[cite: 4]
            page.wait_for_selector("a", timeout=20000)
            page.evaluate("""
                [...document.querySelectorAll('a')]
                  .find(a => a.innerText.includes('Logbook+'))
                  .click()
            """)
            page.wait_for_load_state("networkidle")
            
            # Dismiss overlay backdrop blockages permanently[cite: 2]
            try:
                backdrop = page.locator("div.w-screen.h-screen.fixed.z-40.inset-0").first
                if backdrop.is_visible():
                    backdrop.click(force=True)
            except: pass

            for v_name in vessel_names:
                logger.info(f"Processing vessel: {v_name}")
                
                for current_month_start in month_ranges:
                    try:
                        # Select the target vessel[cite: 2]
                        select_vessel_by_name(page, v_name)

                        # Navigate to the correct target month grid viewport context
                        if not navigate_to_month(page, current_month_start.year, current_month_start.month):
                            continue
                        page.wait_for_load_state("networkidle")

                        with tempfile.TemporaryDirectory() as tmp_dir:
                            temp_file_path = os.path.join(tmp_dir, "historical_data.csv")
                            
                            with page.expect_download() as download_info:
                                page.get_by_role("button", name="Download Table as CSV").click()
                            
                            download = download_info.value
                            download.save_as(temp_file_path)
                            
                            headers = get_wni_headers(temp_file_path)
                            df = pd.read_csv(temp_file_path, skiprows=2, names=headers)
                            
                            if df.empty:
                                continue

                            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                            df = df.dropna(subset=['Date'])
                            
                            if df.empty:
                                continue

                            # Neat single-line log output format
                            min_date = df['Date'].min().strftime('%Y-%m-%d')
                            max_date = df['Date'].max().strftime('%Y-%m-%d')
                            logger.info(f"Vessel: {v_name} | Extracted from {min_date} to {max_date}")

                            # Deduplicate and aggregate fuel values by date locally[cite: 2]
                            daily_aggregated_fuel = {}
                            for _, row in df.iterrows():
                                report_date = row['Date'].date()
                                total_fuel = calculate_total_fuel(row)
                                daily_aggregated_fuel[report_date] = round(daily_aggregated_fuel.get(report_date, 0.0) + total_fuel, 2)

                            # Sort the collection chronologically so they hit the DB sequentially
                            sorted_dates = sorted(daily_aggregated_fuel.keys())

                            # Upsert the combined daily totals sequentially into the database
                            for report_date in sorted_dates:
                                total_fuel = daily_aggregated_fuel[report_date]
                                
                                existing = db.query(FuelConsumption).filter_by(
                                    vessel_name=v_name, report_date=report_date
                                ).first()

                                if existing:
                                    existing.total_fuel_consumption = total_fuel
                                else:
                                    # Generates a valid deterministic Version-5 UUID based on string combination
                                    unique_string_seed = f"{v_name.replace(' ', '_')}_{report_date}"
                                    deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, unique_string_seed)
                                    
                                    db.add(FuelConsumption(
                                        id=deterministic_uuid,
                                        vessel_name=v_name,
                                        report_date=report_date,
                                        total_fuel_consumption=total_fuel
                                    ))
                                    
                            db.commit()

                    except Exception as monthly_exception:
                        db.rollback()
                        logger.error(f"Error handling month {current_month_start.strftime('%b %Y')} for vessel {v_name}: {monthly_exception}")

        finally:
            db.close()
            browser.close()

if __name__ == "__main__":
    run_wni_fuel_scraper()