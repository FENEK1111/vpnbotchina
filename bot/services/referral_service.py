import logging
from database.models import SessionLocal, User, Referral
from bot.config import VPN_PRICE_PER_DAY

logger = logging.getLogger(__name__)

# Calculate referral bonus: 7 days VPN, rounded to whole number
REFERRAL_BONUS = round(7 * VPN_PRICE_PER_DAY)  # 7 days (1 week) ≈ 5¥


class ReferralService:
    """Сервис работы с реферальной системой"""
    
    @staticmethod
    def generate_referral_link(bot_username: str, user_id: int) -> str:
        """
        Генерировать реферальную ссылку
        
        Args:
            bot_username: имя бота в Telegram (без @)
            user_id: ID пользователя (или telegram_id)
            
        Returns:
            Реферальная ссылка
        """
        return f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    @staticmethod
    def get_referral_stats(user_id: int) -> dict:
        """
        Получить статистику рефералов пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            dict: статистика {'total_referrals': int, 'total_earned': float, 'pending': int}
        """
        db = SessionLocal()
        try:
            # Получаем все рефералы пользователя
            referrals = db.query(Referral).filter(
                Referral.referrer_id == user_id
            ).all()
            
            total_earned = sum(ref.bonus_amount for ref in referrals if ref.is_paid)
            pending_bonuses = sum(ref.bonus_amount for ref in referrals if not ref.is_paid)
            
            return {
                "total_referrals": len(referrals),
                "total_earned": total_earned,
                "pending": len([r for r in referrals if not r.is_paid]),
                "pending_amount": pending_bonuses
            }
            
        finally:
            db.close()
    
    @staticmethod
    def get_referral_list(user_id: int) -> list:
        """
        Получить список рефералов пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            list: список кортежей (username, created_at, bonus_amount, is_paid)
        """
        db = SessionLocal()
        try:
            referrals = db.query(Referral).filter(
                Referral.referrer_id == user_id
            ).order_by(Referral.created_at.desc()).all()
            
            result = []
            for ref in referrals:
                user = db.query(User).filter(User.id == ref.referred_user_id).first()
                if user:
                    result.append({
                        "username": user.username or f"User_{user.telegram_id}",
                        "date": ref.created_at,
                        "bonus": ref.bonus_amount,
                        "paid": ref.is_paid
                    })
            
            return result
            
        finally:
            db.close()
    
    @staticmethod
    def create_referral(referrer_id: int, referred_user_id: int) -> tuple:
        """
        Создать запись о референале и выдать бонус
        
        Args:
            referrer_id: ID того, кто пригласил
            referred_user_id: ID приглашённого пользователя
            
        Returns:
            tuple: (bool - успешно ли, referrer_telegram_id если успешно или None)
        """
        db = SessionLocal()
        try:
            logger.info(f"📍 create_referral начало: referrer_id={referrer_id}, referred_user_id={referred_user_id}")
            
            # Проверяем что рефереа существует
            referred_user = db.query(User).filter(User.id == referred_user_id).first()
            if not referred_user:
                logger.error(f"❌ Новый пользователь {referred_user_id} не найден")
                return False, None
            
            logger.info(f"✅ Новый пользователь найден: {referred_user.username or referred_user.telegram_id}")
            
            # ⚠️ ЗАЩИТА ОТ ABUSE: проверяем что пользователь не был ранее приглашен кем-то другим
            if referred_user.referrer_id is not None:
                logger.warning(
                    f"⚠️ ABUSE BLOCKED: Попытка добавить реферера {referrer_id} пользователю {referred_user_id}, "
                    f"но у пользователя уже есть реферер {referred_user.referrer_id}"
                )
                return False, None
            
            logger.info(f"✅ У пользователя {referred_user_id} нет рефереа - можно добавлять")
            
            # Проверяем что реферал с этим пользователем ещё не создан (двойная защита)
            existing_referral = db.query(Referral).filter(
                Referral.referred_user_id == referred_user_id
            ).first()
            
            if existing_referral:
                logger.warning(f"⚠️ Реферальная запись для пользователя {referred_user_id} уже существует")
                return False, None
            
            logger.info(f"✅ Реферальная запись не существует - можно создавать")
            
            # Получаем рефереа
            referrer = db.query(User).filter(User.id == referrer_id).first()
            if not referrer:
                logger.error(f"❌ Рефереа {referrer_id} не найден")
                return False, None
            
            logger.info(f"✅ Рефереа найден: {referrer.username or referrer.telegram_id}")
            
            # ⚠️ Проверяем что пользователь не пытается пригласить сам себя
            if referrer_id == referred_user_id:
                logger.warning(f"⚠️ ABUSE BLOCKED: Попытка self-referral от пользователя {referrer_id}")
                return False, None
            
            logger.info(f"✅ Это не self-referral")
            
            # Создаем запись о референале
            referral = Referral(
                referrer_id=referrer_id,
                referred_user_id=referred_user_id,
                bonus_amount=REFERRAL_BONUS,
                is_paid=True  # Сразу выплачиваем
            )
            
            db.add(referral)
            db.commit()
            logger.info(f"✅ Запись Referral создана в БД")
            
            # Добавляем баланс рефереа
            old_balance = referrer.balance
            referrer.balance += REFERRAL_BONUS
            db.commit()
            logger.info(f"✅ Баланс рефереа обновлен: {old_balance:.2f} -> {referrer.balance:.2f}")
            
            referrer_telegram_id = referrer.telegram_id
            
            logger.info(
                f"✅ Реферал успешно создан: {referrer.username or 'User_' + str(referrer.telegram_id)} "
                f"пригласил {referred_user.username or 'User_' + str(referred_user.telegram_id)}\n"
                f"   Бонус: {REFERRAL_BONUS}¥, telegram_id={referrer_telegram_id}"
            )
            
            return True, referrer_telegram_id
            
        except Exception as e:
            logger.error(f"❌ Исключение в create_referral: {e}", exc_info=True)
            return False, None
        finally:
            db.close()
    
    @staticmethod
    def set_referrer(user_id: int, referrer_id: int) -> bool:
        """
        Установить рефереа для пользователя
        
        Args:
            user_id: ID пользователя
            referrer_id: ID рефереа
            
        Returns:
            bool: True если успешно
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            
            if not user:
                logger.error(f"❌ Пользователь {user_id} не найден")
                return False
            
            if user.referrer_id is not None:
                logger.warning(f"⚠️ У пользователя {user_id} уже есть рефереа")
                return False
            
            user.referrer_id = referrer_id
            db.commit()
            
            logger.info(f"✅ Рефереа установлен: {user_id} -> {referrer_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка установления рефереа: {e}")
            return False
        finally:
            db.close()
