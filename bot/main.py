import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest
from sqlalchemy import inspect, text
import shutil
import sys
import os
from datetime import datetime
from bot.config import TELEGRAM_BOT_TOKEN, DEBUG, ADMIN_ID, DATABASE_URL
from bot.handlers.start import start_handler
from bot.keyboards.main_menu import get_main_menu_keyboard, get_device_actions_keyboard, get_confirm_delete_keyboard, get_device_type_keyboard, get_settings_keyboard, get_devices_for_rename_keyboard, get_devices_selection_keyboard
from database.models import SessionLocal, User, Device, Subscription
from bot.handlers.devices import show_devices_handler, add_device_handler, handle_device_name_input, select_device_handler
from bot.handlers.account import show_account_handler, add_balance_handler, check_payment_status_handler
from bot.handlers.referral import show_referral_program_handler
from bot.services.notification_service import NotificationService
from bot.services.device_service import DeviceService
from bot.services.subscription_service import SubscriptionService
from bot.services.referral_service import ReferralService, REFERRAL_BONUS
from bot.services.vpn_service import marzban_service
from bot.services.payment_service import PaymentService
from bot.jobs.scheduler import setup_scheduler
from database.models import Base, engine

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG if DEBUG else logging.INFO
)
logger = logging.getLogger(__name__)


def apply_migrations():
    """Apply necessary database migrations with error handling"""
    try:
        inspector = inspect(engine)
        
        # Check if devices table exists
        if 'devices' not in inspector.get_table_names():
            logger.warning("⚠️ Table 'devices' not found")
            return True
        
        # Get list of columns
        columns = inspector.get_columns('devices')
        column_names = [col['name'] for col in columns]
        
        if 'device_type' not in column_names:
            logger.info("🔄 Necessary migrations detected. Creating database backup...")
            
            # Create backup before migration
            try:
                db_path = DATABASE_URL.replace('sqlite:///', '').replace('sqlite:///', './').strip()
                if not db_path.startswith('/'):
                    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', db_path)
                
                if os.path.exists(db_path):
                    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
                    os.makedirs(backup_dir, exist_ok=True)
                    
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_path = os.path.join(backup_dir, f'vpn_bot_backup_{timestamp}.db')
                    
                    shutil.copy2(db_path, backup_path)
                    logger.info(f"💾 Backup created: {backup_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to create backup (continuing): {e}")
            
            logger.info("🔄 Adding missing 'device_type' column to 'devices' table...")
            
            try:
                with engine.begin() as conn:  # begin() automatically commits on success
                    conn.execute(text(
                        "ALTER TABLE devices ADD COLUMN device_type VARCHAR DEFAULT 'custom'"
                    ))
                logger.info("✅ Column 'device_type' added successfully")
            except Exception as alter_error:
                logger.error(f"❌ Error adding column: {alter_error}")
                # Check if already added
                try:
                    inspector = inspect(engine)
                    columns = inspector.get_columns('devices')
                    column_names = [col['name'] for col in columns]
                    if 'device_type' in column_names:
                        logger.info("✅ Column already exists (possible error on re-adding)")
                        return True
                except:
                    pass
                logger.error("❌ Migration failed - Database may be corrupted!")
                return False
        else:
            logger.debug("✅ All required columns exist")
            return True
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Critical error applying migrations: {e}")
        return False


