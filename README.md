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
- `/privacy` and `/terms` serve approved legal documents only when `LEGAL_DOCUMENTS_ENABLED=true` and both files exist; otherwise they return a non-publication notice.
- Telegram `/info` displays operator/support details and shows document links only after the legal pages are enabled.
- The payment flow asks the customer to choose Telegram or email, and stores that contact against the specific payment order for dispute handling.

Secrets live only in Render Environment Variables.
