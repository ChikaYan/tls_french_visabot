import json
import logging
import os
import random
import sys
import time
import traceback
from datetime import datetime

import requests
import undetected_chromedriver as uc
from selenium.common.exceptions import (ElementClickInterceptedException,
                                        NoSuchElementException,
                                        TimeoutException)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ── Configuration ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = '8630876891:AAFOL9tMGRhyt8pC1wWlQiGei1aQ-zzMirI'
TELEGRAM_CHAT_ID = 1044515516

TLS_HOME = 'https://visas-fr.tlscontact.com/visa/gb/gbLON2fr/home'
TLS_TRAVEL_GROUPS = 'https://visas-fr.tlscontact.com/en-us/travel-groups'
TLS_EMAIL = 'walterwuyan@gmail.com'
TLS_PASSWORD = '998182aA!#'

CHECK_INTERVAL = 300
HEADLESS = False
# ───────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(SCRIPT_DIR, "cookies.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "log.txt")


class TeeLogger:
    def __init__(self, log_path, stream):
        self.stream = stream
        self.file = open(log_path, 'a', encoding='utf-8')
        self.file.write(f"\n{'='*60}\n")
        self.file.write(f"Session started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.file.write(f"{'='*60}\n")

    def write(self, msg):
        if msg.strip():
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.file.write(f"[{ts}] {msg}\n")
            self.file.flush()
        self.stream.write(msg)
        self.stream.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()


sys.stdout = TeeLogger(LOG_FILE, sys.stdout)
sys.stderr = TeeLogger(LOG_FILE, sys.stderr)


def human_like_delay(low=1.0, high=2.5):
    time.sleep(random.uniform(low, high))


def send_telegram(message):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message},
            timeout=10
        )
        print(f"[TG] {message[:100]}")
    except Exception as e:
        print(f"Telegram send failed: {e}")


def send_telegram_photo(photo_path, caption=""):
    try:
        with open(photo_path, 'rb') as f:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto',
                data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption},
                files={'photo': f},
                timeout=30
            )
        print(f"[TG] Photo sent: {caption[:60]}")
    except Exception as e:
        print(f"Telegram photo send failed: {e}")


def save_debug(driver, label):
    ts = datetime.now().strftime('%H%M%S')
    path = os.path.join(SCRIPT_DIR, f"debug_{label}_{ts}.png")
    try:
        driver.save_screenshot(path)
        print(f"  [DEBUG] Screenshot: {path}")
        print(f"  [DEBUG] Title: {driver.title} | URL: {driver.current_url[:80]}")
    except Exception as e:
        print(f"  [DEBUG] Screenshot failed: {e}")
    return path


def save_cookies(driver):
    cookies = driver.get_cookies()
    with open(COOKIES_FILE, 'w') as f:
        json.dump(cookies, f)
    print(f"  Cookies saved ({len(cookies)} cookies)")


