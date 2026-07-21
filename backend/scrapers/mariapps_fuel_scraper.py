import logging
import os
import sys
import time
import uuid
import pandas as pd
import numpy as np
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

# Ensure backend root is inside system paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import get_settings
from scrapers.sync_database import get_sync_session
from app.models.fuel_consumption import FuelConsumption

# --- PROFESSIONAL LOGGING LAYOUT ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] --- %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("MariAppsScraper")
logging.getLogger("playwright").setLevel(logging.WARNING)

settings = get_settings()

# Pipeline Configurations
MARIAPPS_VESSELS = ["AMNS POLAR", "AMNS TUFMAX", "AMNSI STALLION", "AMNSI MAXIMUS"]
FROM_DATE = "01-Jun-2025"
TO_DATE = datetime.now().strftime("%d-%b-%Y")
TARGET_URL = "https://smartpal.ozellar.com/PerformancePALApp/Performance/LogApproval"
AUTH_FILE = os.path.join(CURRENT_DIR, "mariapps_auth_session.json")

# VISUAL DEBUGGING FLAG: Change to False if you want to visually see the browser open
HEADLESS_MODE = True

def run_background_sso_login():
    """Performs full corporate Microsoft SSO authentication gate with visual bypasses."""
    logger.info("Initializing secure Microsoft SSO gateway connection...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS_MODE)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        context.add_init_script("Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });")

        try:
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            
            # Target interactive buttons or wrappers rather than hidden layout text elements
            signin_selectors = [
                "button:has-text('SIGN IN')", 
                "a:has-text('SIGN IN')", 
                ".btn:has-text('SIGN IN')",
                "text='SIGN IN'"
            ]
            
            for sel in signin_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                        logger.info(f"Successfully triggered landing gate using selector: {sel}")
                        break
                except Exception:
                    continue
            
            time.sleep(2.0)
            page.wait_for_load_state("networkidle")

            # --- PRE-CHECK: Handle "Pick an account" or "Use another account" intermediate panels ---
            try:
                another_account_tile = page.locator("#otherTile, text='Use another account'").first
                if another_account_tile.count() > 0 and another_account_tile.is_visible():
                    logger.info("Intermediate 'Pick an account' screen detected. Clicking 'Use another account'...")
                    another_account_tile.click(force=True)
                    time.sleep(1.5)
            except Exception:
                pass

            # Form Processing - Email entry
            logger.info("Injecting target account entry credentials...")
            email_input = page.locator("input[name='loginfmt'], #i0116, input[type='email']").first
            email_input.wait_for(state="visible", timeout=30000)
            email_input.fill("pms@ozellar.com")
            
            next_btn = page.locator("#idSIButton9, input[type='submit']").first
            next_btn.click()
            time.sleep(2.5)
            page.wait_for_load_state("networkidle")

            # Form Processing - Password entry
            logger.info("Injecting access keys...")
            pass_input = page.locator("input[name='passwd'], #i0118, input[type='password']").first
            pass_input.wait_for(state="visible", timeout=20000)
            pass_input.fill("T%482550371780as")
            
            submit_btn = page.locator("#idSIButton9, input[type='submit']").first
            submit_btn.click()
            time.sleep(2.5)
            page.wait_for_load_state("networkidle")
            
            # Handle standard "Stay signed in?" prompt window
            try:
                stay_signed_in_btn = page.locator("#idSIButton9, input[value='Yes']").first
                if stay_signed_in_btn.count() > 0:
                    stay_signed_in_btn.click()
            except: 
                pass
            
            page.wait_for_load_state("networkidle", timeout=30000)
            context.storage_state(path=AUTH_FILE)
            logger.info("SSO Token generated successfully. Session token cached.")
        except Exception as auth_err:
            logger.error(f"SSO Gate Authorization crashed: {auth_err}")
            raise auth_err
        finally:
            browser.close()

def get_active_frame(page):
    """Pinpoints Kendo context frames within core DOM trees."""
    for frame in page.frames:
        try:
            if frame.get_by_text("From (UTC)").count() > 0:
                return frame
        except:
            continue
    return None

