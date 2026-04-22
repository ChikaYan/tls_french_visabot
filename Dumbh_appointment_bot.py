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

TLS_URL = 'https://visas-fr.tlscontact.com/visa/gb/gbLON2fr/home'
TLS_EMAIL = 'walterwuyan@gmail.com'
TLS_PASSWORD = '998182aA!#'

CHECK_INTERVAL = 180
HEADLESS = False  # Keep False — need to see reCAPTCHA if manual solve required
# ───────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(SCRIPT_DIR, "cookies.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "log.txt")


class TeeLogger:
    """Redirect stdout/stderr to both console and log file with timestamps."""
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


def human_like_delay(low=1.5, high=3.0):
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


def find_element_flexible(driver, wait, selectors, description):
    for selector_type, selector_value in selectors:
        try:
            elem = wait.until(EC.element_to_be_clickable((selector_type, selector_value)))
            print(f"  Found '{description}' via: {selector_value}")
            return elem
        except TimeoutException:
            continue
    raise TimeoutException(f"Could not find '{description}' with any selector")


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
        driver.get(TLS_URL)
        human_like_delay(3, 5)
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


def wait_for_cloudflare(driver, timeout=30):
    """Wait for Cloudflare challenge to pass."""
    print("  Waiting for Cloudflare challenge...")
    start = time.time()
    while time.time() - start < timeout:
        title = driver.title.lower()
        if "just a moment" not in title and "checking" not in title:
            print("  Cloudflare passed.")
            return True
        time.sleep(2)
    print("  Cloudflare timeout — may need manual solve.")
    return False


def solve_recaptcha(driver, timeout=60):
    """Try to click reCAPTCHA checkbox. If it needs manual solve, wait for user."""
    print("  Attempting to solve reCAPTCHA...")

    # reCAPTCHA lives in an iframe — switch to it
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        recaptcha_frame = None
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "recaptcha" in src or "google.com/recaptcha" in src:
                recaptcha_frame = iframe
                break

        if not recaptcha_frame:
            print("  No reCAPTCHA iframe found — may not be required.")
            return True

        # Click the reCAPTCHA checkbox
        driver.switch_to.frame(recaptcha_frame)
        human_like_delay(1, 2)

        try:
            checkbox = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".recaptcha-checkbox-border, #recaptcha-anchor"))
            )
            checkbox.click()
            print("  Clicked reCAPTCHA checkbox.")
        except Exception as e:
            print(f"  Could not click reCAPTCHA checkbox: {e}")

        driver.switch_to.default_content()
        human_like_delay(3, 5)

        # Check if reCAPTCHA was solved (checkbox turns green)
        driver.switch_to.frame(recaptcha_frame)
        start = time.time()
        while time.time() - start < 10:
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

        # If not auto-solved, wait for manual solve
        print("  ⚠️  reCAPTCHA needs manual solving! Please solve it in the browser window.")
        send_telegram("⚠️ reCAPTCHA needs manual solving! Go to your PC and click the CAPTCHA.")

        start = time.time()
        while time.time() - start < timeout:
            try:
                # Check if we've left the login page (login succeeded)
                if "auth" not in driver.current_url and "login" not in driver.current_url:
                    print("  Login page left — reCAPTCHA was solved!")
                    return True
                # Check if reCAPTCHA is solved
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

        print("  reCAPTCHA timeout — could not solve.")
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