def load_cookies(driver):
    if not os.path.exists(COOKIES_FILE):
        return False
    try:
        with open(COOKIES_FILE, 'r') as f:
            cookies = json.load(f)
        driver.get(TLS_HOME)
        time.sleep(1)
        for cookie in cookies:
            cookie.pop('sameSite', None)
            cookie.pop('expiry', None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        print(f"  Loaded {len(cookies)} cookies from file")
        return True
    except Exception as e:
        print(f"  Failed to load cookies: {e}")
        return False


def wait_for_cloudflare(driver, timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        title = driver.title.lower()
        if "just a moment" not in title and "checking" not in title:
            print("  Cloudflare passed.")
            return True
        time.sleep(1)
    print("  Cloudflare timeout.")
    return False


def solve_recaptcha(driver, timeout=60):
    print("  Solving reCAPTCHA...")
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        recaptcha_frame = None
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "recaptcha" in src or "google.com/recaptcha" in src:
                recaptcha_frame = iframe
                break

        if not recaptcha_frame:
            print("  No reCAPTCHA found.")
            return True

        driver.switch_to.frame(recaptcha_frame)
        time.sleep(0.5)

        try:
            checkbox = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".recaptcha-checkbox-border, #recaptcha-anchor")))
            checkbox.click()
            print("  Clicked reCAPTCHA checkbox.")
        except Exception as e:
            print(f"  Could not click reCAPTCHA: {e}")

        driver.switch_to.default_content()
        time.sleep(2)

        driver.switch_to.frame(recaptcha_frame)
        for _ in range(5):
            try:
                anchor = driver.find_element(By.CSS_SELECTOR, "#recaptcha-anchor")
                if "recaptcha-checkbox-checked" in (anchor.get_attribute("class") or ""):
                    print("  reCAPTCHA auto-solved!")
                    driver.switch_to.default_content()
                    return True
            except Exception:
                pass
            time.sleep(1)
        driver.switch_to.default_content()

        print("  reCAPTCHA needs manual solving!")
        send_telegram("⚠️ reCAPTCHA needs manual solving! Go to your PC and click the CAPTCHA.")

        start_t = time.time()
        while time.time() - start_t < timeout:
            try:
                if "auth" not in driver.current_url and "login" not in driver.current_url:
                    print("  Page changed — reCAPTCHA solved!")
                    return True
                for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
                    src = iframe.get_attribute("src") or ""
                    if "recaptcha" in src:
                        driver.switch_to.frame(iframe)
                        try:
                            anchor = driver.find_element(By.CSS_SELECTOR, "#recaptcha-anchor")
                            if "recaptcha-checkbox-checked" in (anchor.get_attribute("class") or ""):
                                driver.switch_to.default_content()
                                print("  reCAPTCHA solved manually!")
                                return True
                        except Exception:
                            pass
                        driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
            time.sleep(2)

        print("  reCAPTCHA timeout.")
        return False
    except Exception as e:
        print(f"  reCAPTCHA error: {e}")
        driver.switch_to.default_content()
        return False


def create_driver():
    options = uc.ChromeOptions()
    if HEADLESS:
        options.add_argument('--headless=new')
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    driver = uc.Chrome(options=options, version_main=None)
    return driver


# ─────────────────────────────────────────────────────────────
# LOGIN — proven working flow from 18:35:54 session
# Home page → click Login link → fill form → reCAPTCHA → submit
# ─────────────────────────────────────────────────────────────

