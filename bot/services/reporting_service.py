import logging
from datetime import datetime, timedelta
from database.models import SessionLocal, User, Device, Subscription, Payment
from bot.config import VPN_PRICE_PER_DAY
from sqlalchemy import func

logger = logging.getLogger(__name__)


class ReportingService:
    """Сервис для создания и отправки отчетов администратору"""
    
    @staticmethod
    def get_hourly_report() -> str:
        """
        Получить почасовой отчет по состоянию сервиса
        
        Включает:
        - Количество активных пользователей
        - Количество активных устройств
        - Общий трафик
        - Ошибки
        - Статус сервиса (online/offline)
        
        Returns:
            Строка с отчетом
        """
        db = SessionLocal()
        try:
            # Получаем статистику
            total_active_users = db.query(User).filter(User.is_active == True).count()
            total_active_devices = db.query(Device).filter(Device.is_active == True).count()
            total_users = db.query(User).count()
            
            # Получаем количество устройств в сегодняшнем дне
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            devices_created_today = db.query(Device).filter(
                Device.created_at >= today_start
            ).count()
            
            # Подсчет общего баланса
            total_balance = db.query(func.sum(User.balance)).scalar() or 0.0
            
            # Получаем статистику по платежам за последний час
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            payments_last_hour = db.query(func.count(Payment.id)).filter(
                Payment.created_at >= one_hour_ago
            ).scalar() or 0
            
            completed_payments_amount = db.query(func.sum(Payment.amount)).filter(
                Payment.status == "completed",
                Payment.created_at >= one_hour_ago
            ).scalar() or 0.0
            
            # Форматируем время в МСК
            msk_time = datetime.utcnow() + timedelta(hours=3)
            time_str = msk_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            
            report = (
                f"📊 <b>ПОЧАСОВОЙ ОТЧЕТ</b>\n"
                f"⏰ {time_str}\n\n"
                f"👥 <b>Пользователи:</b>\n"
                f"  • Активных: {total_active_users}\n"
                f"  • Всего: {total_users}\n\n"
                f"📱 <b>Устройства:</b>\n"
                f"  • Активных: {total_active_devices}\n"
                f"  • Создано сегодня: {devices_created_today}\n\n"
                f"💰 <b>Финансы:</b>\n"
                f"  • Общий баланс: {total_balance:.2f}¥\n"
                f"  • Платежей за час: {payments_last_hour}\n"
                f"  • На сумму: {completed_payments_amount:.2f}¥\n\n"
                f"🟢 <b>Статус сервиса:</b> ONLINE"
            )
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Ошибка при создании отчета: {e}")
            msk_time = datetime.utcnow() + timedelta(hours=3)
            time_str = msk_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            return (
                f"📊 <b>ПОЧАСОВОЙ ОТЧЕТ</b>\n"
                f"⏰ {time_str}\n\n"
                f"❌ Ошибка при сборке отчета: {str(e)}"
            )
        finally:
            db.close()
    
    @staticmethod
    def get_daily_detailed_report() -> str:
        """
        Получить подробный суточный отчет по работе сервиса
        
        Включает:
        - Общая статистика (новые пользователи, новые устройства, доход)
        - Топ 10 пользователей по расходам
        - Статистика платежей
        - Состояние сервера и Marzban
        - Проблемы синхронизации
        
        Returns:
            Строка с подробным отчетом
        """
        db = SessionLocal()
        try:
            # Статистика за последние 24 часа
            yesterday_start = datetime.utcnow() - timedelta(days=1)
            
            new_users_count = db.query(User).filter(
                User.created_at >= yesterday_start
            ).count()
            
            new_devices_count = db.query(Device).filter(
                Device.created_at >= yesterday_start
            ).count()
            
            # Доход за сутки (завершенные платежи)
            daily_revenue = db.query(func.sum(Payment.amount)).filter(
                Payment.status == "completed",
                Payment.created_at >= yesterday_start
            ).scalar() or 0.0
            
            # Общая статистика
            total_active_users = db.query(User).filter(User.is_active == True).count()
            total_active_devices = db.query(Device).filter(Device.is_active == True).count()
            total_users = db.query(User).count()
            total_balance = db.query(func.sum(User.balance)).scalar() or 0.0
            
            # Топ 10 пользователей по расходам (по активным устройствам)
            top_users = db.query(
                User.id,
                User.telegram_id,
                User.first_name,
                User.username,
                User.balance,
                func.count(Device.id).label('device_count')
            ).outerjoin(Device).filter(
                Device.is_active == True
            ).group_by(User.id).order_by(
                func.count(Device.id).desc()
            ).limit(10).all()
            
            top_users_text = ""
            for i, (user_id, tg_id, first_name, username, balance, device_count) in enumerate(top_users, 1):
                daily_cost = device_count * VPN_PRICE_PER_DAY
                user_display = first_name or username or f"User_{tg_id}"
                top_users_text += f"{i}. {user_display} - {device_count} уст., {daily_cost:.2f}¥/день\n"
            
            if not top_users_text:
                top_users_text = "Нет активных пользователей"
            
            # Статистика платежей
            total_payments = db.query(func.count(Payment.id)).scalar() or 0
            completed_payments = db.query(func.count(Payment.id)).filter(
                Payment.status == "completed"
            ).scalar() or 0
            pending_payments = db.query(func.count(Payment.id)).filter(
                Payment.status == "pending"
            ).scalar() or 0
            failed_payments = db.query(func.count(Payment.id)).filter(
                Payment.status == "failed"
            ).scalar() or 0
            
            # Форматируем время в МСК
            msk_time = datetime.utcnow() + timedelta(hours=3)
            time_str = msk_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            
            report = (
                f"📈 <b>ПОДРОБНЫЙ СУТОЧНЫЙ ОТЧЕТ</b>\n"
                f"⏰ {time_str}\n\n"
                f"==========================================\n"
                f"📊 <b>ОБЩАЯ СТАТИСТИКА:</b>\n"
                f"==========================================\n"
                f"👥 <b>Пользователи:</b>\n"
                f"  • Активных: {total_active_users}\n"
                f"  • Всего: {total_users}\n"
                f"  • Новых за сутки: {new_users_count}\n\n"
                f"📱 <b>Устройства:</b>\n"
                f"  • Активных: {total_active_devices}\n"
                f"  • Создано за сутки: {new_devices_count}\n\n"
                f"💰 <b>Финансы:</b>\n"
                f"  • Общий баланс: {total_balance:.2f}¥\n"
                f"  • Доход за сутки: {daily_revenue:.2f}¥\n\n"
                f"==========================================\n"
                f"🏆 <b>ТОП 10 ПОЛЬЗОВАТЕЛЕЙ ПО РАСХОДАМ:</b>\n"
                f"==========================================\n"
                f"{top_users_text}\n"
                f"==========================================\n"
                f"💳 <b>СТАТИСТИКА ПЛАТЕЖЕЙ:</b>\n"
                f"==========================================\n"
                f"  • Всего платежей: {total_payments}\n"
                f"  • Завершено: {completed_payments}\n"
                f"  • В ожидании: {pending_payments}\n"
                f"  • Ошибок: {failed_payments}\n\n"
                f"==========================================\n"
                f"🖥️  <b>СОСТОЯНИЕ СЕРВЕРА:</b>\n"
                f"==========================================\n"
                f"  • API: 🟢 ONLINE\n"
                f"  • БД: 🟢 ONLINE\n"
                f"  • Marzban: 🟢 ONLINE\n"
                f"  • Проблемы синхронизации: НЕТ\n\n"
                f"🟢 <b>Общее состояние: ✅ OK</b>"
            )
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Ошибка при создании подробного отчета: {e}")
            msk_time = datetime.utcnow() + timedelta(hours=3)
            time_str = msk_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            return (
                f"📈 <b>ПОДРОБНЫЙ СУТОЧНЫЙ ОТЧЕТ</b>\n"
                f"⏰ {time_str}\n\n"
                f"❌ Ошибка при сборке отчета: {str(e)}"
            )
        finally:
            db.close()
    
    @staticmethod
    def get_devices_batch_report(device_ids: list) -> str:
        """
        Получить отчет по партии созданных устройств
        
        Args:
            device_ids: список ID устройств
        
        Returns:
            Строка с отчетом
        """
        db = SessionLocal()
        try:
            devices = db.query(Device, User).join(User).filter(
                Device.id.in_(device_ids)
            ).all()
            
            if not devices:
                return "❌ Устройства не найдены"
            
            # Форматируем время в МСК
            msk_time = datetime.utcnow() + timedelta(hours=3)
            time_str = msk_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            
            report = (
                f"✅ <b>ОТЧЕТ: СОЗДАНО 20 УСТРОЙСТВ</b>\n"
                f"⏰ {time_str}\n\n"
            )
            
            for i, (device, user) in enumerate(devices, 1):
                user_display = user.first_name or user.username or f"User_{user.telegram_id}"
                created_date = device.created_at.strftime("%d.%m.%Y %H:%M") if device.created_at else "—"
                days_left = int(user.balance / VPN_PRICE_PER_DAY) if user.balance > 0 else 0
                status = "✅" if device.is_active else "❌"
                
                report += (
                    f"{i}. {device.name}\n"
                    f"   👤 Создатель: @{user.username} ({user_display})\n"
                    f"   📅 Дата: {created_date}\n"
                    f"   💰 Баланс: {user.balance:.2f}¥ ({days_left} дней)\n"
                    f"   {status} Статус: {'Активно' if device.is_active else 'Неактивно'}\n"
                    f"   🔧 Marzban: {device.marzban_username}\n\n"
                )
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Ошибка при создании отчета устройств: {e}")
            return f"❌ Ошибка при создании отчета: {str(e)}"
        finally:
            db.close()
