import logging
from datetime import datetime, timedelta
from database.models import SessionLocal, Subscription, Device, User
from bot.config import VPN_PRICE_PER_DAY, VPN_LOW_BALANCE_DAYS
from bot.services.vpn_service import marzban_service

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Сервис управления подписками"""
    
    @staticmethod
    def create_subscription(user_id: int) -> Subscription:
        """
        Создать ОДНУ ОБЩУЮ подписку для пользователя (без привязки к конкретному устройству)
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Subscription объект
        """
        db = SessionLocal()
        try:
            # Проверяем что подписка еще не создана
            existing = db.query(Subscription).filter(Subscription.user_id == user_id).first()
            if existing:
                logger.info(f"ℹ️ Подписка уже существует для user={user_id}")
                return existing
            
            # Создаем общую подписку БЕЗ device_id
            subscription = Subscription(
                user_id=user_id,
                device_id=None,  # общая подписка для всех устройств
                balance=0,
                days_remaining=0,
                expires_at=None,
                is_active=True
            )
            
            db.add(subscription)
            db.commit()
            db.refresh(subscription)
            
            logger.info(f"✅ Общая подписка создана: user={user_id}")
            return subscription
            
        finally:
            db.close()
    
    @staticmethod
    def add_balance(user_id: int, amount: float) -> bool:
        """
        Добавить баланс к пользователю (общей подписке)
        
        Args:
            user_id: ID пользователя (не subscription_id!)
            amount: сумма в рублях
            
        Returns:
            True если успешно, False если пользователь не найден
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user:
                logger.error(f"❌ Пользователь {user_id} не найден")
                return False
            
            user.balance += amount
            db.commit()
            logger.info(f"✅ Баланс добавлен: user={user_id}, сумма={amount}¥, новый баланс={user.balance:.2f}¥")
            return True
            
        finally:
            db.close()
    
    @staticmethod
    def reactivate_deactivated_devices(user_id: int) -> int:
        """
        Реактивировать все деактивированные устройства пользователя
        Вызывается при пополнении баланса
        Снимает ограничение трафика (устанавливает 0 - без ограничений)
        
        Args:
            user_id: ID пользователя
        
        Returns:
            int: Количество реактивированных устройств
        """
        db = SessionLocal()
        try:
            from bot.services.vpn_service import MarzbanService
            
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user or user.balance <= 0:
                logger.warning(f"⚠️ Не могу реактивировать устройства для user={user_id}: баланс недостаточен")
                return 0
            
            # Ищем все деактивированные устройства
            inactive_devices = db.query(Device).filter(
                Device.user_id == user_id,
                Device.is_active == False
            ).all()
            
            marzban = MarzbanService()
            reactivated_count = 0
            
            for device in inactive_devices:
                try:
                    # Снимаем ограничение трафика (устанавливаем на 0 = без ограничений)
                    marzban.set_data_limit(device.marzban_username, 0)
                    device.is_active = True
                    reactivated_count += 1
                    logger.info(f"♻️ Устройство реактивировано (лимит трафика снят): {device.name} -> {device.marzban_username} (user={user_id})")
                except Exception as e:
                    logger.error(f"❌ Не удалось снять ограничение трафика для {device.marzban_username}: {e}")
                    # Все равно отмечаем как активное в БД
                    device.is_active = True
                    reactivated_count += 1
            
            # Реактивируем подписки
            subscriptions = db.query(Subscription).filter(
                Subscription.user_id == user_id,
                Subscription.is_active == False
            ).all()
            
            for sub in subscriptions:
                sub.is_active = True
            
            db.commit()
            logger.info(f"✅ Реактивировано устройств: {reactivated_count} для user={user_id}")
            return reactivated_count
            
        except Exception as e:
            logger.error(f"❌ Ошибка при реактивации устройств для user={user_id}: {e}")
            return 0
        finally:
            db.close()
    
    @staticmethod
    def charge_daily(subscription_id: int) -> bool:
        """
        ❌ DEPRECATED: Используйте charge_daily_for_user() вместо этого
        
        Этот метод больше не используется, так как подписка теперь общая для всех устройств пользователя.
        Списание происходит через charge_daily_for_user(user_id).
        
        Returns:
            False - всегда, так как метод не используется
        """
        logger.warning(f"⚠️ Вызван deprecated метод charge_daily({subscription_id}). Используйте charge_daily_for_user() вместо этого.")
        return False
    
    @staticmethod
    def charge_daily_for_user(user_id: int) -> dict:
        """
        Ежедневное списание для пользователя за все активные устройства
        Стоимость = кол-во_активных_устройств × VPN_PRICE_PER_DAY
        
        Логика grace day:
        - Если баланс < daily_cost И устройств > 0:
          - Проверяем: был ли grace day в последние 14 дней?
          - Если нет → предоставляем grace day (баланс не списывается)
          - Отправляем уведомление и просим пополнить баланс
          - Если да → отключаем все устройства (баланс недостаточен)
        
        Args:
            user_id: ID пользователя
        
        Returns:
            dict с ключами:
            - success (bool): успешно ли выполнено списание
            - grace_day_given (bool): был ли выдан grace day
            - active_devices (int): количество активных устройств
            - daily_cost (float): стоимость одного дня
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user or not user.is_active:
                return {"success": False, "grace_day_given": False, "active_devices": 0, "daily_cost": 0}
            
            # Подсчитываем активные устройства
            active_devices = db.query(Device).filter(
                Device.user_id == user_id,
                Device.is_active == True
            ).count()
            
            # Если устройств нет, списание не требуется
            if active_devices == 0:
                logger.info(f"ℹ️ Пользователь {user_id} не имеет активных устройств, списание пропущено")
                return {"success": True, "grace_day_given": False, "active_devices": 0, "daily_cost": 0}
            
            # Вычисляем стоимость за день
            daily_cost = VPN_PRICE_PER_DAY * active_devices
            
            # Проверяем баланс
            if user.balance >= daily_cost:
                user.balance -= daily_cost
                db.commit()
                logger.info(f"✅ Списание: user={user_id}, устройств={active_devices}, стоимость={daily_cost}¥")
                return {"success": True, "grace_day_given": False, "active_devices": active_devices, "daily_cost": daily_cost}
            else:
                # Баланс недостаточен - проверяем grace day
                now = datetime.utcnow()
                can_use_grace_day = False
                
                if user.last_grace_day_date is None:
                    # Никогда не использовал grace day
                    can_use_grace_day = True
                else:
                    # Проверяем: прошло ли 14 дней с последнего grace day
                    days_since_grace = (now - user.last_grace_day_date).days
                    if days_since_grace >= 14:
                        can_use_grace_day = True
                
                if can_use_grace_day:
                    # Предоставляем grace day
                    user.last_grace_day_date = now
                    db.commit()
                    logger.info(f"🎁 Grace Day выдан: user={user_id}, баланс={user.balance}¥, требуется={daily_cost}¥")
                    return {"success": True, "grace_day_given": True, "active_devices": active_devices, "daily_cost": daily_cost}
                else:
                    # Grace day уже использован недавно - устанавливаем очень малый лимит трафика (0,001 GB)
                    from bot.services.vpn_service import MarzbanService
                    
                    marzban = MarzbanService()
                    devices = db.query(Device).filter(
                        Device.user_id == user_id,
                        Device.is_active == True
                    ).all()
                    
                    # Устанавливаем лимит трафика на 0,001 GB (практически без доступа)
                    for device in devices:
                        try:
                            marzban.set_data_limit(device.marzban_username, 0.001)
                            logger.info(f"📊 Лимит трафика установлен для {device.marzban_username}: 0,001 GB (баланс закончился)")
                        except Exception as e:
                            logger.error(f"❌ Не удалось установить лимит трафика для {device.marzban_username}: {e}")
                        
                        # Деактивируем в БД
                        device.is_active = False
                    
                    # Деактивируем все подписки
                    subscriptions = db.query(Subscription).filter(
                        Subscription.user_id == user_id,
                        Subscription.is_active == True
                    ).all()
                    
                    for sub in subscriptions:
                        sub.is_active = False
                    
                    db.commit()
                    logger.warning(f"❌ Баланс закончился (grace day недоступен): user={user_id}, баланс={user.balance}¥, требуется={daily_cost}¥. Установлено ограничение трафика на 0,001 GB.")
                    return {"success": False, "grace_day_given": False, "active_devices": active_devices, "daily_cost": daily_cost, "subscription_ended": True}
                
        except Exception as e:
            logger.error(f"❌ Ошибка при списании для пользователя {user_id}: {e}")
            return {"success": False, "grace_day_given": False, "active_devices": 0, "daily_cost": 0}
        finally:
            db.close()
    
    @staticmethod
    def get_users_with_low_balance_soon(days_threshold: int = 3) -> list:
        """
        Получить пользователей с балансом, которого хватит на N дней или меньше
        
        Returns:
            список кортежей (user_id, current_balance, days_remaining)
        """
        db = SessionLocal()
        try:
            from bot.config import VPN_PRICE_PER_DAY
            
            users = db.query(User).filter(User.is_active == True).all()
            low_balance_users = []
            
            for user in users:
                # Считаем активные устройства
                active_devices = db.query(Device).filter(
                    Device.user_id == user.id,
                    Device.is_active == True
                ).count()
                
                if active_devices == 0:
                    continue  # Нет активных устройств
                
                # Стоимость за день
                daily_cost = VPN_PRICE_PER_DAY * active_devices
                
                # Сколько дней хватит баланса
                days_remaining = int(user.balance / daily_cost) if daily_cost > 0 else 0
                
                # Если дней осталось меньше или равно пороку - добавляем
                if days_remaining <= days_threshold:
                    low_balance_users.append((user.id, user.balance, days_remaining, active_devices))
            
            return low_balance_users
            
        finally:
            db.close()
    
    @staticmethod
    def get_users_with_low_balance():
        """
        Получить пользователей с низким общим балансом
        Низкий баланс = недостаточно для 3 дней на все активные устройства
        
        Returns:
            список кортежей (user_id, current_balance, active_devices_count, threshold)
        """
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active == True).all()
            low_balance_users = []
            
            for user in users:
                # Подсчитываем активные устройства
                active_devices = db.query(Device).filter(
                    Device.user_id == user.id,
                    Device.is_active == True
                ).count()
                
                if active_devices > 0:
                    # Calculate threshold: 3 days * daily price * number of devices
                    threshold = VPN_PRICE_PER_DAY * VPN_LOW_BALANCE_DAYS * active_devices
                    
                    if user.balance < threshold:
                        low_balance_users.append((
                            user.id,
                            user.balance,
                            active_devices,
                            threshold
                        ))
            
            return low_balance_users
            
        finally:
            db.close()
    
    @staticmethod
    def get_user_subscriptions(user_id: int):
        """Получить все подписки пользователя"""
        db = SessionLocal()
        try:
            subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
            return subscriptions
            
        finally:
            db.close()
