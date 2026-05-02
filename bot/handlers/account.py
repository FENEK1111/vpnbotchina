import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models import SessionLocal, User, Payment, PaymentScreenshot, PaymentRequest
from bot.keyboards.main_menu import get_subscription_menu_keyboard
from bot.config import ALIPAY_AMOUNT_OPTIONS, ADMIN_ID, BUFF_ACCOUNT_CREDENTIALS, get_topup_bonus
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
    """Handle balance top-up - WeChat Pay only"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            return
        
        # Create keyboard with available amounts for WeChat
        keyboard = []
        for amount in ALIPAY_AMOUNT_OPTIONS:
            bonus = get_topup_bonus(amount)
            if bonus > 0:
                button_text = f"🛒 ¥{amount} 🎁+¥{bonus} EXTRA"
            else:
                button_text = f"🛒 ¥{amount}"
            
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"wechat_initiate_{amount}")
            ])
        
        keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="account")])
        
        message = (
            f"🛒 <b>WeChat Pay Top-up</b>\n\n"
            f"Select amount to top-up and GET BONUS:\n\n"
            f"<b>🎁 BONUS FOR YOU:</b>\n"
            f"• Buy 50¥ → Get +5¥ EXTRA\n"
            f"• Buy 100¥ → Get +15¥ EXTRA\n"
            f"• Buy 150¥ → Get +30¥ EXTRA\n"
            f"• Buy 200¥ → Get +50¥ EXTRA\n\n"
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
        
        # Calculate bonus
        bonus = get_topup_bonus(amount_cny)
        bonus_line = f"<b>🎁 YOU GET BONUS:</b> +¥{bonus} absolutely FREE!\n" if bonus > 0 else ""
        
        # Create instruction with admin Steam ID
        instruction_text = f"""
✅ <b>Steam Top-up Instructions</b>

<b>Amount to top-up:</b> <code>¥{amount_cny}</code>
{bonus_line}
<b>Total you'll receive:</b> <code>¥{amount_cny + bonus}</code>
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
    """Handle payment screenshot upload from user or QR from admin"""
    
    if not update.message.photo:
        await update.message.reply_text("❌ Please send a photo")
        return
    
    # Check if this is admin sending QR code for WeChat payment
    if update.effective_user.id == ADMIN_ID and 'pending_qr_request_id' in context.user_data:
        await admin_send_qr_handler(update, context)
        return
    
    # Regular user payment screenshot handling
    
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
        
        # Calculate and add top-up bonus
        bonus = get_topup_bonus(int(topup_amount))
        if bonus > 0:
            user.balance += bonus
            bonus_text = f"🎁 <b>YOU GET EXTRA:</b> +¥{bonus} absolutely FREE!\n"
        else:
            bonus_text = ""
        
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
                    f"� You paid: <b>¥{topup_amount}</b>\n"
                    f"{bonus_text}"
                    f"💰 Total in balance: <b>¥{user.balance:.2f}</b>\n\n"
                    f"🎉 Ready to use VPN!"
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
            f"Received: ¥{topup_amount}\n"
            f"{bonus_text}"
            f"New Balance: ¥{user.balance:.2f}\n\n"
            f"✓ User has been notified",
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


# ==================== NEW WeChat Payment Flow ====================

