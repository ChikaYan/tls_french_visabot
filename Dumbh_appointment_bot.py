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


def human_like_delay(low=0.5, high=1.2):
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


def find_first(driver, selectors, description, timeout=8):
    """Poll all selectors simultaneously until one matches or timeout."""
    end = time.time() + timeout
    while time.time() < end:
        for selector_type, selector_value in selectors:
            try:
                elem = driver.find_element(selector_type, selector_value)
                if elem.is_displayed():
                    print(f"  Found '{description}' via: {selector_value}")
                    return elem
            except (NoSuchElementException, Exception):
                continue
        time.sleep(0.3)
    raise TimeoutException(f"Could not find '{description}'")


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


def wait_for_cloudflare(driver, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        title = driver.title.lower()
        if "just a moment" not in title and "checking" not in title:
            print("  Cloudflare passed.")
            return True
        time.sleep(0.5)
    print("  Cloudflare timeout.")
    return False


def solve_recaptcha(driver, timeout=60):
    """Click reCAPTCHA checkbox. If manual solve needed, wait for user."""
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
            print("  No reCAPTCHA found — not required.")
            return True

        driver.switch_to.frame(recaptcha_frame)
        time.sleep(0.5)

        try:
            checkbox = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".recaptcha-checkbox-border, #recaptcha-anchor"))
            )
            checkbox.click()
            print("  Clicked reCAPTCHA checkbox.")
        except Exception as e:
            print(f"  Could not click reCAPTCHA: {e}")

        driver.switch_to.default_content()
        time.sleep(2)

        # Quick check if auto-solved
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

        # Manual solve needed
        print("  reCAPTCHA needs manual solving!")
        send_telegram("⚠️ reCAPTCHA needs manual solving! Go to your PC and click the CAPTCHA.")

        start = time.time()
        while time.time() - start < timeout:
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


def do_login(driver):
    """Full login flow. Returns True if logged in."""

    # Try saved cookies first
    if load_cookies(driver):
        driver.get(TLS_URL)
        time.sleep(1)
        wait_for_cloudflare(driver)
        url = driver.current_url.lower()
        # Detect expired/invalid sessions
        if "expired" in url or "login" in url or "auth" in url:
            print(f"  Cookies invalid (landed on {url[:60]}), fresh login...")
            os.remove(COOKIES_FILE)
            print("  Deleted stale cookies file.")
        else:
            print("  Logged in via saved cookies!")
            return True

    # Fresh login
    driver.get(TLS_URL)
    time.sleep(1)
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

    # Click Login link — confirmed selector: //a[contains(@href, 'login')]
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
                "#username, input[name='username'], input[type='email']")))
        print(f"  Found Email field (tag={email_input.tag_name}, id={email_input.get_attribute('id')})")
        email_input.clear()
        email_input.send_keys(TLS_EMAIL)
        print("  Email entered.")

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

    # Locate submit button FIRST (fast, before reCAPTCHA)
    try:
        submit_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "#kc-login, button[type='submit'], input[type='submit']")))
        print(f"  Found Submit button (tag={submit_button.tag_name}, text={submit_button.text})")
    except TimeoutException:
        # Fallback: any button/a containing "Login" text
        try:
            submit_button = driver.find_element(By.XPATH,
                "//button[contains(text(),'Login')] | //button[contains(text(),'login')] | "
                "//a[contains(text(),'Login')] | //button[.//span[contains(text(),'Login')]]")
            print(f"  Found Submit button via text fallback (tag={submit_button.tag_name}).")
        except NoSuchElementException:
            # Last resort: find the button nearest to the password field
            try:
                submit_button = driver.find_element(By.XPATH,
                    "//form//button | //div[contains(@class,'login')]//button")
                print(f"  Found Submit button via form fallback (tag={submit_button.tag_name}, text={submit_button.text}).")
            except NoSuchElementException:
                debug_path = save_debug(driver, "no_submit_btn")
                # Dump all buttons on page for debugging
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for i, btn in enumerate(buttons):
                    print(f"  [DEBUG] Button {i}: text='{btn.text}' class='{btn.get_attribute('class')}' type='{btn.get_attribute('type')}' id='{btn.get_attribute('id')}'")
                send_telegram_photo(debug_path, "Cannot find submit button")
                return False

    # Solve reCAPTCHA right before clicking submit
    if not solve_recaptcha(driver):
        debug_path = save_debug(driver, "recaptcha_fail")
        send_telegram_photo(debug_path, "reCAPTCHA failed")
        return False

    # Click submit IMMEDIATELY after reCAPTCHA
    driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
    driver.execute_script("arguments[0].click();", submit_button)
    print("  Login submitted.")

    time.sleep(1.5)

    # Verify login
    if "auth" in driver.current_url or "login" in driver.current_url.lower():
        debug_path = save_debug(driver, "login_stuck")
        page_lower = driver.page_source.lower()
        if "recaptcha" in page_lower or "captcha" in page_lower:
            print("  Still on login — reCAPTCHA may have expired. Waiting for manual solve...")
            send_telegram("⚠️ Still on login page. reCAPTCHA may have expired — solve it on your PC!")
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
# POST-LOGIN: Manus-verified flow
# travel-groups → Select existing group → Continue → check slots
# ─────────────────────────────────────────────────────────────

