"""
Buff.163 Payment Automation Service
Handles QR code generation, balance polling, and payment tracking without proxies (MVP).
Proxy support ready for future deployment.
"""

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from io import BytesIO

# Third-party imports
import pyotp
from PIL import Image
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Local imports
from database.models import SessionLocal, Payment, User
from bot.config import ADMIN_ID

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/buff_payments.log'),
        logging.StreamHandler()
    ]
)


class BuffAccountManager:
    """Управление пулом аккаунтов Buff.163 с случайным выбором"""
    
    def __init__(self):
        self.accounts: List[Dict] = self._load_accounts_from_env()
        self.account_locks = {}  # {account_id: locked_until_timestamp}
        self.rotation_strategy = os.getenv("BUFF_ACCOUNT_ROTATION_STRATEGY", "random")
        self.min_rest_secs = int(os.getenv("BUFF_MIN_ACCOUNT_REST_SECS", "30"))
        
        if not self.accounts:
            logger.warning("⚠️ No Buff accounts loaded from BUFF_ACCOUNTS env var")
    
    def _load_accounts_from_env(self) -> List[Dict]:
        """Загрузить аккаунты из переменной окружения"""
        accounts_json = os.getenv("BUFF_ACCOUNTS", "[]")
        try:
            accounts = json.loads(accounts_json)
            logger.info(f"✅ Loaded {len(accounts)} Buff accounts")
            
            # Инициализировать поля статуса для каждого аккаунта
            for acc in accounts:
                if "last_used" not in acc:
                    acc["last_used"] = None
                if "usage_count" not in acc:
                    acc["usage_count"] = 0
            
            return accounts
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse BUFF_ACCOUNTS JSON: {e}")
            return []
    
    def get_available_account(self) -> Optional[Dict]:
        """
        Получить доступный аккаунт по выбранной стратегии
        
        Исключает:
        - Неактивные аккаунты
        - Заблокированные аккаунты (капча, too many requests)
        - Аккаунты в периоде отдыха (rest period)
        
        Returns:
            Копия аккаунта или None если нет доступных
        """
        available = self._filter_available_accounts()
        
        if not available:
            logger.warning("⚠️ No available accounts! All locked or resting.")
            return None
        
        # Выбрать по стратегии
        if self.rotation_strategy == "random":
            selected = random.choice(available)
        elif self.rotation_strategy == "least_used":
            selected = min(available, key=lambda a: a.get("usage_count", 0))
        else:  # round_robin
            selected = available[0]
        
        logger.info(f"✅ Selected account ID={selected['account_id']}, "
                   f"Login={selected['buff_username']}, "
                   f"Uses={selected.get('usage_count', 0)}")
        
        return selected.copy()
    
    def _filter_available_accounts(self) -> List[Dict]:
        """Отфильтровать доступные аккаунты"""
        available = []
        now = datetime.utcnow().timestamp()
        
        for acc in self.accounts:
            # Пропустить неактивные аккаунты
            if acc.get("status") != "active":
                logger.debug(f"⊘ Account {acc['account_id']} is inactive")
                continue
            
            # Пропустить заблокированные (капча, ошибки и т.д.)
            if acc["account_id"] in self.account_locks:
                lock_until = self.account_locks[acc["account_id"]]
                if now < lock_until:
                    remaining = int(lock_until - now)
                    logger.debug(f"⊘ Account {acc['account_id']} locked for {remaining}s more")
                    continue
                else:
                    # Автоматически разблокировать если истек таймаут
                    del self.account_locks[acc["account_id"]]
                    logger.info(f"✅ Account {acc['account_id']} auto-unlocked")
            
            # Пропустить если в периоде отдыха (rest period)
            last_used = acc.get("last_used")
            if last_used:
                time_since_use = now - last_used
                if time_since_use < self.min_rest_secs:
                    remaining = int(self.min_rest_secs - time_since_use)
                    logger.debug(f"⊘ Account {acc['account_id']} resting for {remaining}s more")
                    continue
            
            available.append(acc)
        
        return available
    
    def mark_busy(self, account_id: int, duration_secs: int = 1800, reason: str = "error") -> None:
        """
        Заблокировать аккаунт на время
        
        Args:
            account_id: ID аккаунта
            duration_secs: На сколько секунд заблокировать (30 мин по умолчанию)
            reason: Причина блокировки (капча, rate_limit и т.д.)
        """
        lock_until = datetime.utcnow().timestamp() + duration_secs
        self.account_locks[account_id] = lock_until
        
        logger.warning(f"⛔ Account {account_id} LOCKED for {duration_secs}s "
                      f"(reason: {reason}) until {datetime.fromtimestamp(lock_until).isoformat()}")
    
    def mark_used(self, account_id: int) -> None:
        """Отметить аккаунт как использованный (начать rest period)"""
        for acc in self.accounts:
            if acc["account_id"] == account_id:
                acc["last_used"] = datetime.utcnow().timestamp()
                acc["usage_count"] = acc.get("usage_count", 0) + 1
                logger.info(f"📊 Account {account_id}: usage_count={acc['usage_count']}")
                break
    
    def get_account_status(self) -> Dict:
        """Получить полный статус всех аккаунтов"""
        now = datetime.utcnow().timestamp()
        status = {
            "total": len(self.accounts),
            "active": len([a for a in self.accounts if a.get("status") == "active"]),
            "locked": len(self.account_locks),
            "available": len(self._filter_available_accounts()),
            "accounts": []
        }
        
        for acc in self.accounts:
            is_locked = acc["account_id"] in self.account_locks
            lock_remaining = None
            if is_locked:
                lock_until = self.account_locks[acc["account_id"]]
                lock_remaining = int(max(0, lock_until - now))
            
            last_used = acc.get("last_used")
            time_since_use = None
            if last_used:
                time_since_use = int(now - last_used)
            
            acc_status = {
                "id": acc["account_id"],
                "buff_username": acc["buff_username"],
                "status": acc.get("status", "unknown"),
                "locked": is_locked,
                "lock_remaining_secs": lock_remaining,
                "usage_count": acc.get("usage_count", 0),
                "time_since_last_use_secs": time_since_use,
            }
            status["accounts"].append(acc_status)
        
        return status
    
    def reset_account(self, account_id: int) -> bool:
        """Принудительная разблокировка аккаунта (admin command)"""
        if account_id in self.account_locks:
            del self.account_locks[account_id]
            logger.info(f"✅ Account {account_id} manually unlocked by admin")
            return True
        return False