async def cleanup_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to cleanup invalid devices"""
    user_id = update.effective_user.id
    
    # Check that this is an administrator
    if ADMIN_ID and user_id != ADMIN_ID:
        await update.message.reply_text("❌ You don't have permission to execute this command")
        return
    
    if not ADMIN_ID:
        await update.message.reply_text("❌ ADMIN_ID not set in config")
        return
    
    await update.message.reply_text("🔄 Starting cleanup of invalid devices...")
    
    deleted_count = DeviceService.cleanup_invalid_devices()
    
    await update.message.reply_text(
        f"✅ Cleanup completed\n"
        f"Deleted invalid devices: {deleted_count}"
    )
    logger.info(f"🧹 Administrator {user_id} launched cleanup. Deleted: {deleted_count}")


def main():
    """Running main bot loop"""
    
    # Create tables in DB
    Base.metadata.create_all(bind=engine)
    logger.info("✅ DB initialized")
    
    # Apply migrations (CRITICAL - must succeed)
    logger.info("🔧 Checking DB migrations...")
    migration_success = apply_migrations()
    
    if not migration_success:
        logger.error("❌ CRITICAL ERROR: Failed to apply migrations!")
        logger.error("❌ Bot cannot continue. Check DB and logs.")
        logger.error("❌ Recovery command: python migrate_db.py --restore backups/[latest_backup].db")
        sys.exit(1)
    
    logger.info("✅ All migrations applied successfully")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register error handler
    async def error_handler(update, context):
        """Error handling"""
        error_str = str(context.error)
        
        # Ignore "Message is not modified" error - this is normal
        if "Message is not modified" in error_str:
            logger.debug("⚠️ Message not changed (normal Telegram API error)")
            return
        
        logger.error(f"❌ Error: {error_str}")
    
    application.add_error_handler(error_handler)
    
    # Initialize notification service
    notification_service = NotificationService(application.bot)
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("cleanup", cleanup_handler))
    
    # Text message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    # Handler for uploading payment receipt photos
    from bot.handlers.account import handle_payment_screenshot
    application.add_handler(MessageHandler(
        filters.PHOTO,
        handle_payment_screenshot
    ))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_callbacks))
    
    # Set up task scheduler
    setup_scheduler(application, notification_service)
    
    # Start polling
    logger.info("🤖 Bot started. Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=['message', 'callback_query'])


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Handling text messages"""
    text = update.message.text
    
    # Handle admin amount input during payment top-up
    if update.effective_user.id == ADMIN_ID and context.user_data.get('approving_screenshot_id'):
        from bot.handlers.account import finalize_payment_handler
        await finalize_payment_handler(update, context)
        return
    
    # Handle input for new name during renaming
    if context.user_data.get('awaiting_device_rename'):
        await handle_rename_input(update, context)
        return
    
    if text == "📱 My Devices":
        await show_devices_handler(update, context)
    elif text == "💰 My Balance":
        await show_account_handler(update, context)
    elif text == "➕ Add Device":
        await add_device_handler(update, context)
    elif text == "✏️ Rename":
        await show_rename_device_list(update, context)
    elif text == "❓ Help":
        await show_help_handler(update, context)
    elif text == "⚙️ Settings":
        await show_settings_handler(update, context)
    elif text == "🎁 Referral Program":
        await show_referral_program_handler(update, context)
    elif text == "Создать профиль" or text == "Create Profile":
        # Handler for both variants (Russian and English)
        await handle_create_profile_button(update, context)
    elif context.user_data.get('awaiting_device_name'):
        await handle_device_name_input(update, context)


async def back_to_devices_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Return to device list from device information"""
    from telegram import error as telegram_error
    query = update.callback_query
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await query.answer("❌ User not found")
            return
        
        devices = DeviceService.get_user_devices(user.id)
        active_count = DeviceService.get_active_devices_count(user.id)
        
        if not devices:
            await query.edit_message_text("📱 You have no devices. Add your first device!")
            return
        
        # Show first device from list
        device = devices[0]
        from bot.config import VPN_PRICE_PER_DAY
        status = "✅ Active" if device.is_active else "❌ Inactive"
        days_left = int(user.balance / VPN_PRICE_PER_DAY)
        
        device_message = (
            f"📱 <b>{device.name}</b>\n"
            f"Status: {status}\n"
            f"Days left: <b>{days_left}</b>\n"
            f"Balance: <b>{user.balance:.2f}¥</b>"
        )
        
        try:
            await query.edit_message_text(
                device_message,
                reply_markup=get_device_actions_keyboard(device.id),
                parse_mode="HTML"
            )
        except telegram_error.BadRequest as e:
            # Message not changed - ignore error
            if "not modified" not in str(e).lower():
                logger.error(f"❌ Error editing message: {e}")
                raise
        
        await query.answer()
        
    finally:
        db.close()


async def handle_create_profile_button(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for 'Create Profile' button from menu"""
    user_data = update.effective_user
    db = SessionLocal()
    
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            user = User(
                telegram_id=user_data.id,
                username=user_data.username,
                first_name=user_data.first_name,
                balance=5.0  # bonus on creation (1 week VPN)
            )
            db.add(user)
            db.commit()
            logger.info(f"✅ Profile created with ¥5 bonus: {user_data.id}")
            
            # Referral program handling
            referrer_id = context.user_data.get('referrer_id') if context.user_data else None
            if referrer_id:
                try:
                    referrer = db.query(User).filter(User.id == referrer_id).first()
                    if referrer:
                        result = ReferralService.create_referral(referrer_id, user.id)
                        if result:
                            logger.info(f"🎁 Referral program activated: user_id={user.id} from referrer_id={referrer_id}")
                            await update.message.reply_text(
                                f"🎉 <b>Thanks for registering via {referrer.first_name}'s referral!</b>\n\n"
                                f"You both received bonuses!",
                                parse_mode="HTML"
                            )
                        else:
                            logger.warning(f"⚠️ Failed to create referral for user_id={user.id}")
                except Exception as e:
                    logger.error(f"❌ Error while processing referral bonus: {e}")
        else:
            # ⚠️ Profile already exists, this is an abuse attempt
            logger.warning(
                f"⚠️ ABUSE ATTEMPT: User {user_data.id} ({user_data.first_name}) "
                f"trying to create profile but profile already exists. "
                f"Balance: ¥{user.balance:.2f}"
            )
            await update.message.reply_text(
                "ℹ️ You already have a profile!\n\n"
                "Click 💰 My Balance to see your account"
            )
            return
        
        # Create general subscription for user
        SubscriptionService.create_subscription(user.id)
        
        # Send welcome message with menu
        welcome_text = (
            f"👋 <b>Welcome, {user_data.first_name}!</b>\n\n"
            f"✨ <b>You've received a ¥5 bonus</b> (1 week free VPN)\n\n"
            f"💰 Your balance: <b>¥{user.balance:.2f}</b>"
        )
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
        
    finally:
        db.close()


