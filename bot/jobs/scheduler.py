import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application
from bot.services.subscription_service import SubscriptionService
from bot.services.notification_service import NotificationService
from bot.services.payment_service import PaymentService
from bot.services.reporting_service import ReportingService
from bot.config import ADMIN_ID

logger = logging.getLogger(__name__)

# Глобальная переменная для отслеживания последнего ID устройства в отчете о 20 устройств
_last_devices_batch_report_id = 0


async def daily_charge_job(app: Application, notification_service: NotificationService) -> None:
    """
    Ежедневное задание: списание за подписки
    Запускается каждый день в 00:00 UTC
    
    Новая логика: вместо списания за каждую подписку отдельно,
    списываем за каждого пользователя со всеми его активными устройствами
    Стоимость = кол-во активных устройств × VPN_PRICE_PER_DAY
    
    Если баланс недостаточен, дается grace day (раз в 2 недели) с уведомлением.
    """
    logger.info("🔄 Запуск ежедневного списания...")
    
    # Получаем все активных пользователей
    db = None
    try:
        from database.models import SessionLocal, User
        db = SessionLocal()
        
        users = db.query(User).filter(User.is_active == True).all()
        
        for user in users:
            result = SubscriptionService.charge_daily_for_user(user.id)
            
            # Если был выдан grace day, отправляем уведомление
            if result.get("grace_day_given"):
                await notification_service.send_grace_day_notification(
                    user.id,
                    result.get("active_devices", 0),
                    result.get("daily_cost", 0)
                )
            # Если подписка завершена (баланс исчерпан), отправляем уведомление
            elif result.get("subscription_ended"):
                await notification_service.send_subscription_ended_notification(user.id)
        
        logger.info(f"✅ Обработано пользователей: {len(users)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при списании: {e}")
    finally:
        if db:
            db.close()


async def check_expiring_subscriptions_job(app: Application, notification_service: NotificationService) -> None:
    """
    Проверка пользователей с низким балансом (осталось ≤ 3 дней)
    Отправляет напоминание пополнить баланс
    Запускается каждый день в 12:00 UTC
    """
    logger.info("⏰ Проверка балансов, которые на исходе...")
    
    try:
        low_balance_users = SubscriptionService.get_users_with_low_balance_soon(days_threshold=3)
        
        for user_id, current_balance, days_remaining, active_devices in low_balance_users:
            await notification_service.send_low_balance_notification(
                user_id,
                current_balance,
                days_remaining,
                active_devices
            )
        
        logger.info(f"✅ Отправлено уведомлений: {len(low_balance_users)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке балансов: {e}")


async def check_low_balance_job(app: Application, notification_service: NotificationService) -> None:
    """
    ❌ DEPRECATED: Объединена с check_expiring_subscriptions_job()
    
    Эта задача больше не нужна, так как проверка низкого баланса теперь идет в check_expiring_subscriptions_job()
    """
    logger.warning("⚠️ check_low_balance_job() вызван, но задача больше не используется")


async def check_pending_payments_job(app: Application) -> None:
    """
    Проверка ожидающих платежей (для polling-based интеграции с Yookassa)
    Запускается каждые 15 минут
    """
    try:
        processed = PaymentService.check_pending_payments()
        if processed > 0:
            logger.info(f"✅ Автоматически обработано платежей: {processed}")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке платежей: {e}")


async def hourly_report_job(app: Application) -> None:
    """
    Почасовой отчет по состоянию сервиса
    Запускается каждый час в начале часа (ХХ:00) по МСК
    
    Отправляет админу:
    - Количество активных пользователей и устройств
    - Трафик и ошибки
    - Статус сервиса (online/offline)
    """
    if not ADMIN_ID:
        logger.warning("⚠️ ADMIN_ID не установлен, пропускаю отправку почасового отчета")
        return
    
    try:
        logger.info("📊 Создаю почасовой отчет...")
        report = ReportingService.get_hourly_report()
        
        await app.bot.send_message(
            chat_id=ADMIN_ID,
            text=report,
            parse_mode="HTML"
        )
        
        logger.info("✅ Почасовой отчет отправлен администратору")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке почасового отчета: {e}")


