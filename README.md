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

Secrets live only in Render Environment Variables.
