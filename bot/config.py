import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в .env файле")

# Database URL
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./vpn_bot_china.db')

# Marzban API
MARZBAN_URL = os.getenv('MARZBAN_URL', 'http://localhost:8000')
MARZBAN_ADMIN_TOKEN = os.getenv('MARZBAN_ADMIN_TOKEN', '')

# VPN Settings (China Edition - CNY)
VPN_PRICE_PER_MONTH = 18.0  # 18 yuan per month per device
VPN_PRICE_PER_DAY = 0.60  # ≈ 0.60 yuan per day per device (18 / 30)
VPN_NOTIFICATION_DAYS = 3  # Notify 3 days before subscription expires
VPN_LOW_BALANCE_DAYS = 3  # Reserve days for low balance check
VPN_MAX_DEVICES = 6  # max devices per user
VPN_LOCATION = 'China'  # location

# Alipay Payment (Instructions only - no direct API integration)
ALIPAY_ENABLED = os.getenv('ALIPAY_ENABLED', 'True').lower() == 'true'
ALIPAY_AMOUNT_OPTIONS = [int(x.strip()) for x in os.getenv('ALIPAY_AMOUNT_OPTIONS', '10,20,50,100,200').split(',')]
ALIPAY_PAYMENT_METHOD = 'manual_instruction'  # Инструкции, а не автоматические платежи

# Режим отладки
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# Администратор (для команд отладки и отчетов)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0')) if os.getenv('ADMIN_ID', '0') and os.getenv('ADMIN_ID', '0') != '0' else None

# Buff.163 Account Credentials (для отправки админу при генерировании QR)
BUFF_ACCOUNT_CREDENTIALS = {
    1: {"login": "vffkpnivhu746", "password": "I61B8A06x4P"},
    2: {"login": "qhmk00gtmsvb", "password": "M4fVrX2zP4nPMeg"},
    3: {"login": "dgxm36jjokkivms", "password": "LvDILzzOD8LjtVrLtrV"},
    4: {"login": "hrvlpshw561990", "password": "AGeJsijTFayIxxIc"},
    5: {"login": "glicyqxu495077", "password": "IUGZgGv4kDP6veS8N24"},
    6: {"login": "vkgooduq78q", "password": "OJDV4JGUZJm"},
    7: {"login": "pvjvagan14uygh", "password": "U0apiFyyri3Mnb0kqa3"},
    8: {"login": "lxuxqgox9768", "password": "fGH3jJIcb8we1hbzHFNa"},
    9: {"login": "dlthoxji7447", "password": "97W3IfPSnRGUV"},
    10: {"login": "ebgvuebu28go", "password": "Ru2s7kXGRaXie3BV6L"},
}