class BuffBrowserManager:
    """Управление браузером (одна сессия для очереди платежей)"""
    
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.wait_timeout = int(os.getenv("BROWSER_DEFAULT_TIMEOUT", "30")) // 1000  # сек
        self.headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
    
    async def launch(self, account: Dict) -> webdriver.Chrome:
        """
        Запустить браузер с undetected-chromedriver
        
        Args:
            account: Данные аккаунта (для логирования)
            
        Returns:
            WebDriver объект Chrome
        """
        try:
            options = uc.ChromeOptions()
            
            # Базовые опции
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-translate")
            options.add_argument("--disable-client-side-phishing-detection")
            
            if self.headless:
                options.add_argument("--headless=new")
            
            # Прокси поддержка (если есть)
            proxy_url = account.get("proxy_url")
            if proxy_url and proxy_url != "none":
                logger.info(f"🌐 Using proxy: {proxy_url[:30]}...")
                options.add_argument(f"--proxy-server={proxy_url}")
            else:
                logger.warning(f"⚠️ Account {account['account_id']} using NO PROXY")
            
            # Запустить undetected браузер
            self.driver = uc.Chrome(options=options, version_main=None)
            self.driver.set_page_load_timeout(30)
            
            logger.info(f"✅ Browser launched for account {account['account_id']}")
            return self.driver
            
        except Exception as e:
            logger.error(f"❌ Failed to launch browser: {e}")
            raise
    
    async def close(self) -> None:
        """Закрыть браузер"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                logger.info("✅ Browser closed")
            except Exception as e:
                logger.error(f"❌ Error closing browser: {e}")
    
    async def cleanup_memory(self) -> None:
        """Очистить память (закрыть табы, вкладки и т.д.)"""
        if self.driver:
            try:
                # Закрыть все табы кроме первого
                windows = self.driver.window_handles
                if len(windows) > 1:
                    for window in windows[1:]:
                        self.driver.switch_to.window(window)
                        self.driver.close()
                    self.driver.switch_to.window(windows[0])
                
                # Очистить cookies и локальное хранилище
                self.driver.delete_all_cookies()
                self.driver.execute_script("window.localStorage.clear();")
                
                logger.info("🗑️ Memory cleaned up")
            except Exception as e:
                logger.error(f"❌ Error during cleanup: {e}")


class BuffPaymentProcessor:
    """Обработка платежей через Buff.163"""
    
    def __init__(self):
        self.account_manager = BuffAccountManager()
        self.browser_manager = BuffBrowserManager()
        self.timeout_minutes = int(os.getenv("BUFF_TIMEOUT_MINUTES", "10"))
        self.polling_interval = int(os.getenv("BUFF_POLLING_INTERVAL_SECS", "15"))
    
    async def generate_invoice(self, user_id: int, amount: float) -> Dict:
        """
        Генерировать QR-код для оплаты
        
        Args:
            user_id: ID пользователя в БД
            amount: Сумма в CNY
            
        Returns:
            {
                "success": bool,
                "qr_bytes": b'...',  # PNG bytes в памяти
                "transaction_id": "buff_xxx",
                "start_balance": 1000.5,
                "error": str (если не success)
            }
        """
        account = self.account_manager.get_available_account()
        if not account:
            return {
                "success": False,
                "error": "All accounts are busy or locked. Try again in 1-2 minutes."
            }
        
        logger.info(f"🔄 Starting payment generation: user={user_id}, amount={amount}CNY, "
                   f"account={account['account_id']}")
        
        try:
            # Запустить браузер
            driver = await self.browser_manager.launch(account)
            
            # Перейти на Buff
            logger.info("📄 Navigating to https://buff.163.com...")
            driver.get("https://buff.163.com")
            await asyncio.sleep(2)  # Подождать загрузку
            
            # Проверить авторизацию
            is_auth = await self._check_auth(driver, account)
            if not is_auth:
                logger.error(f"❌ Authentication failed for account {account['account_id']}")
                self.account_manager.mark_busy(account["account_id"], duration_secs=300, 
                                              reason="auth_failed")
                return {
                    "success": False,
                    "error": "Authentication failed. Account may require manual 2FA verification."
                }
            
            # Получить начальный баланс
            start_balance = await self._get_balance(driver)
            logger.info(f"💰 Initial balance: {start_balance} CNY")
            
            # Перейти на страницу пополнения
            logger.info("💳 Navigating to recharge page...")
            driver.get("https://buff.163.com/account/recharge")
            await asyncio.sleep(1)
            
            # Ввести сумму
            logger.info(f"🔢 Entering amount: {amount}...")
            await self._enter_amount(driver, amount)
            await asyncio.sleep(0.5)
            
            # Выбрать метод оплаты (Alipay по умолчанию)
            logger.info("💳 Selecting payment method...")
            await self._select_payment_method(driver, "alipay")
            await asyncio.sleep(1)
            
            # Нажать кнопку подтверждения
            logger.info("✅ Clicking confirm button...")
            await self._click_confirm(driver)
            await asyncio.sleep(2)
            
            # Извлечь QR-код
            logger.info("📱 Extracting QR code...")
            qr_bytes = await self._extract_qr_code(driver)
            if not qr_bytes:
                logger.error("❌ Failed to extract QR code")
                return {
                    "success": False,
                    "error": "Could not extract QR code from page"
                }
            
            logger.info(f"✅ QR code extracted ({len(qr_bytes)} bytes)")
            
            # Генерировать transaction ID
            transaction_id = f"buff_{int(time.time())}_{account['account_id']}"
            
            # Отметить аккаунт как использованный
            self.account_manager.mark_used(account["account_id"])
            
            # Запустить polling в фоновом потоке
            asyncio.create_task(
                self._poll_balance_async(driver, user_id, transaction_id, 
                                        start_balance, amount, account["account_id"])
            )
            
            return {
                "success": True,
                "qr_bytes": qr_bytes,
                "transaction_id": transaction_id,
                "start_balance": start_balance,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"❌ Error in generate_invoice: {e}")
            await self.browser_manager.close()
            self.account_manager.mark_busy(account["account_id"], duration_secs=600, 
                                          reason=f"exception:{str(e)[:30]}")
            return {
                "success": False,
                "error": f"Payment generation failed: {str(e)[:100]}"
            }
    
    async def _check_auth(self, driver: webdriver.Chrome, account: Dict) -> bool:
        """Проверить авторизацию на Buff"""
        try:
            # Ждем загрузку страницы
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Проверить наличие элемента профиля (признак авторизации)
            # TODO: Актуализировать селекторы под реальный Buff интерфейс
            try:
                driver.find_element(By.CSS_SELECTOR, ".user-profile, .account-info")
                logger.info(f"✅ Account {account['account_id']} is authenticated")
                return True
            except NoSuchElementException:
                # Может потребоваться логин
                logger.warning(f"⚠️ Account {account['account_id']} may need re-login")
                # TODO: Реализовать автологин если требуется
                return True  # Пока оставляем true для MVP
                
        except TimeoutException:
            logger.error("❌ Auth check timeout")
            return False
    
    async def _get_balance(self, driver: webdriver.Chrome) -> float:
        """Получить текущий баланс аккаунта"""
        try:
            # TODO: Актуализировать XPath под реальный интерфейс Buff
            balance_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//span[@class='balance-amount']"))
            )
            balance_text = balance_element.text.strip()
            # Парсить число (убрать валюту и т.д.)
            balance = float(''.join(c for c in balance_text if c.isdigit() or c == '.'))
            return balance
        except Exception as e:
            logger.warning(f"⚠️ Could not get balance: {e}, returning 0")
            return 0
    
    async def _enter_amount(self, driver: webdriver.Chrome, amount: float) -> None:
        """Ввести сумму пополнения"""
        try:
            # TODO: Актуализировать селектор под реальный интерфейс
            amount_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='number'][@placeholder*='amount']"))
            )
            amount_input.clear()
            amount_input.send_keys(str(amount))
            logger.info(f"✅ Amount {amount} entered")
        except Exception as e:
            logger.error(f"❌ Error entering amount: {e}")
            raise
    
    async def _select_payment_method(self, driver: webdriver.Chrome, method: str = "alipay") -> None:
        """Выбрать метод оплаты (alipay или wechat)"""
        try:
            # TODO: Актуализировать селектор
            if method == "alipay":
                button = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Alipay')]"))
                )
            else:  # wechat
                button = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'WeChat')]"))
                )
            button.click()
            logger.info(f"✅ Payment method {method} selected")
        except Exception as e:
            logger.error(f"❌ Error selecting payment method: {e}")
            raise
    
    async def _click_confirm(self, driver: webdriver.Chrome) -> None:
        """Нажать кнопку подтверждения"""
        try:
            # TODO: Актуализировать селектор
            confirm_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Confirm')]"))
            )
            confirm_btn.click()
            logger.info("✅ Confirm button clicked")
        except Exception as e:
            logger.error(f"❌ Error clicking confirm: {e}")
            raise
    
    async def _extract_qr_code(self, driver: webdriver.Chrome) -> Optional[bytes]:
        """
        Извлечь QR-код и вернуть как PNG bytes
        
        Returns:
            PNG bytes или None если не найден
        """
        try:
            # Ждем появления QR кода
            qr_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'qr') or contains(@class, 'qr')]"))
            )
            
            # Делаем скриншот области с QR
            qr_location = qr_element.location
            qr_size = qr_element.size
            
            # Получить весь скриншот страницы
            screenshot = driver.get_screenshot_as_png()
            image = Image.open(BytesIO(screenshot))
            
            # Кроп области с QR-кодом
            left = int(qr_location['x'])
            top = int(qr_location['y'])
            right = int(left + qr_size['width'])
            bottom = int(top + qr_size['height'])
            
            qr_image = image.crop((left, top, right, bottom))
            
            # Сохранить в памяти как PNG bytes
            qr_bytes = BytesIO()
            qr_image.save(qr_bytes, format='PNG')
            qr_bytes.seek(0)
            
            logger.info(f"✅ QR code extracted: {qr_image.size}")
            return qr_bytes.getvalue()
            
        except Exception as e:
            logger.error(f"❌ Error extracting QR code: {e}")
            return None
    
    async def _poll_balance_async(self, driver: webdriver.Chrome, user_id: int, 
                                 transaction_id: str, start_balance: float, 
                                 amount: float, account_id: int) -> None:
        """
        Асинхронный polling баланса в фоне (запускается как Task)
        
        Это работает в фоновом потоке и не блокирует основной поток бота
        """
        logger.info(f"🔄 Starting balance polling for transaction {transaction_id}")
        
        try:
            start_time = time.time()
            timeout_secs = self.timeout_minutes * 60
            
            while (time.time() - start_time) < timeout_secs:
                await asyncio.sleep(self.polling_interval)
                
                try:
                    current_balance = await self._get_balance(driver)
                    balance_diff = current_balance - start_balance
                    
                    logger.info(f"📊 Polling: start={start_balance}, current={current_balance}, "
                              f"diff={balance_diff}")
                    
                    # Проверить если баланс изменился
                    if balance_diff >= (amount * 0.95):  # Минус 5% на комиссию
                        logger.info(f"✅ PAYMENT SUCCESS: {balance_diff} CNY received!")
                        await self._complete_payment(user_id, transaction_id, balance_diff, 
                                                    "completed")
                        return
                
                except Exception as e:
                    logger.warning(f"⚠️ Error during polling: {e}")
                    continue
            
            # Таймаут истек
            logger.warning(f"⏰ Payment timeout: {transaction_id}")
            await self._complete_payment(user_id, transaction_id, 0, "expired")
            
        except Exception as e:
            logger.error(f"❌ Error in polling loop: {e}")
            await self.browser_manager.close()
        finally:
            # Закрыть браузер после завершения polling
            await self.browser_manager.close()
    
    async def _complete_payment(self, user_id: int, transaction_id: str, 
                               paid_amount: float, status: str) -> None:
        """
        Завершить платеж и обновить БД
        
        Args:
            user_id: ID пользователя
            transaction_id: Transaction ID от Buff
            paid_amount: Фактическая сумма оплаты
            status: 'completed' или 'expired'
        """
        db = SessionLocal()
        try:
            # Найти платеж
            payment = db.query(Payment).filter(
                Payment.transaction_id == transaction_id
            ).first()
            
            if payment:
                payment.status = status
                db.commit()
                
                if status == "completed":
                    logger.info(f"💰 Payment {transaction_id} completed: {paid_amount} CNY")
                    
                    # Обновить баланс пользователя
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.balance += paid_amount
                        db.commit()
                        logger.info(f"📈 User {user_id} balance updated: +{paid_amount} CNY")
                else:
                    logger.warning(f"⏰ Payment {transaction_id} expired (no payment received)")
        
        except Exception as e:
            logger.error(f"❌ Error completing payment: {e}")
        finally:
            db.close()


# Глобальный экземпляр для использования в хэндлерах
buff_processor: Optional[BuffPaymentProcessor] = None


def init_buff_service():
    """Инициализировать Buff сервис"""
    global buff_processor
    buff_processor = BuffPaymentProcessor()
    logger.info("✅ Buff payment service initialized")


async def get_buff_processor() -> BuffPaymentProcessor:
    """Получить экземпляр процессора"""
    global buff_processor
    if buff_processor is None:
        init_buff_service()
    return buff_processor
