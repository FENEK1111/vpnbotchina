import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models import SessionLocal, User, Payment, PaymentScreenshot
from bot.keyboards.main_menu import get_subscription_menu_keyboard
from bot.config import ALIPAY_AMOUNT_OPTIONS, ADMIN_ID
from datetime import datetime

logger = logging.getLogger(__name__)


async def show_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user profile/balance"""
    user_data = update.effective_user
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_data.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        message = (
            f"👤 <b>Your Profile</b>\n\n"
            f"Name: <b>{user.first_name}</b>\n"
            f"Username: @{user.username}\n"
            f"ID: <code>{user.telegram_id}</code>\n\n"
            f"💰 <b>Balance:</b> <code>{user.balance:.2f}¥</code>\n"
            f"📅 <b>Created:</b> {user.created_at.strftime('%d.%m.%Y')}\n"
        )
        
        await update.message.reply_text(
            message,
            parse_mode="HTML",
            reply_markup=get_subscription_menu_keyboard()
        )
        
    finally:
        db.close()

async def add_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle balance top-up - select amount"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            return
        
        # Create keyboard with available amounts
        keyboard = []
        for amount in ALIPAY_AMOUNT_OPTIONS:
            keyboard.append([
                InlineKeyboardButton(f"¥{amount}", callback_data=f"alipay_amount_{amount}")
            ])
        
        keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="account")])
        
        message = (
            f"💳 <b>Top-up Balance via Alipay</b>\n\n"
            f"Select amount to top-up:\n\n"
            f"Current balance: <b>{user.balance:.2f}¥</b>"
        )
        
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    finally:
        db.close()


async def show_alipay_instruction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Alipay instruction for selected amount"""
    query = update.callback_query
    await query.answer()
    
    # Extracting amount from callback_data
    amount_str = query.data.replace("alipay_amount_", "")
    amount_cny = int(amount_str)
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            return
        
        # Store amount in context for later use when photo is sent
        context.user_data['payment_amount'] = amount_cny
        
        # Create instruction with admin Steam ID
        instruction_text = f"""
✅ <b>Steam Top-up Instructions</b>

<b>Amount to top-up:</b> <code>¥{amount_cny}</code>
<b>Your current balance:</b> <code>{user.balance:.2f}¥</code>

━━━━━━━━━━━━━━━━━━━

<b>📱 Step 1: Open Alipay App</b>
• Launch Alipay application on your smartphone
• Make sure you have sufficient funds in your account

<b>💳 Step 2: Go to Transfers/Recharges</b>
• Tap on "Recharge" or "Transfer Money"
• Select "Game Recharge" → "Steam"

<b>🎮 Step 3: Enter Steam Account</b>
• Use the Steam ID sent below 👇
• Copy and enter it in Alipay form
• Amount: <b>¥{amount_cny}</b>

<b>💰 Step 4: Complete Payment</b>
• Enter amount: <b>¥{amount_cny}</b>
• Select your Alipay payment method
• Click "Confirm Payment"

<b>✅ Step 5: Send Screenshot</b>
• Take a screenshot showing:
  ✓ Amount paid (¥{amount_cny})
  ✓ Time of payment
  ✓ Transaction status (Success/Completed)
• Send the screenshot below 👇

━━━━━━━━━━━━━━━━━━━

<b>⏱️ Timeline:</b>
Screenshot received → Admin reviews → Your balance updated (2-5 minutes)

<b>📝 Important:</b>
✓ Screenshot must clearly show amount and timestamp
✓ Keep the screenshot as proof
✓ Admin will verify and top-up your VPN account

<b>❌ Next Step:</b>
📸 <b>Please send the payment screenshot below</b>
        """
        
        # Create keyboard for sending photo
        keyboard = [
            [InlineKeyboardButton("❓ Need Help", callback_data="help")],
            [InlineKeyboardButton("◀️ Back", callback_data="add_balance")],
        ]
        
        await query.edit_message_text(
            instruction_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Send Steam ID as separate message for easy copying
        await query.message.reply_text(
            f"`{ADMIN_ID}`",
            parse_mode="MarkdownV2"
        )
        
        logger.info(f"✅ Alipay instruction shown to {user.telegram_id}: ¥{amount_cny}")
        
    except Exception as e:
        logger.error(f"❌ Error showing instruction: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again later.")
    finally:
        db.close()


async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle payment screenshot upload from user"""
    
    if not update.message.photo:
        await update.message.reply_text("❌ Please send a photo of the payment receipt")
        return
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        # Check if user is in payment flow
        if 'payment_amount' not in context.user_data:
            await update.message.reply_text(
                "⚠️ Please select an amount to top-up first\n\n"
                "Go to: My Balance → Top-up ¥ → Select amount → Follow instructions"
            )
            return
        
        amount = context.user_data['payment_amount']
        
        # Get the photo file_id (highest quality)
        photo_file_id = update.message.photo[-1].file_id
        
        # Create payment screenshot record
        screenshot = PaymentScreenshot(
            user_id=user.id,
            photo_file_id=photo_file_id,
            amount=amount,
            status='pending',
            created_at=datetime.utcnow()
        )
        db.add(screenshot)
        db.commit()
        db.refresh(screenshot)
        
        # Send confirmation to user
        await update.message.reply_text(
            f"✅ <b>Payment Screenshot Received!</b>\n\n"
            f"Amount: <b>¥{amount}</b>\n"
            f"Status: ⏳ Waiting for admin verification\n\n"
            f"<i>Admin will review your payment within 5 minutes and top-up your account</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
            ])
        )
        
        # Send screenshot to admin
        admin_message_text = (
            f"📸 <b>Payment Screenshot Received</b>\n\n"
            f"👤 User: <b>{user.first_name}</b> (@{user.username})\n"
            f"🆔 ID: <code>{user.telegram_id}</code>\n"
            f"💰 Amount: <b>¥{amount}</b>\n"
            f"📅 Received: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"<b>Action:</b> Review screenshot and press buttons below"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve & Top-up", callback_data=f"approve_payment_{screenshot.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_payment_{screenshot.id}")
            ]
        ]
        
        if ADMIN_ID:
            try:
                admin_msg = await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=photo_file_id,
                    caption=admin_message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Store admin message ID for later updates
                screenshot.admin_message_id = admin_msg.message_id
                db.commit()
                
                logger.info(f"📸 Screenshot sent to admin for user {user.telegram_id}: ¥{amount}")
            except Exception as e:
                logger.error(f"❌ Failed to send screenshot to admin: {e}")
        
    except Exception as e:
        logger.error(f"❌ Error handling payment screenshot: {e}")
        await update.message.reply_text("❌ An error occurred while processing your screenshot")
    finally:
        db.close()


async def approve_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin approves payment and enters top-up amount"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_caption("❌ You don't have permission to approve payments")
        return
    
    screenshot_id = int(query.data.replace("approve_payment_", ""))
    
    db = SessionLocal()
    try:
        screenshot = db.query(PaymentScreenshot).filter(PaymentScreenshot.id == screenshot_id).first()
        if not screenshot:
            await query.edit_message_caption("❌ Payment record not found")
            return
        
        # Store approval in context
        context.user_data['approving_screenshot_id'] = screenshot_id
        context.user_data['approving_user_id'] = screenshot.user_id
        context.user_data['approving_amount'] = screenshot.amount
        
        # Ask admin for top-up amount
        await query.edit_message_caption(
            f"✅ <b>Approval Mode</b>\n\n"
            f"User ID: {screenshot.user_id}\n"
            f"Paid Amount: ¥{screenshot.amount}\n\n"
            f"<b>Enter the amount to top-up:</b>\n"
            f"<i>(Reply with a number, e.g., 50)</i>",
            parse_mode="HTML"
        )
        
        logger.info(f"⏳ Admin {ADMIN_ID} is approving payment {screenshot_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in approve payment: {e}")
        await query.edit_message_caption("❌ An error occurred")
    finally:
        db.close()


async def reject_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin rejects payment"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_caption("❌ You don't have permission to reject payments")
        return
    
    screenshot_id = int(query.data.replace("reject_payment_", ""))
    
    db = SessionLocal()
    try:
        screenshot = db.query(PaymentScreenshot).filter(PaymentScreenshot.id == screenshot_id).first()
        if not screenshot:
            await query.edit_message_caption("❌ Payment record not found")
            return
        
        screenshot.status = 'rejected'
        screenshot.processed_at = datetime.utcnow()
        db.commit()
        
        user = screenshot.user
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"❌ <b>Payment Rejected</b>\n\n"
                    f"Amount: ¥{screenshot.amount}\n"
                    f"Reason: Please contact admin for details\n\n"
                    f"💬 Please try again or contact support"
                ),
                parse_mode="HTML"
            )
        except:
            pass
        
        await query.edit_message_caption(
            f"❌ <b>Payment Rejected</b>\n\n"
            f"User {user.first_name} ({user.telegram_id}) has been notified",
            parse_mode="HTML"
        )
        
        logger.info(f"❌ Payment {screenshot_id} rejected by admin")
        
    except Exception as e:
        logger.error(f"❌ Error in reject payment: {e}")
        await query.edit_message_caption("❌ An error occurred")
    finally:
        db.close()


async def finalize_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin's top-up amount input and finalize payment"""
    
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You don't have permission")
        return
    
    # Check if we're in approval mode
    if 'approving_screenshot_id' not in context.user_data:
        await update.message.reply_text("⚠️ Not in approval mode. Go back and approve a payment first")
        return
    
    try:
        topup_amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number")
        return
    
    db = SessionLocal()
    try:
        screenshot_id = context.user_data['approving_screenshot_id']
        user_id = context.user_data['approving_user_id']
        
        # Get user and screenshot
        user = db.query(User).filter(User.id == user_id).first()
        screenshot = db.query(PaymentScreenshot).filter(PaymentScreenshot.id == screenshot_id).first()
        
        if not user or not screenshot:
            await update.message.reply_text("❌ User or payment not found")
            return
        
        # Update user balance
        user.balance += topup_amount
        
        # Mark screenshot as approved
        screenshot.status = 'approved'
        screenshot.processed_at = datetime.utcnow()
        
        # Create payment record
        payment = Payment(
            user_id=user.id,
            amount=topup_amount,
            status='completed',
            payment_system='steam',
            transaction_id=f"steam_manual_{screenshot.id}",
            created_at=datetime.utcnow()
        )
        db.add(payment)
        db.commit()
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"✅ <b>Payment Approved & Completed!</b>\n\n"
                    f"💰 Amount: <b>¥{topup_amount}</b>\n"
                    f"✓ Status: Confirmed\n\n"
                    f"Your balance: <b>¥{user.balance:.2f}</b>\n\n"
                    f"🎉 You can now use VPN!"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
                ])
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        # Confirm to admin
        await update.message.reply_text(
            f"✅ <b>Payment Completed!</b>\n\n"
            f"User: {user.first_name} ({user.telegram_id})\n"
            f"Top-up Amount: ¥{topup_amount}\n"
            f"New Balance: ¥{user.balance:.2f}\n\n"
            f"User has been notified",
            parse_mode="HTML"
        )
        
        # Clear context
        del context.user_data['approving_screenshot_id']
        del context.user_data['approving_user_id']
        del context.user_data['approving_amount']
        
        logger.info(f"✅ Payment finalized: User {user.telegram_id} topped up ¥{topup_amount}")
        
    except Exception as e:
        logger.error(f"❌ Error finalizing payment: {e}")
        await update.message.reply_text("❌ An error occurred while finalizing payment")
    finally:
        db.close()


async def check_payment_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check payment status"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            return
        
        # Get user's last payment
        last_payment = db.query(Payment).filter(
            Payment.user_id == user.id
        ).order_by(Payment.created_at.desc()).first()
        
        if not last_payment:
            message = "❌ You have no payments"
        else:
            status_emoji = {
                'pending': '⏳',
                'completed': '✅',
                'failed': '❌'
            }.get(last_payment.status, '❓')
            
            message = (
                f"{status_emoji} <b>Last Payment Status</b>\n\n"
                f"Amount: <b>¥{last_payment.amount}</b>\n"
                f"Status: <b>{last_payment.status}</b>\n"
                f"Date: {last_payment.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Your current balance: <b>¥{user.balance:.2f}</b>"
            )
        
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="account")]
            ])
        )
        
    finally:
        db.close()
