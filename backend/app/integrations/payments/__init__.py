from app.core.config import settings
from app.integrations.payments.mock import MockPaymentProvider


def provider(name=None):
    name = name or settings().payment_provider
    if name == "mock":
        return MockPaymentProvider()
    if name == "yookassa_test":
        from app.integrations.payments.yookassa import YooKassaProvider

        return YooKassaProvider()
    raise ValueError("Only mock and yookassa_test are supported")