async def daily_detailed_report_job(app: Application) -> None:
    """
    Подробный суточный отчет по работе сервиса
    Запускается каждый день в 00:20 МСК (21:20 UTC)
    
    Отправляет админу:
    - Общую статистику (новые пользователи, новые устройства, доход)
    - Топ 10 пользователей по расходам
    - Статистику платежей
    - Состояние сервера и Marzban
    - Проблемы синхронизации
    """
    if not ADMIN_ID:
        logger.warning("⚠️ ADMIN_ID не установлен, пропускаю отправку суточного отчета")
        return
    
    try:
        logger.info("📈 Создаю подробный суточный отчет...")
        report = ReportingService.get_daily_detailed_report()
        
        await app.bot.send_message(
            chat_id=ADMIN_ID,
            text=report,
            parse_mode="HTML"
        )
        
        logger.info("✅ Подробный суточный отчет отправлен администратору")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке суточного отчета: {e}")


async def check_new_devices_batch_job(app: Application) -> None:
    """
    Проверка на создание 20 новых устройств
    Если создано 20 устройств со времени последнего отчета - отправляет отчет админу
    Запускается каждые 5 минут
    """
    global _last_devices_batch_report_id
    
    if not ADMIN_ID:
        return
    
    try:
        from database.models import SessionLocal, Device
        
        db = SessionLocal()
        try:
            # Получаем количество устройств, созданных после последнего отчета
            new_devices = db.query(Device).filter(
                Device.id > _last_devices_batch_report_id
            ).order_by(Device.created_at).all()
            
            # Если накопилось 20 или больше устройств
            if len(new_devices) >= 20:
                # Берем первые 20
                devices_to_report = new_devices[:20]
                device_ids = [d.id for d in devices_to_report]
                
                # Создаем и отправляем отчет
                report = ReportingService.get_devices_batch_report(device_ids)
                
                await app.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=report,
                    parse_mode="HTML"
                )
                
                # Обновляем переменную отслеживания
                _last_devices_batch_report_id = max([d.id for d in devices_to_report])
                
                logger.info(f"✅ Отчет о 20 новых устройствах отправлен администратору (ID: {_last_devices_batch_report_id})")
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке новых устройств: {e}")


def setup_scheduler(app: Application, notification_service: NotificationService):
    """Настройка планировщика задач"""
    
    scheduler = AsyncIOScheduler()
    
    # Ежедневное списание в 00:00 UTC
    scheduler.add_job(
        daily_charge_job,
        'cron',
        hour=0,
        minute=0,
        args=[app, notification_service],
        id='daily_charge'
    )
    
    # Проверка низких балансов в 12:00 UTC (объединена с проверкой истекающих)
    scheduler.add_job(
        check_expiring_subscriptions_job,
        'cron',
        hour=12,
        minute=0,
        args=[app, notification_service],
        id='check_expiring'
    )
    
    # Проверка ожидающих платежей каждые 15 минут
    scheduler.add_job(
        check_pending_payments_job,
        'interval',
        minutes=15,
        args=[app],
        id='check_pending_payments'
    )
    
    # ========== НОВЫЕ ЗАДАЧИ ДЛЯ ОТЧЕТОВ ==========
    
    # Почасовой отчет в начале каждого часа (по МСК)
    scheduler.add_job(
        hourly_report_job,
        'cron',
        hour='*',
        minute=0,
        timezone='Europe/Moscow',
        args=[app],
        id='hourly_report'
    )
    
    # Подробный суточный отчет в 00:20 МСК (21:20 UTC)
    scheduler.add_job(
        daily_detailed_report_job,
        'cron',
        hour=21,
        minute=20,
        timezone='UTC',
        args=[app],
        id='daily_detailed_report'
    )
    
    # Проверка на создание 20 новых устройств каждые 5 минут
    scheduler.add_job(
        check_new_devices_batch_job,
        'interval',
        minutes=5,
        args=[app],
        id='check_new_devices_batch'
    )
    
    scheduler.start()
    logger.info("✅ Планировщик задач запущен")
    logger.info("📊 Включены задачи отчетов:")
    logger.info("  • Почасовой отчет: каждый час в хх:00 МСК")
    logger.info("  • Суточный отчет: каждый день в 00:20 МСК")
    logger.info("  • Отчет о 20 устройств: каждые 5 минут")
    
    return scheduler