def check_appointments(driver):
    """After login, navigate through booking flow and check for slots."""

    save_debug(driver, "post_login")
    print(f"  Post-login URL: {driver.current_url}")

    # Navigate to travel groups if not already there
    if "travel-groups" not in driver.current_url:
        driver.get('https://visas-fr.tlscontact.com/en-us/travel-groups')
        time.sleep(2)
        wait_for_cloudflare(driver)

    save_debug(driver, "travel_groups")

    # Dismiss cookie banner if it reappeared
    try:
        accept = driver.find_element(By.XPATH, "//button[contains(@class, 'osano-cm-accept-all')]")
        accept.click()
        print("  Dismissed cookie banner.")
        time.sleep(0.5)
    except NoSuchElementException:
        pass

    # Step 1: Get into the application
    # Try "Select" button first (Manus-verified), then "Book an appointment" (seen in logs)
    clicked = False
    try:
        select_btns = driver.find_elements(By.XPATH, "//button[@name='formGroupId']")
        for btn in select_btns:
            if btn.is_displayed() and btn.text.strip():
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                driver.execute_script("arguments[0].click();", btn)
                print(f"  Clicked 'Select' (text='{btn.text}', value={btn.get_attribute('value')}).")
                clicked = True
                human_like_delay()
                break
    except Exception:
        pass

    if not clicked:
        try:
            book_btn = driver.find_element(By.XPATH,
                "//button[contains(text(), 'Book an appointment')] | "
                "//button[contains(text(), 'Book')] | "
                "//button[contains(text(), 'Select')]")
            driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", book_btn)
            print(f"  Clicked '{book_btn.text}'.")
            clicked = True
            human_like_delay()
        except NoSuchElementException:
            pass

    if not clicked:
        debug_path = save_debug(driver, "no_action_btn")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for i, btn in enumerate(buttons):
            if btn.text.strip():
                print(f"  [DEBUG] Button {i}: text='{btn.text}' name='{btn.get_attribute('name')}'")
        send_telegram_photo(debug_path, "Cannot find Select/Book button")
        return False

    # Step 2: Click "Continue" if present (services page)
    try:
        continue_btn = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "#book-appointment-btn, [data-testid='btn-book-appointment']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", continue_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", continue_btn)
        print("  Clicked 'Continue'.")
        human_like_delay()
    except TimeoutException:
        print("  No 'Continue' button — may already be on appointment page.")

    wait_for_cloudflare(driver)
    time.sleep(2)
    save_debug(driver, "appointment_page")

    # 3. Check for available slots
    def check_current_view():
        # "No slots" is a <p> tag: "We currently don't have any appointment slots available."
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


def is_session_alive(driver):
    """Check if the current browser session is still logged in."""
    try:
        url = driver.current_url.lower()
        if "expired" in url or "login" in url or "auth" in url:
            return False
        return True
    except Exception:
        return False


def main():
    print("=" * 60)
    print("TLScontact France Visa Slot Checker")
    print(f"URL: {TLS_URL}")
    print(f"Check interval: {CHECK_INTERVAL}s | Headless: {HEADLESS}")
    print("=" * 60)

    send_telegram(f"🤖 TLS Visa Bot started! Checking every {CHECK_INTERVAL}s for France/London slots.")

    driver = None
    logged_in = False
    check_count = 0

    try:
        while True:
            check_count += 1
            print(f"\n[Check #{check_count} at {datetime.now().strftime('%H:%M:%S')}]")

            # Create driver if we don't have one (first run or after crash)
            if driver is None:
                try:
                    driver = create_driver()
                    logged_in = False
                except Exception as e:
                    print(f"  Failed to create driver: {e}")
                    send_telegram(f"⚠️ Failed to create browser: {str(e)[:100]}")
                    time.sleep(CHECK_INTERVAL)
                    continue

            # Login if needed
            if not logged_in:
                try:
                    if do_login(driver):
                        logged_in = True
                    else:
                        print("  Login failed, will retry next cycle.")
                        time.sleep(CHECK_INTERVAL)
                        continue
                except Exception as e:
                    print(f"  Login error: {e}")
                    traceback.print_exc()
                    # Browser may have crashed, recreate next cycle
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None
                    logged_in = False
                    time.sleep(CHECK_INTERVAL)
                    continue

            # Check appointments using the live session
            try:
                found = check_appointments(driver)

                if found:
                    send_telegram("🎉 Appointment process started. Bot stopping.")
                    break

                # After checking, verify session is still alive
                if not is_session_alive(driver):
                    print("  Session expired during check, will re-login next cycle.")
                    logged_in = False

                # Save fresh cookies after each successful check
                save_cookies(driver)

            except Exception as e:
                print(f"  ERROR during check: {e}")
                traceback.print_exc()
                try:
                    debug_path = save_debug(driver, "error")
                    send_telegram_photo(debug_path, f"Bot error: {str(e)[:200]}")
                except Exception:
                    send_telegram(f"⚠️ Bot error: {str(e)[:150]}")

                # Check if browser died
                try:
                    _ = driver.current_url
                except Exception:
                    print("  Browser crashed, will recreate next cycle.")
                    driver = None
                    logged_in = False

                # Session might have expired
                if driver and not is_session_alive(driver):
                    logged_in = False

            print(f"  Waiting {CHECK_INTERVAL}s...")
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == '__main__':
    main()
