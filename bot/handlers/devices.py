import logging
import uuid
from telegram import Update
from telegram.ext import ContextTypes
from database.models import SessionLocal, User, Device, Subscription
from bot.services.vpn_service import marzban_service
from bot.services.device_service import DeviceService
from bot.keyboards.main_menu import get_device_actions_keyboard, get_confirm_delete_keyboard, get_device_type_keyboard, get_devices_selection_keyboard, get_device_emoji

logger = logging.getLogger(__name__)


async def show_devices_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's device list"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        devices = DeviceService.get_user_devices(user.id)
        active_count = DeviceService.get_active_devices_count(user.id)
        
        if not devices:
            await update.message.reply_text(
                "📱 You have no devices. Add your first device!",
                parse_mode="HTML"
            )
            return
        
        message = f"📱 <b>Select device ({active_count}/6)</b>\n\n"
        message += f"💰 Balance: <b>{user.balance:.2f}¥</b>\n\n"
        
        await update.message.reply_text(
            message,
            reply_markup=get_devices_selection_keyboard(devices),
            parse_mode="HTML"
        )
        
    finally:
        db.close()


async def select_device_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle device selection from list"""
    query = update.callback_query
    await query.answer()
    
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.edit_message_text("❌ Device not found")
            return
        
        user = db.query(User).filter(User.id == device.user_id).first()
        emoji = get_device_emoji(device.device_type)
        status = "✅ Active" if device.is_active else "❌ Inactive"
        
        from bot.config import VPN_PRICE_PER_DAY
        days_left = int(user.balance / VPN_PRICE_PER_DAY)
        
        message = (
            f"{emoji} <b>{device.name}</b>\n"
            f"Type: {device.device_type}\n"
            f"Status: {status}\n"
            f"Days left: <b>{days_left}</b>\n"
            f"Balance: <b>{user.balance:.2f}¥</b>"
        )
        
        await query.edit_message_text(
            message,
            reply_markup=get_device_actions_keyboard(device.id),
            parse_mode="HTML"
        )
        
    finally:
        db.close()


async def add_device_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add new device - select type"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        active_count = DeviceService.get_active_devices_count(user.id)
        
        if active_count >= 6:
            await update.message.reply_text(
                "❌ <b>Device limit reached (6)</b>\n\n"
                "Remove unused devices to add new ones.",
                parse_mode="HTML"
            )
            return
        
        await update.message.reply_text(
            "📱 <b>Select device type:</b>",
            reply_markup=get_device_type_keyboard(),
            parse_mode="HTML"
        )
        
    finally:
        db.close()


async def handle_device_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle device name input"""
    if not context.user_data.get('awaiting_device_name'):
        return
    
    user_data = update.effective_user
    device_name = update.message.text.strip()
    
    # Check length
    if len(device_name) > 50:
        await update.message.reply_text("❌ Name is too long (max 50 characters)")
        return
    
    if len(device_name) < 2:
        await update.message.reply_text("❌ Name is too short (min 2 characters)")
        return
    
    # Device name can contain letters, numbers and spaces
    # But should not start/end with spaces (already handled by .strip())
    
    # Check that it's not only special characters
    if not any(c.isalnum() for c in device_name):
        await update.message.reply_text("❌ Name must contain at least one letter or number")
        return
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        
        # Get selected device type
        device_type = context.user_data.get('device_type_selected', 'custom')
        
        # Create device with entered name and type
        device = DeviceService.create_device(user.id, device_name, device_type)
        
        if device:
            emoji = get_device_emoji(device.device_type)
            await update.message.reply_text(
                f"✅ <b>Device created!</b>\n\n"
                f"{emoji} Name: <b>{device.name}</b>\n"
                f"Type: <b>{device.device_type}</b>",
                parse_mode="HTML"
            )
            logger.info(f"✅ Device '{device.name}' ({device.device_type}) created for user {user_data.id}")
        else:
            await update.message.reply_text(
                "❌ Error creating device. Try again later."
            )
        
        context.user_data['awaiting_device_name'] = False
        context.user_data['device_type_selected'] = None
        
    finally:
        db.close()
