"""
Payment Request Service
Управление запросами на пополнение баланса с уникальной суммой и многоэтапным подтверждением.

Флоу:
1. Пользователь нажимает "Оплатить"
2. Создается PaymentRequest со статусом 'awaiting_admin'
3. Админу отправляется уведомление с кнопками "Подтвердить" и "Отклонить"
4. Админ нажимает "Подтвердить" → статус 'admin_confirmed'
5. Админ отправляет QR код
6. Пользователю приходит QR с кнопкой подтверждения → статус 'awaiting_payment'
7. Пользователь нажимает "Подтвердить оплату" → админ вручную проверяет
8. После проверки админа → статус 'completed'
"""

import random
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

from database.models import SessionLocal, PaymentRequest, User

logger = logging.getLogger(__name__)


class PaymentRequestService:
    """Управление payment requests"""
    
    @staticmethod
    def create_request(user_id: int, amount: float) -> Optional[PaymentRequest]:
        """
        Создать новый payment request
        
        Args:
            user_id: ID пользователя
            amount: Запрошенная сумма в юанях
        
        Returns:
            PaymentRequest объект или None если ошибка
        """
        try:
            db = SessionLocal()
            
            # Сгенерировать уникальную сумму ±1 юань
            offset = random.uniform(-0.99, 0.99)  # ±0.99 для вариативности
            unique_amount = round(amount + offset, 2)
            
            logger.info(f"💳 Creating payment request: user_id={user_id}, "
                       f"requested={amount}¥, unique_amount={unique_amount}¥")
            
            # Удалить старые pending запросы от этого пользователя (если есть)
            db.query(PaymentRequest).filter(
                PaymentRequest.user_id == user_id,
                PaymentRequest.status == 'awaiting_admin'
            ).delete()
            
            # Создать новый request
            payment_request = PaymentRequest(
                user_id=user_id,
                amount_requested=amount,
                unique_amount=unique_amount,
                status='awaiting_admin'
            )
            
            db.add(payment_request)
            db.commit()
            db.refresh(payment_request)
            
            logger.info(f"✅ Payment request created: ID={payment_request.id}, "
                       f"unique_amount={unique_amount}¥")
            
            return payment_request
            
        except Exception as e:
            logger.error(f"❌ Error creating payment request: {e}")
            return None
        finally:
            db.close()
    
    @staticmethod
    def confirm_by_admin(request_id: int, admin_message_id: int) -> bool:
        """
        Подтвердить запрос админом
        
        Args:
            request_id: ID payment request
            admin_message_id: message_id уведомления админу
        
        Returns:
            True если успешно
        """
        try:
            db = SessionLocal()
            
            request = db.query(PaymentRequest).filter(
                PaymentRequest.id == request_id
            ).first()
            
            if not request:
                logger.warning(f"⚠️ Payment request not found: {request_id}")
                return False
            
            request.status = 'admin_confirmed'
            request.admin_confirmed_at = datetime.utcnow()
            request.admin_message_id = admin_message_id
            
            db.commit()
            
            logger.info(f"✅ Admin confirmed payment request {request_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error confirming payment request: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def decline_by_admin(request_id: int) -> bool:
        """
        Отклонить запрос админом
        
        Args:
            request_id: ID payment request
        
        Returns:
            True если успешно
        """
        try:
            db = SessionLocal()
            
            request = db.query(PaymentRequest).filter(
                PaymentRequest.id == request_id
            ).first()
            
            if not request:
                logger.warning(f"⚠️ Payment request not found: {request_id}")
                return False
            
            request.status = 'declined'
            db.commit()
            
            logger.info(f"✅ Admin declined payment request {request_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error declining payment request: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def set_qr_sent(request_id: int, user_message_id: int) -> bool:
        """
        Отметить что QR отправлен пользователю
        
        Args:
            request_id: ID payment request
            user_message_id: message_id сообщения пользователю с QR
        
        Returns:
            True если успешно
        """
        try:
            db = SessionLocal()
            
            request = db.query(PaymentRequest).filter(
                PaymentRequest.id == request_id
            ).first()
            
            if not request:
                logger.warning(f"⚠️ Payment request not found: {request_id}")
                return False
            
            # Установить статус и время истечения QR (15 минут)
            request.status = 'awaiting_payment'
            request.user_message_id = user_message_id
            request.qr_expires_at = datetime.utcnow() + timedelta(minutes=15)
            
            db.commit()
            
            logger.info(f"✅ QR sent for payment request {request_id}, "
                       f"expires at {request.qr_expires_at}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error setting QR sent: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def complete_payment(request_id: int) -> bool:
        """
        Завершить платежный процесс (после того как админ проверил)
        
        Args:
            request_id: ID payment request
        
        Returns:
            True если успешно
        """
        try:
            db = SessionLocal()
            
            request = db.query(PaymentRequest).filter(
                PaymentRequest.id == request_id
            ).first()
            
            if not request:
                logger.warning(f"⚠️ Payment request not found: {request_id}")
                return False
            
            request.status = 'completed'
            request.payment_confirmed_at = datetime.utcnow()
            
            db.commit()
            
            logger.info(f"✅ Payment request {request_id} completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error completing payment request: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def expire_old_qrs() -> int:
        """
        Отметить превышенные по времени QR коды как истекшие
        
        Returns:
            Количество истекших запросов
        """
        try:
            db = SessionLocal()
            
            now = datetime.utcnow()
            expired_count = db.query(PaymentRequest).filter(
                PaymentRequest.status == 'awaiting_payment',
                PaymentRequest.qr_expires_at < now
            ).count()
            
            # Обновить статус на 'expired' для старых requests
            db.query(PaymentRequest).filter(
                PaymentRequest.status == 'awaiting_payment',
                PaymentRequest.qr_expires_at < now
            ).update({'status': 'expired'})
            
            db.commit()
            
            if expired_count > 0:
                logger.info(f"⏰ Expired {expired_count} old QR codes")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"❌ Error expiring old QRs: {e}")
            return 0
        finally:
            db.close()
    
    @staticmethod
    def get_request(request_id: int) -> Optional[PaymentRequest]:
        """
        Получить payment request по ID
        
        Args:
            request_id: ID payment request
        
        Returns:
            PaymentRequest объект или None
        """
        try:
            db = SessionLocal()
            request = db.query(PaymentRequest).filter(
                PaymentRequest.id == request_id
            ).first()
            return request
        finally:
            db.close()
    
    @staticmethod
    def get_pending_request(user_id: int) -> Optional[PaymentRequest]:
        """
        Получить текущий pending payment request пользователя
        
        Args:
            user_id: ID пользователя
        
        Returns:
            PaymentRequest объект или None
        """
        try:
            db = SessionLocal()
            request = db.query(PaymentRequest).filter(
                PaymentRequest.user_id == user_id,
                PaymentRequest.status.in_(['awaiting_admin', 'admin_confirmed', 'awaiting_payment'])
            ).order_by(PaymentRequest.created_at.desc()).first()
            return request
        finally:
            db.close()
    
    @staticmethod
    def get_user_info(user_id: int) -> Optional[Dict]:
        """
        Получить информацию о пользователе для уведомлений
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Словарь с info или None
        """
        try:
            db = SessionLocal()
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return {
                    'username': user.username or f"User{user.telegram_id}",
                    'first_name': user.first_name,
                    'telegram_id': user.telegram_id
                }
            return None
        finally:
            db.close()
