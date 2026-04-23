import logging
from telegram import Update
from telegram.ext import ContextTypes
from database.models import SessionLocal, User
from bot.services.referral_service import ReferralService, REFERRAL_BONUS

logger = logging.getLogger(__name__)


async def show_referral_program_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show referral program"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        # Generate referral link using bot username from context
        bot_username = context.bot.username or "bot"
        referral_link = ReferralService.generate_referral_link(bot_username, user.telegram_id)
        
        # Get statistics
        stats = ReferralService.get_referral_stats(user.id)
        
        message = (
            f"🎁 <b>Referral Program</b>\n\n"
            f"<b>Your referral link:</b>\n"
            f"<code>{referral_link}</code>\n\n"
            f"<b>How does it work?</b>\n"
            f"1. Share your link with friends\n"
            f"2. When a friend clicks your link and creates a profile\n"
            f"3. You get a bonus to your balance: <b>{REFERRAL_BONUS}¥</b>\n\n"
            f"<b>📊 Your Statistics:</b>\n"
            f"• Total invited: <b>{stats['total_referrals']}</b> people\n"
            f"• Earned: <b>{stats['total_earned']:.2f}¥</b>\n"
            f"• Pending: <b>{stats['pending']}</b>\n"
        )
        
        if stats['total_referrals'] > 0:
            message += f"\n<b>💰 Pending amount:</b> {stats['pending_amount']:.2f}¥"
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    finally:
        db.close()


async def show_referral_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of referrals"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        referrals = ReferralService.get_referral_list(user.id)
        
        if not referrals:
            message = "📋 You have no referrals yet"
        else:
            message = "📋 <b>Your Referrals:</b>\n\n"
            for i, ref in enumerate(referrals, 1):
                status = "✅ Paid" if ref['paid'] else "⏳ Pending"
                message += (
                    f"{i}. <b>{ref['username']}</b>\n"
                    f"   Date: {ref['date'].strftime('%d.%m.%Y')}\n"
                    f"   Bonus: {ref['bonus']:.2f}¥ ({status})\n\n"
                )
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    finally:
        db.close()