async def payment_method_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбирает метод оплаты"""
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            return
        
        keyboard = [
            [InlineKeyboardButton("💳 Alipay", callback_data="payment_method_alipay")],
            [InlineKeyboardButton("🛒 WeChat Pay", callback_data="payment_method_wechat")],
            [InlineKeyboardButton("◀️ Back", callback_data="account")]
        ]
        
        message = (
            f"💰 <b>Select Payment Method</b>\n\n"
            f"Current balance: <b>{user.balance:.2f}¥</b>\n\n"
            f"Choose your preferred payment option:"
        )
        
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    finally:
        db.close()


async def wechat_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбирает сумму для WeChat платежа"""
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
                InlineKeyboardButton(f"¥{amount}", callback_data=f"wechat_initiate_{amount}")
            ])
        
        keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="payment_method")])
        
        message = (
            f"🛒 <b>WeChat Pay Top-up</b>\n\n"
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


async def wechat_initiate_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Инициировать WeChat платеж - админ должен быть уведомлен"""
    query = update.callback_query
    await query.answer()
    
    # Извлечь сумму из callback_data
    amount_str = query.data.replace("wechat_initiate_", "")
    amount = int(amount_str)
    
    db = SessionLocal()
    try:
        from bot.services.payment_request_service import PaymentRequestService
        
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if not user:
            await query.edit_message_text("❌ User not found")
            return
        
        # Создать payment request
        payment_request = PaymentRequestService.create_request(user.id, amount)
        if not payment_request:
            await query.edit_message_text("❌ Failed to create payment request. Try again.")
            return
        
        # Показать пользователю сообщение что ждем QR
        await query.edit_message_text(
            f"✅ <b>Payment Request Created</b>\n\n"
            f"Amount: <b>¥{amount}</b>\n"
            f"Unique amount to pay: <b>¥{payment_request.unique_amount}</b>\n\n"
            f"⏳ <b>Administrator is sending QR code for payment...</b>\n\n"
            f"We'lll send you QR code in a couple of minutes.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
            ])
        )
        
        # Отправить уведомление админу
        user_info = PaymentRequestService.get_user_info(user.id)
        admin_message_text = (
            f"💳 <b>New WeChat Payment Request</b>\n\n"
            f"👤 User: <b>{user_info['first_name']}</b>\n"
            f"🆔 Username: @{user_info['username']}\n"
            f"📞 User ID: <code>{user_info['telegram_id']}</code>\n"
            f"💰 Requested amount: <b>¥{amount}</b>\n"
            f"🎯 Unique amount: <b>¥{payment_request.unique_amount}</b>\n"
            f"📅 Time: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"<b>Action:</b> Confirm or decline below"
        )
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirm & Send QR",
                    callback_data=f"admin_confirm_wechat_{payment_request.id}"
                ),
                InlineKeyboardButton(
                    "❌ Decline",
                    callback_data=f"admin_decline_wechat_{payment_request.id}"
                )
            ]
        ]
        
        if ADMIN_ID:
            try:
                admin_msg = await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Сохранить admin message ID
                payment_request.admin_message_id = admin_msg.message_id
                db.commit()
                
                logger.info(f"✅ Admin notified for WeChat payment: {payment_request.id}")
            except Exception as e:
                logger.error(f"❌ Failed to notify admin: {e}")
        
    except Exception as e:
        logger.error(f"❌ Error initiating WeChat payment: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again.")
    finally:
        db.close()


async def admin_confirm_wechat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ подтверждает WeChat платежи"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    request_id = int(query.data.replace("admin_confirm_wechat_", ""))
    
    db = SessionLocal()
    try:
        from bot.services.payment_request_service import PaymentRequestService
        
        # Подтвердить запрос
        success = PaymentRequestService.confirm_by_admin(request_id, query.message.message_id)
        if not success:
            await query.edit_message_text("❌ Payment request not found")
            return
        
        # Получить информацию о payment request
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if payment_request:
            user = db.query(User).filter(User.id == payment_request.user_id).first()
            
            # Обновить сообщение админу
            await query.edit_message_text(
                f"✅ <b>WeChat Payment Confirmed</b>\n\n"
                f"User: <b>{user.first_name}</b>\n"
                f"Amount: <b>¥{payment_request.unique_amount}</b>\n\n"
                f"<b>Next step:</b> Send QR code as next message",
                parse_mode="HTML"
            )
            
            # 📤 СРАЗУ отправить данные аккаунта админу
            import random
            account_id = random.randint(1, 10)
            account_creds = BUFF_ACCOUNT_CREDENTIALS.get(account_id, {})
            
            if account_creds:
                admin_account_msg = (
                    f"📤 <b>Payment Confirmed - Account Credentials</b>\n\n"
                    f"User: <b>{user.first_name}</b> (ID: {user.telegram_id})\n"
                    f"Amount: <b>¥{payment_request.unique_amount}</b>\n"
                    f"Request ID: <code>{request_id}</code>\n\n"
                    f"<b>Buff.163 Account #{account_id}:</b>\n"
                    f"🔐 Login: <code>{account_creds['login']}</code>\n"
                    f"🔑 Password: <code>{account_creds['password']}</code>\n\n"
                    f"<i>Now send QR code to complete the process.</i>"
                )
                
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=admin_account_msg,
                        parse_mode="HTML"
                    )
                    logger.info(f"📤 Account credentials sent to admin immediately: Account #{account_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send account credentials to admin: {e}")
            
            # Отправить уведомления для пользователя
            context.user_data['pending_qr_user_id'] = user.id
            context.user_data['pending_qr_request_id'] = request_id
            context.user_data['pending_qr_amount'] = payment_request.unique_amount
            
            logger.info(f"✅ Admin confirmed WeChat payment {request_id}")
    
    except Exception as e:
        logger.error(f"❌ Error in admin_confirm: {e}")
        await query.edit_message_text("❌ An error occurred")
    finally:
        db.close()


async def admin_decline_wechat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ отклоняет WeChat платеж"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    request_id = int(query.data.replace("admin_decline_wechat_", ""))
    
    db = SessionLocal()
    try:
        from bot.services.payment_request_service import PaymentRequestService
        
        # Отклонить запрос
        success = PaymentRequestService.decline_by_admin(request_id)
        if not success:
            await query.edit_message_text("❌ Payment request not found")
            return
        
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if payment_request:
            user = db.query(User).filter(User.id == payment_request.user_id).first()
            
            # Уведомить пользователя
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text="❌ <b>Payment Request Declined</b>\n\n"
                         "Your payment request has been declined by the administrator.\n"
                         "Please try again later or contact support.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
            
            # Обновить сообщение админу
            await query.edit_message_text(
                f"❌ <b>WeChat Payment Declined</b>\n\n"
                f"User: <b>{user.first_name}</b>\n"
                f"Amount: <b>¥{payment_request.unique_amount}</b>\n\n"
                f"User has been notified.",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Admin declined WeChat payment {request_id}")
    
    except Exception as e:
        logger.error(f"❌ Error in admin_decline: {e}")
        await query.edit_message_text("❌ An error occurred")
    finally:
        db.close()


async def admin_send_qr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Админ отправляет QR для платежа.
    
    Флоу:
    1. Админ подтверждает платеж
    2. Следующее сообщение с фото считается QR кодом
    3. Система отправляет QR пользователю с инструкциями
    """
    
    # Проверим что это фото/документ
    if not update.message:
        return
    
    if not (update.message.photo or update.message.document):
        await update.message.reply_text("⚠️ Please send a QR code photo or document")
        return
    
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied")
        return
    
    # Проверяем есть ли pending payment request
    if 'pending_qr_request_id' not in context.user_data:
        await update.message.reply_text(
            "⚠️ No pending payment request\n\n"
            "Use: Confirm payment → Send QR"
        )
        return
    
    from bot.services.payment_request_service import PaymentRequestService
    
    request_id = context.user_data['pending_qr_request_id']
    user_id = context.user_data.get('pending_qr_user_id')
    amount = context.user_data.get('pending_qr_amount')
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        
        # Get QR file ID
        if update.message.photo:
            qr_file_id = update.message.photo[-1].file_id
        else:
            qr_file_id = update.message.document.file_id
        
        # ОТправить QR пользователю
        qr_message_text = (
            f"🛒 <b>WeChat Payment QR Code</b>\n\n"
            f"💰 <b>Amount to pay: ¥{amount}</b>\n\n"
            f"⏰ <b>QR Valid for 15 minutes</b>\n\n"
            f"After payment, click confirm button to complete."
        )
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Payment Confirmed",
                    callback_data=f"user_confirm_payment_{request_id}"
                )
            ]
        ]
        
        # Отправить QR пользователю
        qr_msg = await context.bot.send_photo(
            chat_id=user.telegram_id,
            photo=qr_file_id,
            caption=qr_message_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Обновить payment request
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if payment_request:
            success = PaymentRequestService.set_qr_sent(request_id, qr_msg.message_id)
            
            if success:
                await update.message.reply_text(
                    f"✅ <b>QR Sent to User</b>\n\n"
                    f"User: <b>{user.first_name}</b>\n"
                    f"Amount: <b>¥{amount}</b>\n\n"
                    f"User has been sent QR code and will confirm when paid.",
                    parse_mode="HTML"
                )
                
                # Очистить context
                context.user_data.pop('pending_qr_request_id', None)
                context.user_data.pop('pending_qr_user_id', None)
                context.user_data.pop('pending_qr_amount', None)
                
                logger.info(f"✅ QR sent to user {user_id} for payment {request_id}")
            else:
                await update.message.reply_text("❌ Failed to update payment request")
    
    except Exception as e:
        logger.error(f"❌ Error sending QR: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")
    finally:
        db.close()


async def user_final_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Пользователь подтверждает что оплатил в WeChat.
    Админ должен вручную проверить баланс на Buff.163
    """
    query = update.callback_query
    await query.answer()
    
    request_id = int(query.data.replace("user_confirm_payment_", ""))
    
    db = SessionLocal()
    try:
        from bot.services.payment_request_service import PaymentRequestService
        
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if not payment_request:
            await query.edit_message_text("❌ Payment request not found")
            return
        
        # Проверить истек ли QR
        if payment_request.qr_expires_at and datetime.utcnow() > payment_request.qr_expires_at:
            await query.edit_message_caption(
                f"❌ <b>QR Code Expired</b>\n\n"
                f"The QR code is no longer valid (15 minutes have passed).\n\n"
                f"If you've already paid, click the button below to notify admin.\n"
                f"If not, please try again later.",
                parse_mode="HTML"
            )
            return
        
        # Показать пользователю сообщение "ожидаем подтверждение админа"
        await query.edit_message_caption(
            f"⏳ <b>Awaiting Admin Confirmation</b>\n\n"
            f"Amount: <b>¥{payment_request.unique_amount}</b>\n\n"
            f"Your payment is being verified.\n"
            f"Confirmation within 2-5 minutes.",
            parse_mode="HTML"
        )
        
        # Отправить уведомление админу
        user = db.query(User).filter(User.id == payment_request.user_id).first()
        
        admin_message_text = (
            f"✅ <b>Payment Confirmation from User</b>\n\n"
            f"👤 User: <b>{user.first_name}</b>\n"
            f"🆔 ID: <code>{user.telegram_id}</code>\n"
            f"💰 Amount: <b>¥{payment_request.unique_amount}</b>\n"
            f"📅 Time: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"<b>Action:</b> Verify balance on Buff.163 and check the buttons below"
        )
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Verified & Complete",
                    callback_data=f"admin_complete_payment_{request_id}"
                ),
                InlineKeyboardButton(
                    "❌ Not Received",
                    callback_data=f"admin_cancel_payment_{request_id}"
                )
            ]
        ]
        
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_message_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                logger.info(f"✅ Payment confirmation notification sent to admin for request {request_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
    
    except Exception as e:
        logger.error(f"❌ Error in user payment confirmation: {e}")
        await query.edit_message_caption(f"❌ An error occurred")
    finally:
        db.close()


async def admin_complete_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ завершает платеж после проверки баланса"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    request_id = int(query.data.replace("admin_complete_payment_", ""))
    
    db = SessionLocal()
    try:
        from bot.services.payment_request_service import PaymentRequestService
        
        # Завершить платеж
        success = PaymentRequestService.complete_payment(request_id)
        if not success:
            await query.edit_message_text("❌ Payment request not found")
            return
        
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if payment_request:
            user = db.query(User).filter(User.id == payment_request.user_id).first()
            
            # Обновить баланс пользователя
            user.balance += payment_request.unique_amount
            
            # Calculate and add top-up bonus based on REQUESTED amount (not unique_amount)
            bonus = get_topup_bonus(int(payment_request.amount_requested))
            if bonus > 0:
                user.balance += bonus
                bonus_text = f"🎁 <b>YOU GET EXTRA:</b> +¥{bonus} absolutely FREE!\n"
            else:
                bonus_text = ""
            
            db.commit()
            
            # Отправить уведомление пользователю
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"✅ <b>Payment Confirmed!</b>\n\n"
                         f"Amount: <b>¥{payment_request.unique_amount}</b>\n"
                         f"{bonus_text}"
                         f"New balance: <b>¥{user.balance:.2f}</b>\n\n"
                         f"Thank you for topping up!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
                    ])
                )
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
            
            # Обновить сообщение админу
            await query.edit_message_text(
                f"✅ <b>Payment Completed</b>\n\n"
                f"👤 User: <b>{user.first_name}</b>\n"
                f"💳 They paid: <b>¥{payment_request.unique_amount}</b>\n"
                f"{bonus_text}"
                f"💰 New balance: <b>¥{user.balance:.2f}</b>\n\n"
                f"✓ Successfully processed",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Payment {request_id} completed. User balance updated to {user.balance}")
    
    except Exception as e:
        logger.error(f"❌ Error completing payment: {e}")
        await query.edit_message_text("❌ An error occurred")
    finally:
        db.close()


async def admin_cancel_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ отменяет платеж если деньги не поступили"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    request_id = int(query.data.replace("admin_cancel_payment_", ""))
    
    db = SessionLocal()
    try:
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.id == request_id
        ).first()
        
        if not payment_request:
            await query.edit_message_text("❌ Payment request not found")
            return
        
        user = db.query(User).filter(User.id == payment_request.user_id).first()
        
        # Отметить payment request как отмененный
        payment_request.status = 'expired'
        db.commit()
        
        # Отправить уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text="❌ <b>Payment Not Received</b>\n\n"
                     "The payment for your order was not received.\n"
                     "Please try again or contact support.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
                ])
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        # Обновить сообщение админу
        await query.edit_message_text(
            f"❌ <b>Payment Cancelled</b>\n\n"
            f"User: <b>{user.first_name}</b>\n"
            f"Amount: <b>¥{payment_request.unique_amount}</b>\n\n"
            f"User has been notified.",
            parse_mode="HTML"
        )
        
        logger.info(f"❌ Payment {request_id} cancelled")
    
    except Exception as e:
        logger.error(f"❌ Error cancelling payment: {e}")
        await query.edit_message_text("❌ An error occurred")
    finally:
        db.close()
