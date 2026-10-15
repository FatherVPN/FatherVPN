class VPNProviderNotConfigured(RuntimeError):
    pass


async def get_or_create_config(telegram_id: int) -> str:
    """Replace with a real WireGuard or VPN-panel integration.

    Must create a unique client, return its configuration securely, and revoke
    access when the subscription expires. Never return fake placeholder configs.
    """
    raise VPNProviderNotConfigured(
        "VPN-провайдер ещё не настроен. Подключите WireGuard или VPN-панель."
    )
