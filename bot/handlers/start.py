import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models import SessionLocal, User
from bot.keyboards.main_menu import get_main_menu_keyboard
from bot.services.referral_service import ReferralService

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for /start command
    Checks if profile exists and shows welcome message
    Supports referral links: /start ref_<user_id>
    """
    user_data = update.effective_user
    chat_id = update.effective_chat.id
    
    # Check for referral parameter
    referrer_id = None
    if context.args and len(context.args) > 0:
        ref_param = context.args[0]
        if ref_param.startswith("ref_"):
            try:
                referrer_id = int(ref_param.replace("ref_", ""))
                logger.info(f"Referral link detected: referrer_id={referrer_id}")
            except (ValueError, IndexError):
                logger.warning(f"Invalid referral parameter format: {ref_param}")
    
    db = SessionLocal()
    try:
        # Check if profile exists
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        
        if not user:
            # Profile not created yet, offer button to create
            welcome_text = (
                f"👋 Hi, <b>{user_data.first_name}</b>!\n\n"
                f"Welcome to <b>WordVPN</b>, a fast and affordable service for your security!\n\n"
                f"🎁 Get <b>3 days FREE VPN</b> when you create a profile!"
            )
            
            # If this is a referral link, add bonus info
            if referrer_id:
                referrer = db.query(User).filter(User.id == referrer_id).first()
                if referrer:
                    welcome_text += f"\n\n🎁 <b>Recommendation from {referrer.first_name}!</b>\nYou both will get bonuses for joining!"
            
            # Build callback_data with referrer_id if it exists
            callback_data = f"create_profile_ref_{referrer_id}" if referrer_id else "create_profile"
            
            inline = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Create Profile", callback_data=callback_data)]
            ])
            
            await update.message.reply_text(
                welcome_text,
                reply_markup=inline,
                parse_mode="HTML"
            )
            
            return
        
        # If profile exists, update name and username if they changed
        user.first_name = user_data.first_name
        user.username = user_data.username
        
        # If this is a referral link and user has no referrer, add one
        if referrer_id:
            if user.referrer_id:
                # ⚠️ ABUSE ATTEMPT: user already invited, trying to use another referral link
                logger.warning(
                    f"⚠️ ABUSE ATTEMPT: User {user.telegram_id} already invited from {user.referrer_id}, "
                    f"trying to use referral link from {referrer_id}"
                )
            else:
                # ⚠️ IMPORTANT: referrer_id is TELEGRAM_ID, not user.id!
                referrer = db.query(User).filter(User.telegram_id == referrer_id).first()
                if referrer:
                    try:
                        is_success, referrer_telegram_id = ReferralService.create_referral(referrer.id, user.id)
                        if is_success:
                            logger.info(f"🎁 Referral program activated for user_id={user.id} from referrer_id={referrer.id}")
                        else:
                            logger.warning(f"⚠️ Failed to create referral for user_id={user.id}")
                    except Exception as e:
                        logger.error(f"❌ Error creating referral bonus: {e}")
        
        db.commit()
        
        welcome_text = (
            f"👋 Hi, <b>{user_data.first_name}</b>!\n\n"
            f"Welcome to <b>WordVPN</b>, a fast and affordable service for your security!\n\n"
            f"🎁 <b>You've received 3 days FREE VPN</b> (2¥)\n\n"
            f"<b>Price:</b> 18¥ per month (0.60¥ per day) per device\n"
            f"<b>Max devices:</b> 6\n"
            f"Current balance: <b>{user.balance:.2f}¥</b>"
        )
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
        
    finally:
        db.close()