def select_date_from_calendar(target, input_id, day, month, year):
    """Sets Kendo target datetimes via safe widget hook evaluations."""
    try:
        target.evaluate(f"""() => {{
            const input = document.getElementById('{input_id}');
            if (typeof $ !== 'undefined') {{
                const w = $(input).data('kendoDateTimePicker');
                if (w) {{ w.open('date'); }}
            }}
        }}""")
        time.sleep(0.5)

        popup_index = target.evaluate("""() => {
            const popups = document.querySelectorAll('.k-calendar-container.k-popup');
            for (let i = 0; i < popups.length; i++) {
                if (popups[i].style.display !== 'none' && popups[i].offsetParent !== null) return i;
            }
            return -1;
        }""")

        sel = '.k-calendar-container.k-popup' if popup_index != -1 else '.k-popup, .k-animation-container'
        idx = max(0, popup_index)

        target.evaluate(f"document.querySelectorAll('{sel}')[{idx}].querySelector('.k-header .k-nav-fast, .k-calendar-header .k-title').click();")
        time.sleep(0.3)
        target.evaluate(f"document.querySelectorAll('{sel}')[{idx}].querySelector('.k-header .k-nav-fast, .k-calendar-header .k-title').click();")
        time.sleep(0.3)

        target.evaluate(f"""() => {{
            const popup = document.querySelectorAll('{sel}')[{idx}];
            for (const c of popup.querySelectorAll('td[role="gridcell"]')) {{
                if (c.innerText.trim() === '{year}') {{ c.click(); break; }}
            }}
        }}""")
        time.sleep(0.3)

        mp = str(month)[:3].lower()
        target.evaluate(f"""() => {{
            const popup = document.querySelectorAll('{sel}')[{idx}];
            for (const c of popup.querySelectorAll('td[role="gridcell"]')) {{
                if (c.innerText.trim().toLowerCase().startsWith('{mp}')) {{ c.click(); break; }}
            }}
        }}""")
        time.sleep(0.3)

        day_str = str(int(day))
        target.evaluate(f"""() => {{
            const popup = document.querySelectorAll('{sel}')[{idx}];
            for (const c of popup.querySelectorAll('td[role="gridcell"], a.k-link')) {{
                if (c.innerText.trim() === '{day_str}') {{ c.click(); break; }}
            }}
        }}""")
        time.sleep(0.3)

        time_str = "00:00" if "from" in input_id.lower() else "23:59"
        target.evaluate(f"""() => {{
            const input = document.getElementById('{input_id}');
            if (typeof $ !== 'undefined') {{
                const w = $(input).data('kendoDateTimePicker');
                if (w) {{
                    const v = w.value();
                    if (v) {{
                        const parts = '{time_str}'.split(':');
                        v.setHours(parseInt(parts[0]), parseInt(parts[1]), 0, 0);
                        w.value(v);
                        w.trigger('change');
                    }}
                }}
            }}
        }}""")
        time.sleep(0.2)
    except Exception as e:
        logger.debug(f"Calendar layout handling pass execution complete for #{input_id}: {e}")

def download_grid_data(page, target):
    """Triggers spreadsheet exports and wraps raw dataframe matrices."""
    try:
        try:
            target.locator("#loading-container").wait_for(state="hidden", timeout=10000)
        except:
            pass

        export_btn = target.locator("button.btn-icon-export").first
        export_btn.wait_for(state="visible", timeout=10000)
        
        with page.expect_download(timeout=45000) as download_info:
            export_btn.click(force=True)

        path = download_info.value.path()
        df = pd.read_excel(path, header=None, dtype=str, keep_default_na=False, engine='openpyxl')

        if len(df) < 2:
            return []

        row0 = df.iloc[0].replace("", np.nan).ffill().fillna("")
        row1 = df.iloc[1].fillna("")
        headers = [f"{c0} - {c1}" if c0 and c1 and c0 != c1 else (c1 if c1 else c0) for c0, c1 in zip(row0, row1)]

        df.columns = headers
        df = df.iloc[2:].dropna(how='all').reset_index(drop=True)
        return json.loads(df.to_json(orient='records'))
    except Exception as e:
        logger.error(f"Excel parsing architecture crash: {e}")
        return []

def calculate_mariapps_total_fuel(row):
    """Extracts and evaluates matching numerical fuel indexes."""
    total = 0.0
    fuel_columns = [c for c in row.keys() if "consumption" in c.lower() or "foc" in c.lower() or "total_cons" in c.lower()]
    for col in fuel_columns:
        val = pd.to_numeric(row[col], errors='coerce')
        if pd.notna(val) and val > 0:
            total += float(val)
    return round(total, 2)

