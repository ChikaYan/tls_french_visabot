import os
import random
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

CHECK_INTERVAL = 60
HEADLESS = False  # Keep False until login flow is confirmed working
# ───────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def human_like_delay():
    time.sleep(random.uniform(1.5, 3.0))


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
    """Save screenshot + page title for debugging."""
    ts = datetime.now().strftime('%H%M%S')
    path = os.path.join(SCRIPT_DIR, f"debug_{label}_{ts}.png")
    try:
        driver.save_screenshot(path)
        print(f"  [DEBUG] Screenshot saved: {path}")
        print(f"  [DEBUG] Page title: {driver.title}")
        print(f"  [DEBUG] Current URL: {driver.current_url}")
    except Exception as e:
        print(f"  [DEBUG] Screenshot failed: {e}")
    return path


def find_element_flexible(driver, wait, selectors, description):
    """Try multiple selectors, return first match. Raises TimeoutException if none found."""
    for selector_type, selector_value in selectors:
        try:
            elem = wait.until(EC.element_to_be_clickable((selector_type, selector_value)))
            print(f"  Found '{description}' via: {selector_value}")
            return elem
        except TimeoutException:
            continue
    raise TimeoutException(f"Could not find '{description}' with any selector")


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


def check_once():
    """Run one full check cycle. Returns True if appointment found and clicked."""
    driver = None
    try:
        driver = create_driver()
        wait = WebDriverWait(driver, 20)
        short_wait = WebDriverWait(driver, 10)

        # ── Step 1: Open website ──
        print("  Opening TLScontact...")
        driver.get(TLS_URL)
        human_like_delay()
        save_debug(driver, "01_home")

        # ── Step 2: Accept cookies (optional) ──
        try:
            accept_button = short_wait.until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[contains(@class, 'osano-cm-accept-all')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", accept_button)
            human_like_delay()
            accept_button.click()
            print("  Cookies accepted.")
        except TimeoutException:
            print("  No cookie banner, continuing...")

        # ── Step 3: Click Login ──
        try:
            login_button = find_element_flexible(driver, wait, [
                (By.XPATH, "//a[contains(@class, 'tls-button-link') and contains(text(),'Login')]"),
                (By.XPATH, "//a[contains(@class, 'tls-button-link') and contains(text(),'log in')]"),
                (By.XPATH, "//a[contains(@class, 'tls-button') and contains(text(),'Login')]"),
                (By.XPATH, "//button[contains(text(),'Login')]"),
                (By.XPATH, "//a[contains(text(),'Login')]"),
                (By.XPATH, "//a[contains(text(),'Log in')]"),
                (By.XPATH, "//a[contains(@href, 'login')]"),
            ], "Login button")
            human_like_delay()
            login_button.click()
            print("  Clicked Login.")
        except TimeoutException:
            debug_path = save_debug(driver, "02_no_login_btn")
            send_telegram_photo(debug_path, "❌ Can't find Login button — page screenshot attached")
            return False

        human_like_delay()
        save_debug(driver, "03_login_page")

        # ── Step 4: Fill credentials ──
        try:
            email_input = find_element_flexible(driver, wait, [
                (By.ID, "username"),
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[name='email']"),
                (By.CSS_SELECTOR, "input[id*='email']"),
                (By.CSS_SELECTOR, "input[id*='user']"),
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

            submit_button = find_element_flexible(driver, wait, [
                (By.ID, "kc-login"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.XPATH, "//button[contains(text(),'Log')]"),
                (By.XPATH, "//button[contains(text(),'Sign')]"),
            ], "Submit button")
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
            driver.execute_script("arguments[0].click();", submit_button)
            human_like_delay()
            print("  Login submitted.")
        except TimeoutException:
            debug_path = save_debug(driver, "04_login_form_fail")
            send_telegram_photo(debug_path, "❌ Can't fill login form — screenshot attached")
            return False

        save_debug(driver, "05_after_login")

        # Check if login failed
        if "login" in driver.current_url.lower() and "error" in driver.page_source.lower():
            debug_path = save_debug(driver, "05_login_failed")
            send_telegram_photo(debug_path, "❌ Login failed — wrong credentials?")
            return False

        print("  Login successful.")

        # ── Step 5: Click "Enter" button ──
        human_like_delay()
        driver.execute_script("window.scrollTo(0, 500)")
        try:
            enter_button = find_element_flexible(driver, short_wait, [
                (By.XPATH, '//button[@class="tls-button-primary button-neo-inside"]'),
                (By.XPATH, '//button[contains(@class, "tls-button-primary")]'),
                (By.XPATH, '//button[contains(@class, "button-neo-inside")]'),
                (By.XPATH, '//button[contains(text(), "Enter")]'),
                (By.XPATH, '//button[contains(text(), "Continue")]'),
                (By.XPATH, '//a[contains(text(), "Enter")]'),
            ], "Enter button")
            ActionChains(driver).move_to_element(enter_button).click().perform()
            print("  Clicked 'Enter'.")
        except TimeoutException:
            print("  No 'Enter' button found, may already be on dashboard.")
            save_debug(driver, "06_no_enter")

        human_like_delay()

        # ── Step 6: Click "Book appointment" ──
        driver.execute_script("window.scrollTo(0, 3000)")
        try:
            book_btn = find_element_flexible(driver, short_wait, [
                (By.XPATH, '//button[@class="button-neo-inside -primary"]'),
                (By.XPATH, '//button[contains(@class, "-primary") and contains(@class, "button-neo")]'),
                (By.XPATH, '//button[contains(text(), "Book")]'),
                (By.XPATH, '//button[contains(text(), "Appointment")]'),
                (By.XPATH, '//a[contains(text(), "Book")]'),
                (By.XPATH, '//button[contains(@class, "primary")]'),
            ], "Book appointment button")
            driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
            ActionChains(driver).move_to_element(book_btn).click().perform()
            print("  Clicked 'Book appointment'.")
        except TimeoutException:
            print("  No 'Book appointment' button found.")
            save_debug(driver, "07_no_book")

        human_like_delay()
        save_debug(driver, "08_appointment_page")

        # ── Step 7: Check for "no appointments" popup ──
        try:
            no_appt = short_wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@class='tls-button-primary -uppercase']")))
            print(f"  No appointments available at {datetime.now().strftime('%H:%M:%S')}")
            ActionChains(driver).move_to_element(no_appt).click().perform()
            return False
        except TimeoutException:
            print("  No 'no appointments' popup — checking for slots...")

        # ── Step 8: Check for available appointment ──
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
                "✅ Slot clicked! Open TLScontact NOW to finish booking and pay!")

            input(">>> APPOINTMENT FOUND! Press Enter to close browser... <<<")
            return True
        except NoSuchElementException:
            print("  No available slots on page.")
            return False

    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        if driver:
            debug_path = save_debug(driver, "error")
            send_telegram_photo(debug_path, f"⚠️ Bot error: {str(e)[:200]}")
        else:
            send_telegram(f"⚠️ Bot error (no browser): {str(e)[:200]}")
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

    send_telegram("🤖 TLS Visa Bot started! Checking every 60s for France/London slots.")

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
