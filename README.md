# FatherVPN Render project

One Render Web Service runs the Telegram bot and website.

- `/` public site
- `/cabinet/<secret>` personal cabinet
- `/d/<device-token>` browser subscription panel
- `/d/<device-token>/raw` raw VPN subscription
- `/health` health endpoint

Secrets live only in Render Environment Variables.