def run_mariapps_fuel_scraper():
    logger.info("========================================================================")
    logger.info("   MARIAPPS HISTORICAL FUEL INGESTION RUNNER STARTED                    ")
    logger.info("========================================================================")
    
    run_background_sso_login()
    db = get_sync_session()
    
    metrics_summary = {}
    
    with sync_playwright() as p:
        logger.info("Mounting Playwright browser execution profile contexts...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=AUTH_FILE)
        page = context.new_page()
        
        try:
            page.goto(TARGET_URL, wait_until="load", timeout=60000)
            page.wait_for_selector("input[aria-owns='vesselSearchBox_listbox']", timeout=30000)

            for idx, v_name in enumerate(MARIAPPS_VESSELS, start=1):
                logger.info(f"[{idx}/{len(MARIAPPS_VESSELS)}] Launching query process for vessel target: {v_name}")
                
                vessel_input = page.locator("input[aria-owns='vesselSearchBox_listbox']").first
                vessel_input.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                vessel_input.press_sequentially(v_name, delay=80)
                page.locator(f"ul#vesselSearchBox_listbox li:has-text('{v_name}')").first.click()
                time.sleep(1)

                target_frame = get_active_frame(page)
                if not target_frame:
                    logger.error(f"Abort: Missing active UI grid frameset for {v_name}")
                    metrics_summary[v_name] = "FRAME_ERROR"
                    continue

                fp = FROM_DATE.split('-')
                tp = TO_DATE.split('-')
                select_date_from_calendar(target_frame, "txtFromDate", fp[0], fp[1], fp[2])
                select_date_from_calendar(target_frame, "txtToDate", tp[0], tp[1], tp[2])

                search_btn = target_frame.locator("button#btnSearch").first
                search_btn.click()
                time.sleep(2.5)

                logger.info(f"Extracting spreadsheet grid metrics pipeline for {v_name}...")
                excel_records = download_grid_data(page, target_frame)
                if not excel_records:
                    logger.warning(f"No records returned out of data sheets for {v_name}.")
                    metrics_summary[v_name] = "NO_RECORDS"
                    continue

                df = pd.DataFrame(excel_records)
                date_col = next((c for c in df.columns if "date" in c.lower() or "log_date" in c.lower()), None)
                if not date_col:
                    logger.error(f"Execution Failure: No valid date mapping tracking inside {v_name} dataset.")
                    metrics_summary[v_name] = "MISSING_DATE_COLUMN"
                    continue

                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.dropna(subset=[date_col])

                daily_aggregated_fuel = {}
                for _, row in df.iterrows():
                    report_date = row[date_col].date()
                    total_fuel = calculate_mariapps_total_fuel(row.to_dict())
                    daily_aggregated_fuel[report_date] = round(daily_aggregated_fuel.get(report_date, 0.0) + total_fuel, 2)

                upsert_count = 0
                for report_date, total_fuel in daily_aggregated_fuel.items():
                    existing = db.query(FuelConsumption).filter_by(vessel_name=v_name, report_date=report_date).first()
                    if existing:
                        existing.total_fuel_consumption = total_fuel
                    else:
                        seed = f"{v_name.replace(' ', '_')}_{report_date}"
                        deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, seed)
                        db.add(FuelConsumption(
                            id=deterministic_uuid,
                            vessel_name=v_name,
                            report_date=report_date,
                            total_fuel_consumption=total_fuel
                        ))
                    upsert_count += 1
                
                db.commit()
                logger.info(f"Successfully processed and synchronized {upsert_count} calendar date logs for {v_name}.")
                metrics_summary[v_name] = f"SUCCESS ({upsert_count} rows)"
                
        finally:
            db.close()
            browser.close()
            if os.path.exists(AUTH_FILE):
                os.remove(AUTH_FILE)

    logger.info("========================================================================")
    logger.info("   MARIAPPS INGESTION PIPELINE SUMMARY METRICS GRID                     ")
    logger.info("========================================================================")
    for vessel, state in metrics_summary.items():
        logger.info(f"Vessel: {vessel:<22} | Synchronization Status: {state}")
    logger.info("========================================================================")

if __name__ == "__main__":
    run_mariapps_fuel_scraper()