def do_login(driver):
    # Try saved cookies first
    if load_cookies(driver):
        driver.get(TLS_TRAVEL_GROUPS)
        time.sleep(2)
        wait_for_cloudflare(driver)
        if "travel-groups" in driver.current_url:
            print("  Logged in via saved cookies!")
            return True
        # Maybe redirected but still logged in
        if "auth" not in driver.current_url and "login" not in driver.current_url:
            page = driver.page_source.lower()
            if "application" in page or "travel" in page:
                print("  Logged in via saved cookies!")
                return True
        print("  Cookies expired, fresh login...")

    # Start from home page (proven working)
    driver.get(TLS_HOME)
    time.sleep(2)
    wait_for_cloudflare(driver)

    # Accept cookies banner
    try:
        accept = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(@class, 'osano-cm-accept-all')]")))
        accept.click()
        print("  Cookies accepted.")
    except TimeoutException:
        print("  No cookie banner.")

    human_like_delay()

    # Click Login link — confirmed: //a[contains(@href, 'login')]
    try:
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'login')]")))
        print("  Found Login button.")
        human_like_delay()
        login_button.click()
        print("  Clicked Login.")
    except TimeoutException:
        save_debug(driver, "no_login_btn")
        return False

    time.sleep(1)
    wait_for_cloudflare(driver)

    # Fill email + password
    try:
        email_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "#username, #email-input-field, input[name='username'], input[type='email']")))
        email_input.clear()
        email_input.send_keys(TLS_EMAIL)
        print(f"  Email entered (id={email_input.get_attribute('id')}).")

        password_input = driver.find_element(By.CSS_SELECTOR,
            "#password, input[name='password'], input[type='password']")
        password_input.clear()
        password_input.send_keys(TLS_PASSWORD)
        print("  Password entered.")
    except (TimeoutException, NoSuchElementException) as e:
        print(f"  Login form error: {e}")
        debug_path = save_debug(driver, "login_form_fail")
        send_telegram_photo(debug_path, "Cannot fill login form")
        return False

    # Find submit button BEFORE reCAPTCHA
    submit_button = None
    try:
        submit_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "#kc-login, button[type='submit'], input[type='submit']")))
        print(f"  Found Submit button via CSS (text='{submit_button.text}').")
    except TimeoutException:
        try:
            submit_button = driver.find_element(By.XPATH,
                "//button[contains(text(),'Login')] | //button[contains(text(),'login')] | "
                "//a[contains(text(),'Login')] | //button[.//span[contains(text(),'Login')]]")
            print(f"  Found Submit button via text (text='{submit_button.text}').")
        except NoSuchElementException:
            try:
                submit_button = driver.find_element(By.XPATH,
                    "//form//button | //div[contains(@class,'login')]//button")
                print(f"  Found Submit button via form (text='{submit_button.text}').")
            except NoSuchElementException:
                debug_path = save_debug(driver, "no_submit_btn")
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for i, btn in enumerate(buttons):
                    print(f"  [DEBUG] Button {i}: text='{btn.text}' class='{btn.get_attribute('class')}' type='{btn.get_attribute('type')}' id='{btn.get_attribute('id')}'")
                send_telegram_photo(debug_path, "Cannot find submit button")
                return False

    # Solve reCAPTCHA right before submit
    if not solve_recaptcha(driver):
        debug_path = save_debug(driver, "recaptcha_fail")
        send_telegram_photo(debug_path, "reCAPTCHA failed")
        return False

    # Click submit IMMEDIATELY
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
    driver.execute_script("arguments[0].click();", submit_button)
    print("  Login submitted.")

    time.sleep(3)

    # Verify login
    if "auth" in driver.current_url or "login" in driver.current_url.lower():
        debug_path = save_debug(driver, "login_stuck")
        page_lower = driver.page_source.lower()
        if "recaptcha" in page_lower or "captcha" in page_lower:
            print("  Still on login — waiting for manual reCAPTCHA solve...")
            send_telegram("⚠️ Still on login page. Solve reCAPTCHA on your PC!")
            start = time.time()
            while time.time() - start < 60:
                if "auth" not in driver.current_url and "login" not in driver.current_url.lower():
                    break
                time.sleep(2)
            if "auth" in driver.current_url or "login" in driver.current_url.lower():
                send_telegram_photo(debug_path, "Login failed after 60s")
                return False
        else:
            send_telegram_photo(debug_path, "Login failed — wrong credentials?")
            return False

    print("  Login successful!")
    save_cookies(driver)
    return True


# ─────────────────────────────────────────────────────────────
# APPOINTMENT CHECK — Manus flow with verified selectors
# travel-groups → Select → Continue → check slots
# ─────────────────────────────────────────────────────────────

