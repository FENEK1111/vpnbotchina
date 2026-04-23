import logging
from telegram import Bot
from database.models import SessionLocal, Notification, User, Device, Subscription
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис отправки уведомлений"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
    
    async def send_low_balance_notification(self, user_id: int, current_balance: float, days_remaining: int, active_devices: int):
        """
        Отправить уведомление о низком балансе (осталось ≤ 3 дней)
        
        Args:
            user_id: ID пользователя
            current_balance: текущий баланс в рублях
            days_remaining: сколько дней осталось
            active_devices: количество активных устройств
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user or not user.is_active:
                return False
            
            message = (
                f"⏰ <b>Баланс подходит к концу!</b>\n\n"
                f"Текущий баланс: <b>{current_balance:.2f}¥</b>\n"
                f"Осталось дней: <b>{days_remaining}</b>\n"
                f"Активных устройств: <b>{active_devices}</b>\n\n"
                f"Пополните баланс в меню <b>Мой баланс</b>, чтобы не потерять доступ к VPN!"
            )
            
            try:
                await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                
                notification = Notification(
                    user_id=user_id,
                    notification_type="low_balance"
                )
                db.add(notification)
                db.commit()
                
                logger.info(f"✅ Уведомление низкого баланса отправлено: user={user_id}, balance={current_balance:.2f}¥, дней={days_remaining}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления: {e}")
                return False
                
        finally:
            db.close()
    
    async def send_grace_day_notification(self, user_id: int, active_devices: int, daily_cost: float):
        """
        Отправить уведомление о предоставлении grace day
        Grace day дается раз в 2 недели, когда баланс недостаточен
        
        Args:
            user_id: ID пользователя
            active_devices: количество активных устройств
            daily_cost: стоимость одного дня
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user or not user.is_active:
                return False
            
            message = (
                f"🎁 <b>Получен бесплатный день доступа!</b>\n\n"
                f"Ваш баланс близок к нулю (<b>{user.balance:.2f}¥</b>), но мы продлили вам доступ на <b>1 день</b> ✨\n\n"
                f"Активных устройств: <b>{active_devices}</b>\n"
                f"Стоимость дня: <b>{daily_cost:.2f}¥</b>\n\n"
                f"<b>⚠️ Это предложение доступно раз в 2 недели.</b>\n\n"
                f"Пожалуйста, пополните баланс прямо сейчас, чтобы не потерять доступ к сервису! 👇"
            )
            
            try:
                # В будущем здесь можно добавить кнопки пополнения баланса
                await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                
                notification = Notification(
                    user_id=user_id,
                    notification_type="grace_day"
                )
                db.add(notification)
                db.commit()
                
                logger.info(f"✅ Grace day уведомление отправлено: user={user_id}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки grace day уведомления: {e}")
                return False
                
        finally:
            db.close()
    
    async def send_subscription_ended_notification(self, user_id: int):
        """
        Отправить уведомление об окончании подписки (баланс исчерпан)
        
        Args:
            user_id: ID пользователя
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user or not user.is_active:
                return False
            
            message = (
                f"❌ <b>К сожалению, ваша подписка прекращена</b>\n\n"
                f"Чтобы возобновить работу VPN пополните баланс\n"
                f"Ограничения будут автоматически сняты\n"
                f"Ваши устройства будут работать снова\n\n"
                f"Спасибо, что пользуетесь нашим сервисом! 🙏"
            )
            
            try:
                await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                
                notification = Notification(
                    user_id=user_id,
                    notification_type="subscription_ended"
                )
                db.add(notification)
                db.commit()
                
                logger.info(f"✅ Уведомление об окончании подписки отправлено: user={user_id}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления об окончании подписки: {e}")
                return False
                
        finally:
            db.close()
