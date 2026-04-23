import logging
from database.models import SessionLocal, Payment, User

logger = logging.getLogger(__name__)


class PaymentService:
    """Payment service (manual handlers in account.py)"""
    
    @staticmethod
    def create_payment(user_id: int, amount: float, description: str = "VPN Balance Top-up") -> dict:
        """Create payment record - handled in account.py handlers"""
        pass
    
    @staticmethod
    def get_payment_status(payment_id: str) -> dict:
        """Get payment status - handled in account.py handlers"""
        pass
    
    @staticmethod
    def confirm_payment(payment_id: str) -> bool:
        """Confirm payment - handled in account.py handlers"""
        return True
    
    @staticmethod
    def handle_webhook(notification_data: dict) -> bool:
        """Webhook handling - not used (manual payments)"""
        return False
    
    @staticmethod
    def check_pending_payments() -> int:
        """Check pending payments - handled in account.py"""
        return 0