def check_appointments(driver):
    # Navigate to travel groups page
    if "travel-groups" not in driver.current_url:
        driver.get(TLS_TRAVEL_GROUPS)
        time.sleep(2)
        wait_for_cloudflare(driver)

    save_debug(driver, "travel_groups")

    # 1. Click "Select" on existing travel group
    #    Confirmed: <button name="formGroupId" type="submit" value="26091640">Select</button>
    try:
        select_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[@name='formGroupId']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", select_btn)
        select_btn.click()
        print(f"  Clicked 'Select' (value={select_btn.get_attribute('value')}).")
        human_like_delay()
    except TimeoutException:
        # Fallback: any button with "Select" text
        try:
            select_btn = driver.find_element(By.XPATH,
                "//button[contains(text(), 'Select')]")
            select_btn.click()
            print("  Clicked 'Select' via text fallback.")
            human_like_delay()
        except NoSuchElementException:
            debug_path = save_debug(driver, "no_select_btn")
            # Dump buttons for debugging
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for i, btn in enumerate(buttons):
                print(f"  [DEBUG] Button {i}: text='{btn.text}' name='{btn.get_attribute('name')}' type='{btn.get_attribute('type')}'")
            send_telegram_photo(debug_path, "Cannot find Select button on travel groups page")
            return False

    # 2. Click "Continue" to go to appointment booking
    #    Confirmed: <a id="book-appointment-btn">Continue</a>
    try:
        continue_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "book-appointment-btn")))
        driver.execute_script("arguments[0].scrollIntoView(true);", continue_btn)
        continue_btn.click()
        print("  Clicked 'Continue' (book-appointment-btn).")
        human_like_delay()
    except TimeoutException:
        # Fallback
        try:
            continue_btn = driver.find_element(By.XPATH,
                "//a[contains(text(), 'Continue')] | //button[contains(text(), 'Continue')]")
            continue_btn.click()
            print("  Clicked 'Continue' via text fallback.")
            human_like_delay()
        except NoSuchElementException:
            debug_path = save_debug(driver, "no_continue_btn")
            send_telegram_photo(debug_path, "Cannot find Continue button")
            return False

    wait_for_cloudflare(driver)
    time.sleep(2)
    save_debug(driver, "appointment_page")

    # 3. Check for slots
    def check_current_view():
        # "No slots" is a <p> tag, NOT a popup button
        try:
            driver.find_element(By.XPATH,
                "//p[contains(text(), 'appointment slots available')]")
            print(f"  No appointments at {datetime.now().strftime('%H:%M:%S')}")
            return False
        except NoSuchElementException:
            pass

        try:
            available = driver.find_element(By.XPATH,
                "//button[contains(@class, '-available') or contains(@class, 'slot')]")
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            msg = f"APPOINTMENT FOUND at {now}!"
            print(f"  {msg}")
            send_telegram(f"🚨 {msg}")

            available.click()
            human_like_delay()

            screenshot_path = os.path.join(SCRIPT_DIR, "appointment_found.png")
            driver.save_screenshot(screenshot_path)
            send_telegram_photo(screenshot_path,
                "Slot clicked! Open TLScontact NOW to finish booking!")

            input(">>> APPOINTMENT FOUND! Press Enter to close browser... <<<")
            return True
        except NoSuchElementException:
            print("  No slots in current view.")
            return False

    print("  Checking current month...")
    if check_current_view():
        return True

    # 4. Try next month
    try:
        next_month = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//a[@data-testid='btn-next-month-available']")))
        next_month.click()
        print("  Clicked next month.")
        human_like_delay()

        print("  Checking next month...")
        if check_current_view():
            return True
    except TimeoutException:
        print("  No next month button.")

    return False


def check_once():
    driver = None
    try:
        driver = create_driver()

        if not do_login(driver):
            return False

        return check_appointments(driver)

    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        if driver:
            debug_path = save_debug(driver, "error")
            send_telegram_photo(debug_path, f"Bot error: {str(e)[:200]}")
        else:
            send_telegram(f"Bot error: {str(e)[:200]}")
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    print("=" * 60)
    print("TLScontact France Visa Slot Checker")
    print(f"Check interval: {CHECK_INTERVAL}s | Headless: {HEADLESS}")
    print("=" * 60)

    send_telegram(f"🤖 TLS Visa Bot started! Checking every {CHECK_INTERVAL}s.")

    check_count = 0
    while True:
        check_count += 1
        print(f"\n[Check #{check_count} at {datetime.now().strftime('%H:%M:%S')}]")

        found = check_once()
        if found:
            send_telegram("🎉 Appointment process started. Bot stopping.")
            break

        print(f"  Waiting {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
