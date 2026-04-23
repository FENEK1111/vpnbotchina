import requests
import logging
from typing import Optional, Dict
from bot.config import MARZBAN_URL, MARZBAN_ADMIN_TOKEN

logger = logging.getLogger(__name__)


class MarzbanService:
    """Сервис для взаимодействия с Marzban API"""
    
    def __init__(self):
        self.base_url = MARZBAN_URL
        self.token = MARZBAN_ADMIN_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def create_user(self, username: str, data_limit: int = None, protocol: str = "vless", retry_on_exists: bool = True) -> bool:
        """
        Создать пользователя в Marzban
        
        Args:
            username: имя пользователя
            data_limit: лимит данных в байтах (опционально)
            protocol: протокол подключения (vless или shadowsocks)
            retry_on_exists: если True, при ошибке "User already exists" удалить и создать заново
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Базовая конфигурация для VLESS
            payload = {
                "username": username,
                "status": "active",
                "concurrent_connections": 1,  # Максимум одно одновременное подключение
                "data_limit": data_limit or 0,
                "data_limit_reset_strategy": "no_reset",
                "expire": None,
                "note": f"Protocol: {protocol}",
                "inbounds": {},
                "proxies": {}
            }
            
            # Конфигурируем в зависимости от выбранного протокола
            if protocol.lower() == "vless":
                payload["inbounds"]["vless"] = ["VLESS_REALITY_INBOUND"]
                payload["proxies"]["vless"] = {"flow": ""}
            elif protocol.lower() == "shadowsocks":
                payload["inbounds"]["shadowsocks"] = ["Shadowsocks TCP"]
                payload["proxies"]["shadowsocks"] = {"method": "chacha20-ietf-poly1305"}
            else:
                # По умолчанию только VLESS
                payload["inbounds"]["vless"] = ["VLESS_REALITY_INBOUND"]
                payload["proxies"]["vless"] = {"flow": ""}
            
            response = requests.post(
                f"{self.base_url}/api/user",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Пользователь {username} создан в Marzban")
                return True
            elif response.status_code == 400 and "User already exists" in response.text:
                if retry_on_exists:
                    logger.info(f"⚠️  Пользователь {username} уже существует, пытаюсь удалить и создать заново...")
                    # Удаляем старого пользователя
                    self.delete_user(username)
                    # Создаем заново (без retry чтобы избежать бесконечного цикла)
                    return self.create_user(username, data_limit, protocol, retry_on_exists=False)
                else:
                    logger.info(f"ℹ️  Пользователь {username} уже существует в Marzban (используем существующего)")
                    return True  # Возвращаем True, так как пользователь существует
            else:
                logger.error(f"❌ Ошибка создания пользователя: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Marzban: {e}")
            return False
    
    def delete_user(self, username: str) -> bool:
        """Удалить пользователя из Marzban"""
        try:
            # Сначала пробуем удалить с обычным именем
            url = f"{self.base_url}/api/users/{username}"
            logger.info(f"🔄 Удаляю пользователя {username} из Marzban ({url})")
            
            response = requests.delete(
                url,
                headers=self.headers,
                timeout=10
            )
            
            logger.info(f"📊 Статус ответа: {response.status_code}")
            
            if response.status_code in [200, 204]:
                logger.info(f"✅ Пользователь {username} удален из Marzban")
                return True
            elif response.status_code == 404:
                # Если не найдено, пробуем с форматом Wordvpn(username)
                logger.info(f"⚠️ Пользователь {username} не найден, пробую Wordvpn({username})")
                
                formatted_username = f"Wordvpn({username})"
                url_formatted = f"{self.base_url}/api/users/{formatted_username}"
                logger.info(f"🔄 Пробую удалить как {formatted_username}")
                
                response_formatted = requests.delete(
                    url_formatted,
                    headers=self.headers,
                    timeout=10
                )
                
                logger.info(f"📊 Статус ответа (Wordvpn формат): {response_formatted.status_code}")
                
                if response_formatted.status_code in [200, 204]:
                    logger.info(f"✅ Пользователь {formatted_username} удален из Marzban")
                    return True
                elif response_formatted.status_code == 404:
                    logger.warning(f"⚠️ Пользователь не найден ни в одном формате (возможно уже удален)")
                    return True  # Возвращаем True, так как устройство как бы удалилось
                else:
                    logger.error(f"❌ Ошибка удаления {formatted_username}: [{response_formatted.status_code}] {response_formatted.text}")
                    return False
            else:
                logger.error(f"❌ Ошибка удаления {username}: [{response.status_code}] {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения при удалении {username}: {e}")
            return False
    
    def get_user_info(self, username: str) -> Optional[Dict]:
        """Получить информацию о пользователе"""
        try:
            response = requests.get(
                f"{self.base_url}/api/users/{username}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации: {e}")
            return None
    
    def reset_user_data(self, username: str) -> bool:
        """Сбросить статистику трафика пользователя"""
        try:
            payload = {"used_traffic": 0}
            response = requests.patch(
                f"{self.base_url}/api/users/{username}",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Статистика {username} сброшена")
                return True
            return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка сброса: {e}")
            return False
    
    def set_data_limit(self, username: str, data_limit_gb: float) -> bool:
        """
        Установить лимит трафика для пользователя
        
        Args:
            username: имя пользователя
            data_limit_gb: лимит в GB (например, 0.001)
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Конвертируем GB в байты (1 GB = 1,073,741,824 байт)
            data_limit_bytes = int(data_limit_gb * 1_073_741_824)
            
            payload = {"data_limit": data_limit_bytes}
            response = requests.patch(
                f"{self.base_url}/api/users/{username}",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Лимит трафика установлен для {username}: {data_limit_gb} GB ({data_limit_bytes} байт)")
                return True
            else:
                logger.error(f"❌ Ошибка установки лимита для {username}: [{response.status_code}] {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка при установке лимита для {username}: {e}")
            return False
    
    def get_user_links(self, username: str) -> Optional[Dict]:
        """
        Получить ссылки подключения пользователя (конфиги для клиента)
        
        Returns:
            Dict с ссылками или None если ошибка
        """
        try:
            # Сначала пытаемся через прямой эндпоинт /api/users/{username}/links
            response = requests.get(
                f"{self.base_url}/api/users/{username}/links",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Ссылки пользователя {username} получены (endpoint)")
                return data
            
            # Fallback: получаем через /api/users и ищем пользователя
            list_response = requests.get(
                f"{self.base_url}/api/users",
                headers=self.headers,
                timeout=10
            )
            
            if list_response.status_code == 200:
                data = list_response.json()
                users = data.get("users", [])
                
                for user in users:
                    if user.get("username") == username:
                        result = {"links": user.get("links", [])}
                        logger.info(f"✅ Ссылки пользователя {username} получены (from list)")
                        return result
                
                logger.warning(f"⚠️ Пользователь {username} не найден в списке")
            else:
                logger.error(f"❌ Ошибка получения списка: {list_response.status_code} - {list_response.text}")
            
            return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка при получении ссылок: {e}")
            return None
    
    def get_user_config_string(self, username: str, protocol: str = "vless") -> Optional[str]:
        """
        Получить строку конфигурации для клиента
        
        Args:
            username: имя пользователя в Marzban
            protocol: протокол (vless, shadowsocks, etc)
        
        Returns:
            Строка конфигурации вроде 'vless://...' или None
        """
        try:
            # Получаем список всех пользователей и ищем нужного
            list_response = requests.get(
                f"{self.base_url}/api/users",
                headers=self.headers,
                timeout=10
            )
            
            if list_response.status_code == 200:
                data = list_response.json()
                users = data.get("users", [])
                
                # Ищем пользователя по username
                for user in users:
                    if user.get("username") == username:
                        logger.info(f"📍 Найден пользователь {username}")
                        
                        # Способ 1: Берем прямую ссылку из "links"
                        if "links" in user and isinstance(user["links"], list) and len(user["links"]) > 0:
                            config = user["links"][0]
                            logger.info(f"✅ Конфиг найден из links для {username}")
                            return config
                        
                        # Способ 2: Получаем конфиг через subscription_url (BASE64)
                        if "subscription_url" in user:
                            sub_url = user["subscription_url"]
                            if sub_url.startswith("/"):
                                sub_url = self.base_url + sub_url
                            
                            logger.info(f"📍 Пытаемся получить конфиг через subscription_url: {sub_url}")
                            sub_response = requests.get(sub_url, timeout=10)
                            
                            if sub_response.status_code == 200:
                                # Ответ в BASE64, нужно декодировать
                                import base64
                                try:
                                    decoded = base64.b64decode(sub_response.text).decode('utf-8')
                                    # Возвращаем первую строку (первый конфиг)
                                    lines = decoded.split('\n')
                                    for line in lines:
                                        if line.strip():
                                            logger.info(f"✅ Конфиг найден из subscription_url для {username}")
                                            return line.strip()
                                except Exception as e:
                                    logger.warning(f"⚠️ Ошибка декодирования subscription_url: {e}")
                        
                        logger.warning(f"⚠️ Не удалось найти конфиг для {username}")
                        return None
                
                logger.warning(f"⚠️ Пользователь {username} не найден в списке")
                return None
            else:
                logger.error(f"❌ Ошибка получения списка пользователей: {list_response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка при получении конфига: {e}")
            return None


marzban_service = MarzbanService()
