import logging
from database.models import SessionLocal, Device, User
from bot.services.vpn_service import marzban_service

logger = logging.getLogger(__name__)


class DeviceService:
    """Сервис управления устройствами"""
    
    @staticmethod
    def create_device(user_id: int, device_name: str, device_type: str = "custom") -> Device:
        """
        Создать новое устройство
        
        Args:
            user_id: ID пользователя
            device_name: название устройства (iPhone, MacBook и т.д.)
            device_type: тип устройства (iPhone, Android, Windows, MacBook, iPad, Linux, custom)
        
        Returns:
            Device объект или None если ошибка
        """
        db = SessionLocal()
        try:
            # Проверяем количество устройств (max 6)
            device_count = db.query(Device).filter(
                Device.user_id == user_id,
                Device.is_active == True
            ).count()
            
            if device_count >= 6:
                logger.warning(f"❌ Пользователь {user_id} достиг лимита устройств (6)")
                return None
            
            # Генерируем username для Marzban
            user = db.query(User).filter(User.id == user_id).first()
            # Очищаем имя: только буквы, цифры и подчеркивания
            clean_device_name = "".join(c if c.isalnum() or c == "_" else "_" for c in device_name.lower())
            clean_device_name = clean_device_name.replace("_", "_")[:20]  # Max 20 chars для имени устройства
            marzban_username = f"{user.telegram_id}_{clean_device_name}"
            
            # Создаем пользователя в Marzban
            if not marzban_service.create_user(marzban_username):
                logger.error(f"❌ Ошибка создания в Marzban: {marzban_username}")
                return None
            
            device = Device(
                user_id=user_id,
                name=device_name,
                device_type=device_type,
                marzban_username=marzban_username,
                is_active=True
            )
            
            db.add(device)
            db.commit()
            db.refresh(device)
            
            logger.info(f"✅ Устройство создано: {device_name} ({marzban_username}) [Тип: {device_type}]")
            return device
            
        finally:
            db.close()
    
    @staticmethod
    def get_user_devices(user_id: int):
        """Получить все устройства пользователя"""
        db = SessionLocal()
        try:
            devices = db.query(Device).filter(
                Device.user_id == user_id
            ).all()
            return devices
            
        finally:
            db.close()
    
    @staticmethod
    def get_active_devices_count(user_id: int) -> int:
        """Получить количество активных устройств"""
        db = SessionLocal()
        try:
            count = db.query(Device).filter(
                Device.user_id == user_id,
                Device.is_active == True
            ).count()
            return count
            
        finally:
            db.close()
    
    @staticmethod
    def delete_device(device_id: int) -> bool:
        """Удалить устройство"""
        db = SessionLocal()
        try:
            device = db.query(Device).filter(Device.id == device_id).first()
            
            if not device:
                logger.error(f"❌ Устройство с ID {device_id} не найдено")
                return False
            
            logger.info(f"🔄 Начинаю удаление устройства: {device.name} (username: {device.marzban_username})")
            
            # Удаляем из Marzban
            marzban_delete_success = marzban_service.delete_user(device.marzban_username)
            
            if not marzban_delete_success:
                logger.error(f"❌ Ошибка при удалении пользователя {device.marzban_username} из Marzban")
                # Даже если ошибка в Marzban, продолжаем удаление из БД
            
            # Удаляем из БД
            db.delete(device)
            db.commit()
            
            logger.info(f"✅ Устройство удалено: {device.name} (Marzban: {'успешно' if marzban_delete_success else 'ошибка'})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении устройства {device_id}: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def cleanup_invalid_devices() -> int:
        """
        Найти и удалить устройства с неправильным username форматом
        (созданные до исправления)
        
        Returns:
            Количество удаленных устройств
        """
        db = SessionLocal()
        try:
            # Ищем устройства с неправильным форматом username
            devices = db.query(Device).all()
            deleted_count = 0
            
            for device in devices:
                # Правильный формат: user_XXX_yy (где X - цифры, y - буквы/цифры)
                username = device.marzban_username
                
                # Проверяем что username содержит пробелы (это точно неправильно)
                if " " in username:
                    # Пытаемся удалить из Marzban
                    marzban_service.delete_user(username)
                    
                    # Удаляем из БД
                    db.delete(device)
                    deleted_count += 1
                    logger.info(f"🗑️ Удалено неправильное устройство: {device.name} ({username})")
            
            if deleted_count > 0:
                db.commit()
                logger.info(f"✅ Очищено {deleted_count} неправильных устройств")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке устройств: {e}")
            return 0
        finally:
            db.close()
    
    @staticmethod
    def rename_device(device_id: int, new_name: str) -> bool:
        """Переименовать устройство"""
        db = SessionLocal()
        try:
            device = db.query(Device).filter(Device.id == device_id).first()
            
            if not device:
                logger.error(f"❌ Устройство {device_id} не найдено")
                return False
            
            old_name = device.name
            device.name = new_name
            db.commit()
            
            logger.info(f"✅ Устройство переименовано: '{old_name}' → '{new_name}'")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при переименовании: {e}")
            return False
        finally:
            db.close()