async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    """Handling callback buttons"""
    query = update.callback_query
    callback_data = query.data
    
    if callback_data == "create_profile" or callback_data.startswith("create_profile_ref_"):
        # Create profile when inline button is pressed
        await query.answer()
        db = SessionLocal()
        try:
            user_data = update.effective_user
            existing_user = db.query(User).filter(User.telegram_id == user_data.id).first()
            
            if not existing_user:
                # Create new profile
                new_user = User(
                    telegram_id=user_data.id,
                    username=user_data.username,
                    first_name=user_data.first_name,
                    balance=5.0
                )
                db.add(new_user)
                db.commit()
                logger.info(f"✅ Profile created: {user_data.id}")
                
                SubscriptionService.create_subscription(new_user.id)
                
                welcome = (
                    f"👋 <b>Welcome, {user_data.first_name}!</b>\n\n"
                    f"✨ <b>You've received a ¥5 bonus</b> (1 week free VPN)\n\n"
                    f"💰 Your balance: <b>¥{new_user.balance:.2f}</b>\n\n"
                    f"Now you can add a device or top-up your account."
                )
                await query.edit_message_text(welcome, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
            else:
                await query.edit_message_text("ℹ️ You already have a profile")
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            try:
                await query.edit_message_text(f"❌ Error: {str(e)[:50]}")
            except:
                pass
        finally:
            db.close()
    elif callback_data == "add_balance":
        # New handler for WeChat top-up (direct to amounts)
        from bot.handlers.account import wechat_amount_handler
        await wechat_amount_handler(update, context)
    elif callback_data.startswith("wechat_initiate_"):
        # User initiated WeChat payment
        from bot.handlers.account import wechat_initiate_payment_handler
        await wechat_initiate_payment_handler(update, context)
    elif callback_data.startswith("admin_confirm_wechat_"):
        # Admin confirmed WeChat payment
        from bot.handlers.account import admin_confirm_wechat_handler
        await admin_confirm_wechat_handler(update, context)
    elif callback_data.startswith("admin_decline_wechat_"):
        # Admin declined WeChat payment
        from bot.handlers.account import admin_decline_wechat_handler
        await admin_decline_wechat_handler(update, context)
    elif callback_data.startswith("user_confirm_payment_"):
        # User confirmed payment and system notifies admin
        from bot.handlers.account import user_final_payment_confirmation
        await user_final_payment_confirmation(update, context)
    elif callback_data.startswith("admin_complete_payment_"):
        # Admin completed payment after verifying balance
        from bot.handlers.account import admin_complete_payment_handler
        await admin_complete_payment_handler(update, context)
    elif callback_data.startswith("admin_cancel_payment_"):
        # Admin cancelled payment
        from bot.handlers.account import admin_cancel_payment_handler
        await admin_cancel_payment_handler(update, context)
    elif callback_data.startswith("alipay_amount_"):
        # Show Alipay instructions for selected amount
        from bot.handlers.account import show_alipay_instruction_handler
        await show_alipay_instruction_handler(update, context)
    elif callback_data.startswith("approve_payment_"):
        # Admin approves payment and ready to enter amount
        from bot.handlers.account import approve_payment_handler
        await approve_payment_handler(update, context)
    elif callback_data.startswith("reject_payment_"):
        # Admin rejects payment
        from bot.handlers.account import reject_payment_handler
        await reject_payment_handler(update, context)
    elif callback_data.startswith("check_payment_"):
        # Check payment status
        from bot.handlers.account import check_payment_status_handler
        await check_payment_status_handler(update, context)
    elif callback_data.startswith("device_type_"):
        await handle_device_type_selection(update, context)
    elif callback_data.startswith("select_device_"):
        await select_device_handler(update, context)
    elif callback_data.startswith("settings_"):
        await handle_settings_selection(update, context)
    elif callback_data.startswith("device_info_"):
        await handle_device_info(update, context)
    elif callback_data.startswith("device_config_"):
        await handle_device_config(update, context)
    elif callback_data.startswith("rename_select_"):
        await handle_rename_device_selected(update, context)
    elif callback_data.startswith("device_delete_"):
        await handle_device_delete(update, context)
    elif callback_data.startswith("confirm_delete_"):
        await handle_confirm_delete(update, context)
    elif callback_data == "back_to_devices":
        await back_to_devices_handler(update, context)
    elif callback_data == "cancel":
        await query.answer()
        await query.delete_message()


async def handle_device_type_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle device type selection"""
    query = update.callback_query
    callback_data = query.data
    device_type = callback_data.replace("device_type_", "")
    
    await query.answer()
    
    # Save selected type
    context.user_data['device_type_selected'] = device_type
    context.user_data['awaiting_device_name'] = True
    
    # Ask for name for all types
    await query.edit_message_text(
        f"📱 <b>Enter a name for {device_type}:</b>\n\n"
        f"Examples: iPhone, MacBook, Android, etc. in English.",
        parse_mode="HTML"
    )


async def handle_device_info(update, context: ContextTypes.DEFAULT_TYPE):
    """Show device information"""
    query = update.callback_query
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.answer("❌ Device not found")
            return
        
        user = db.query(User).filter(User.id == device.user_id).first()
        if not user:
            await query.answer("❌ User not found")
            return
        
        from bot.config import VPN_PRICE_PER_DAY
        status = "✅ Active" if device.is_active else "❌ Inactive"
        days_left = int(user.balance / VPN_PRICE_PER_DAY)
        
        info_text = (
            f"📱 <b>Device Information</b>\n\n"
            f"<b>Name:</b> {device.name}\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Days left:</b> {days_left}\n"
            f"<b>Balance:</b> {user.balance:.2f}¥"
        )
        
        try:
            await query.edit_message_text(
                info_text,
                reply_markup=get_device_actions_keyboard(device_id),
                parse_mode="HTML"
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        
        await query.answer()
    finally:
        db.close()


async def handle_device_config(update, context: ContextTypes.DEFAULT_TYPE):
    """Send device configuration"""
    query = update.callback_query
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.answer("❌ Device not found")
            return
        
        # Check device activity
        if not device.is_active:
            await query.answer("❌ Device is not active")
            return
        
        user = db.query(User).filter(User.id == device.user_id).first()
        
        # Check balance
        if user.balance <= 0:
            await query.answer("❌ Insufficient funds. Top-up your balance.")
            return
        
        # Check/create subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).first()
        
        if not subscription:
            # Create subscription if not exists
            subscription = Subscription(
                user_id=user.id,
                device_id=None,
                balance=0,
                days_remaining=0,
                expires_at=None,
                is_active=True
            )
            db.add(subscription)
            db.commit()
            logger.info(f"✅ Subscription auto-created for user {user.id}")
        
        if not subscription.is_active:
            await query.answer("❌ Subscription is not active. Top-up balance.")
            return
        
        # Get config from Marzban
        config = marzban_service.get_user_config_string(device.marzban_username, protocol="vless")
        
        if not config:
            # Try to get any available link
            links = marzban_service.get_user_links(device.marzban_username)
            if links:
                if isinstance(links, dict):
                    config = links.get("vless") or links.get("shadowsocks") or str(links)
                else:
                    config = str(links)
        
        if config:
            await query.answer()
            
            # Send instruction
            instruction_text = (
                f"🔐 <b>Configuration for {device.name}</b>\n\n"
                f"💡 <b>Instructions:</b>\n"
                f"1. Copy the link below (in code)\n"
                f"2. Open VPN app on your device\n"
                f"3. Click \"Import\" or paste the link\n"
                f"4. Connect to VPN\n\n"
                f"<b>Protocol:</b> VLESS\n"
            )
            
            await query.message.reply_text(
                instruction_text,
                parse_mode="HTML"
            )
            
            # Send the link as code (for easy copying)
            await query.message.reply_text(
                f"<code>{config}</code>",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Config sent for device {device.name}")
        else:
            await query.answer("⚠️ Failed to get configuration. Try again later.", show_alert=True)
            logger.error(f"❌ Error getting config for {device.marzban_username}")
    finally:
        db.close()


async def handle_device_delete(update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm device deletion"""
    query = update.callback_query
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.answer("❌ Device not found")
            return
        
        confirm_text = (
            f"⚠️ <b>Are you sure?</b> \n \n"
            f"Deleting device <b>{device.name}</b> is irreversible. \n"
            f"Subscription will be cancelled and configuration will be deactivated."
        )
        
        await query.edit_message_text(
            confirm_text,
            reply_markup=get_confirm_delete_keyboard(device_id),
            parse_mode="HTML"
        )
        await query.answer()
    finally:
        db.close()


async def handle_confirm_delete(update, context: ContextTypes.DEFAULT_TYPE):
    """Final device deletion confirmation"""
    query = update.callback_query
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.answer("❌ Device not found")
            return
        
        device_name = device.name
        marzban_username = device.marzban_username
        
        logger.info(f"🔄 Deleting device: {device_name} ({marzban_username})")
        
        # Delete device through service (deletes from Marzban and DB)
        success = DeviceService.delete_device(device_id)
        
        if success:
            success_text = (
                f"✅ <b>Device deleted</b>\n\n"
                f"Configuration '<b>{device_name}</b>' deactivated.\n"

            )
            
            await query.edit_message_text(success_text, parse_mode="HTML")
            await query.answer()
            
            logger.info(f"✅ Device successfully deleted: {device_name} ({marzban_username})")
        else:
            error_text = (
                f"❌ <b>Error deleting</b>\n\n"
                f"Failed to delete device. Try again later.\n"
                f"Check bot logs for details."
            )
            await query.edit_message_text(error_text, parse_mode="HTML")
            await query.answer()
            
            logger.error(f"❌ Error deleting device: {device_name}")
            logger.error(f"❌ Error deleting device: {device_id}")
    finally:
        db.close()


async def show_rename_device_list(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show device list for renaming"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        devices = DeviceService.get_user_devices(user.id)
        
        if not devices:
            await update.message.reply_text(
                "📱 <b>You have no devices</b>\n\n"
                "Add a device to rename it.",
                parse_mode="HTML"
            )
            return
        
        await update.message.reply_text(
            "✏️ <b>Select a device to rename:</b>",
            reply_markup=get_devices_for_rename_keyboard(devices),
            parse_mode="HTML"
        )
        
    finally:
        db.close()


async def handle_rename_device_selected(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle device selection for renaming"""
    query = update.callback_query
    device_id = int(query.data.split("_")[-1])
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            await query.answer("❌ Device not found")
            return
        
        # Save device ID for next step
        context.user_data['rename_device_id'] = device_id
        context.user_data['awaiting_device_rename'] = True
        
        await query.edit_message_text(
            f"✏️ <b>Rename device</b>\n\n"
            f"Current name: <b>{device.name}</b>\n\n"
            f"Enter a new name:",
            parse_mode="HTML"
        )
        await query.answer()
    finally:
        db.close()


async def handle_settings_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings menu selection"""
    query = update.callback_query
    callback_data = query.data
    
    await query.answer()
    
    if callback_data == "settings_notifications":
        text = (
            "🔔 <b>Notifications</b>\n\n"
            "✅ You receive notifications:\n"
            "• 3 days before subscription expires\n"
            "• When balance is low\n\n"
            "Notifications are sent automatically."
        )
    elif callback_data == "settings_language":
        text = (
            "🌐 <b>Language</b>\n\n"
            "🇬🇧 <b>English</b> - current language\n\n"
            "Other languages will be added later."
        )
    
    elif callback_data == "settings_profile":
        user_data = update.effective_user
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.telegram_id == user_data.id).first()
            if user:
                text = (
                    f"👤 <b>Profile</b>\n\n"
                    f"<b>Name:</b> {user.first_name}\n"
                    f"<b>ID:</b> {user.telegram_id}\n"
                    f"<b>Balance:</b> {user.balance:.2f}¥\n"
                    f"<b>Status:</b> {'✅ Active' if user.is_active else '❌ Inactive'}\n"
                    f"<b>Registration date:</b> {user.created_at.strftime('%d.%m.%Y')}"
                )
            else:
                text = "❌ Profile not found"
        finally:
            db.close()
    elif callback_data == "settings_about":
        text = (
            "ℹ️ <b>About the bot</b>\n\n"
            "📱 <b>VPN Bot</b>\n"
            "Fast and affordable VPN service\n\n"
            "⚡ <b>Features:</b>\n"
            "• Device management (max 6)\n"
            "• Automatic top-up\n"
            "• Multiple configurations\n"
            "• 24/7 support\n\n"
            "💳 <b>Price:</b> 20¥ per month (0.67¥ per day) per device\n"
        )
    else:
        text = "❌ Unknown option"
    
    await query.edit_message_text(text, parse_mode="HTML")


async def handle_rename_input(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new device name input"""
    if not context.user_data.get('awaiting_device_rename'):
        return
    
    new_name = update.message.text.strip()
    device_id = context.user_data.get('rename_device_id')
    
    # Length check
    if len(new_name) > 50:
        await update.message.reply_text("❌ Name too long (max 50 characters)")
        return
    
    if len(new_name) < 2:
        await update.message.reply_text("❌ Name too short (min 2 characters)")
        return
    
    # Check no special characters only
    if not any(c.isalnum() for c in new_name):
        await update.message.reply_text("❌ Name must contain at least one letter or number")
        return
    
    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        
        if not device:
            await update.message.reply_text("❌ Device not found")
            context.user_data['awaiting_device_rename'] = False
            return
        
        old_name = device.name
        
        # Update name in DB
        if DeviceService.rename_device(device_id, new_name):
            await update.message.reply_text(
                f"✅ <b>Device renamed!</b>\n\n"
                f"Was: <b>{old_name}</b>\n"
                f"Now: <b>{new_name}</b>",
                parse_mode="HTML"
            )
            logger.info(f"✅ Device renamed: '{old_name}' → '{new_name}' (ID: {device_id})")
        else:
            await update.message.reply_text(
                "❌ Error renaming. Try again later."
            )
        
        context.user_data['awaiting_device_rename'] = False
        context.user_data['rename_device_id'] = None
        
    finally:
        db.close()


async def show_settings_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Show settings menu"""
    settings_text = (
        "⚙️ <b>Settings</b>\n\n"
        "Select what you want to configure:"
    )
    
    await update.message.reply_text(
        settings_text,
        reply_markup=get_settings_keyboard(),
        parse_mode="HTML"
    )


async def show_help_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    help_text = (
        "❓ <b>Help and Usage Guide</b>\n\n"
        "📱 <b>My Devices</b> - manage VPN devices\n"
        "💰 <b>My Balance</b> - view and top-up balance\n"
        "➕ <b>Add Device</b> - add new device (max 6)\n\n"
        "<b>Price:</b> 20¥ per month (0.67¥ per day) per device\n"
        "<b>Reminder:</b> You'll get notified 3 days before subscription expires\n\n"

        "📖 <a href=\"https://www.worddvpn.tech/instruction.html\"><b>Installation instructions</b></a>\n\n"
        "Have questions or suggestions? <a href=\"https://t.me/wordvpn_support_bot\">Contact us</a>"
    )
    
    await update.message.reply_text(help_text, parse_mode="HTML")


if __name__ == '__main__':
    main()
