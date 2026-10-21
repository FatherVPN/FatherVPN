# FatherVPN Render project

One Render Web Service runs the Telegram bot and website.

- `/` public site
- `/miniapp` Telegram Mini App, launched from the FatherVPN bot menu
- `/api/miniapp/state` authenticated Mini App state
- `/api/miniapp/click` add one minute of VPN subscription time per click
- `/cabinet/<secret>` personal cabinet
- `/d/<device-token>` browser subscription panel
- `/d/<device-token>/raw` raw VPN subscription
- `/health` health endpoint
- The active `smart_webapp.py` routes `/privacy` and `/terms` serve approved legal documents only after the code approval gate is enabled and `LEGAL_DOCUMENTS_ENABLED=true`; otherwise they return a non-publication notice.
- The active `telegram_bot_v6.py` command `/info` displays operator/support details and shows document links only after the legal pages are enabled.
- The active `telegram_bot_v6.py` payment flow asks the customer to choose a Telegram username or email and stores that contact against the specific payment order for dispute handling.

Secrets live only in Render Environment Variables.