def do_login(driver, wait):
    """Full login flow with reCAPTCHA handling. Returns True if logged in."""

    # Try loading saved cookies first
    if load_cookies(driver):
        driver.get(TLS_URL)
        human_like_delay(3, 5)
        wait_for_cloudflare(driver)
        # Check if cookies gave us a logged-in session
        if "auth" not in driver.current_url and "login" not in driver.current_url:
            page = driver.page_source.lower()
            if "login" not in driver.title.lower() and ("appointment" in page or "dashboard" in page or "application" in page):
                print("  Logged in via saved cookies!")
                return True
        print("  Cookies expired, doing fresh login...")

    # Fresh login
    driver.get(TLS_URL)
    human_like_delay(3, 5)
    wait_for_cloudflare(driver)

    # Accept cookies
    try:
        accept_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(@class, 'osano-cm-accept-all')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", accept_button)
        human_like_delay()
        accept_button.click()
        print("  Cookies accepted.")
    except TimeoutException:
        print("  No cookie banner, continuing...")

    # Click Login
    try:
        login_button = find_element_flexible(driver, wait, [
            (By.XPATH, "//a[contains(@class, 'tls-button-link') and contains(text(),'Login')]"),
            (By.XPATH, "//a[contains(@class, 'tls-button') and contains(text(),'Login')]"),
            (By.XPATH, "//a[contains(text(),'Login')]"),
            (By.XPATH, "//a[contains(text(),'Log in')]"),
            (By.XPATH, "//a[contains(@href, 'login')]"),
        ], "Login button")
        human_like_delay()
        login_button.click()
        print("  Clicked Login.")
    except TimeoutException:
        debug_path = save_debug(driver, "no_login_btn")
        send_telegram_photo(debug_path, "Cannot find Login button")
        return False

    human_like_delay(3, 5)

    # Wait for Cloudflare on login page too
    wait_for_cloudflare(driver)

    # Fill credentials
    try:
        email_input = find_element_flexible(driver, wait, [
            (By.ID, "username"),
            (By.NAME, "username"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[name='email']"),
        ], "Email field")
        email_input.clear()
        email_input.send_keys(TLS_EMAIL)
        human_like_delay()

        password_input = find_element_flexible(driver, wait, [
            (By.ID, "password"),
            (By.NAME, "password"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ], "Password field")
        password_input.clear()
        password_input.send_keys(TLS_PASSWORD)
        human_like_delay()
    except TimeoutException:
        debug_path = save_debug(driver, "login_form_fail")
        send_telegram_photo(debug_path, "Cannot fill login form")
        return False

    # Solve reCAPTCHA BEFORE clicking Login
    if not solve_recaptcha(driver):
        debug_path = save_debug(driver, "recaptcha_fail")
        send_telegram_photo(debug_path, "reCAPTCHA failed — login blocked")
        return False

    # Click Login button
    try:
        submit_button = find_element_flexible(driver, wait, [
            (By.ID, "kc-login"),
            (By.XPATH, "//button[text()='Login']"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
        ], "Submit button")
        driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
        driver.execute_script("arguments[0].click();", submit_button)
        print("  Login submitted.")
    except TimeoutException:
        debug_path = save_debug(driver, "no_submit_btn")
        send_telegram_photo(debug_path, "Cannot find submit button")
        return False

    human_like_delay(4, 6)

    # Verify login succeeded — should redirect away from auth page
    if "auth" in driver.current_url or "login" in driver.current_url.lower():
        # Maybe there's a second reCAPTCHA or error
        debug_path = save_debug(driver, "login_stuck")
        page_lower = driver.page_source.lower()
        if "recaptcha" in page_lower or "captcha" in page_lower:
            print("  Still on login page — reCAPTCHA may need re-solving.")
            send_telegram("⚠️ Still on login page after submit. Check reCAPTCHA on your PC!")
            # Wait up to 90s for manual intervention
            start = time.time()
            while time.time() - start < 90:
                if "auth" not in driver.current_url and "login" not in driver.current_url.lower():
                    break
                time.sleep(3)
            if "auth" in driver.current_url or "login" in driver.current_url.lower():
                send_telegram_photo(debug_path, "Login failed — still on login page after 90s")
                return False
        else:
            send_telegram_photo(debug_path, "Login failed — wrong credentials?")
            return False

    print("  Login successful!")
    save_cookies(driver)
    return True


def check_appointments(driver, wait, short_wait):
    """After login, navigate to appointments and check. Returns True if slot found."""

    save_debug(driver, "dashboard")

    # Click "Enter" button (application dashboard)
    human_like_delay()
    driver.execute_script("window.scrollTo(0, 500)")
    try:
        enter_button = find_element_flexible(driver, short_wait, [
            (By.XPATH, '//button[@class="tls-button-primary button-neo-inside"]'),
            (By.XPATH, '//button[contains(@class, "tls-button-primary")]'),
            (By.XPATH, '//button[contains(@class, "button-neo-inside")]'),
            (By.XPATH, '//button[contains(text(), "Enter")]'),
            (By.XPATH, '//button[contains(text(), "Continue")]'),
        ], "Enter button")
        ActionChains(driver).move_to_element(enter_button).click().perform()
        print("  Clicked 'Enter'.")
        human_like_delay()
    except TimeoutException:
        print("  No 'Enter' button, may already be on right page.")

    # Click "Book appointment"
    driver.execute_script("window.scrollTo(0, 3000)")
    try:
        book_btn = find_element_flexible(driver, short_wait, [
            (By.XPATH, '//button[@class="button-neo-inside -primary"]'),
            (By.XPATH, '//button[contains(@class, "-primary") and contains(@class, "button-neo")]'),
            (By.XPATH, '//button[contains(text(), "Book")]'),
            (By.XPATH, '//a[contains(text(), "Book")]'),
        ], "Book appointment button")
        driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
        ActionChains(driver).move_to_element(book_btn).click().perform()
        print("  Clicked 'Book appointment'.")
        human_like_delay()
    except TimeoutException:
        print("  No 'Book appointment' button found.")
        save_debug(driver, "no_book_btn")

    save_debug(driver, "appointment_page")

    # Check for "no appointments" popup
    try:
        no_appt = short_wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@class='tls-button-primary -uppercase']")))
        print(f"  No appointments available at {datetime.now().strftime('%H:%M:%S')}")
        ActionChains(driver).move_to_element(no_appt).click().perform()
        return False
    except TimeoutException:
        print("  No 'no appointments' popup — checking for slots...")

    # Check for available appointment
    try:
        available = driver.find_element(
            By.XPATH, "//button[contains(@class, '-available')]")
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = f"APPOINTMENT FOUND at {now}!"
        print(f"  {msg}")
        send_telegram(f"🚨 {msg}")

        available.click()
        human_like_delay()

        screenshot_path = os.path.join(SCRIPT_DIR, "appointment_found.png")
        driver.save_screenshot(screenshot_path)
        send_telegram_photo(screenshot_path,
            "Slot clicked! Open TLScontact NOW to finish booking and pay!")

        input(">>> APPOINTMENT FOUND! Press Enter to close browser... <<<")
        return True
    except NoSuchElementException:
        print("  No available slots on page.")
        return False


def check_once():
    """Run one full check cycle. Returns True if appointment found."""
    driver = None
    try:
        driver = create_driver()
        wait = WebDriverWait(driver, 20)
        short_wait = WebDriverWait(driver, 10)

        if not do_login(driver, wait):
            return False

        return check_appointments(driver, wait, short_wait)

    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        if driver:
            debug_path = save_debug(driver, "error")
            send_telegram_photo(debug_path, f"Bot error: {str(e)[:200]}")
        else:
            send_telegram(f"Bot error (no browser): {str(e)[:200]}")
        return False
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    print("=" * 60)
    print("TLScontact France Visa Slot Checker")
    print(f"URL: {TLS_URL}")
    print(f"Check interval: {CHECK_INTERVAL}s | Headless: {HEADLESS}")
    print("=" * 60)
    print()
    print("NOTE: On first run you may need to manually solve a reCAPTCHA")
    print("in the browser window. After that, cookies are saved for reuse.")
    print()

    send_telegram("🤖 TLS Visa Bot started! Checking every 180s for France/London slots.")

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
