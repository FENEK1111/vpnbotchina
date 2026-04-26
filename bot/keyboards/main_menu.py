from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton


def get_device_emoji(device_type: str) -> str:
    """Get emoji for device type"""
    emojis = {
        "iPhone": "📱",
        "Android": "🤖",
        "Windows": "💻",
        "MacBook": "🍎",
        "iPad": "📲",
        "Linux": "🐧",
        "custom": "⚙️"
    }
    return emojis.get(device_type, "⚙️")


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu"""
    keyboard = [
        [KeyboardButton("📱 My Devices")],
        [KeyboardButton("💰 My Balance")],
        [KeyboardButton("➕ Add Device"), KeyboardButton("✏️ Rename")],
        [KeyboardButton("🎁 Referral Program")],
        [KeyboardButton("❓ Help"), KeyboardButton("⚙️ Settings")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_subscription_menu_keyboard() -> InlineKeyboardMarkup:
    """Payment/Top-up menu - WeChat Pay only"""
    keyboard = [
        [InlineKeyboardButton("🛒 ¥10", callback_data="wechat_initiate_10")],
        [InlineKeyboardButton("🛒 ¥20", callback_data="wechat_initiate_20")],
        [InlineKeyboardButton("🛒 ¥50", callback_data="wechat_initiate_50")],
        [InlineKeyboardButton("🛒 ¥100", callback_data="wechat_initiate_100")],
        [InlineKeyboardButton("🛒 ¥200", callback_data="wechat_initiate_200")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_device_actions_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """Device actions menu"""
    keyboard = [
        [InlineKeyboardButton("📊 Info", callback_data=f"device_info_{device_id}")],
        [InlineKeyboardButton("🔄 Configuration", callback_data=f"device_config_{device_id}")],
        [InlineKeyboardButton("❌ Delete", callback_data=f"device_delete_{device_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_devices")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_confirm_delete_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """Confirm device deletion"""
    keyboard = [
        [InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_delete_{device_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"device_info_{device_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_device_type_keyboard() -> InlineKeyboardMarkup:
    """Device type selection menu"""
    keyboard = [
        [InlineKeyboardButton("📱 iPhone", callback_data="device_type_iPhone")],
        [InlineKeyboardButton("🤖 Android", callback_data="device_type_Android")],
        [InlineKeyboardButton("💻 Windows", callback_data="device_type_Windows")],
        [InlineKeyboardButton("🍎 MacBook", callback_data="device_type_MacBook")],
        [InlineKeyboardButton("📲 iPad", callback_data="device_type_iPad")],
        [InlineKeyboardButton("🐧 Linux", callback_data="device_type_Linux")],
        [InlineKeyboardButton("✏️ Other", callback_data="device_type_custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu"""
    keyboard = [
        [InlineKeyboardButton("🔔 Notifications", callback_data="settings_notifications")],
        [InlineKeyboardButton("🌐 Language", callback_data="settings_language")],
        [InlineKeyboardButton("👤 Profile", callback_data="settings_profile")],
        [InlineKeyboardButton("ℹ️ About", callback_data="settings_about")],
        [InlineKeyboardButton("❌ Close", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_devices_for_rename_keyboard(devices) -> InlineKeyboardMarkup:
    """Menu for selecting device to rename"""
    keyboard = []
    for device in devices:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ {device.name}", 
                callback_data=f"rename_select_{device.id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_devices_selection_keyboard(devices) -> InlineKeyboardMarkup:
    """Menu for selecting device from list"""
    keyboard = []
    for device in devices:
        emoji = get_device_emoji(device.device_type)
        status = "✅" if device.is_active else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {device.name} {status}", 
                callback_data=f"select_device_{device.id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)
