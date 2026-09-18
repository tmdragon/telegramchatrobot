"""src.bot 子包：Telegram Bot + 播报服务。

模块清单：
- service.py      BotService：python-telegram-bot Application 包装
- commands.py     /status /projects /help /force_broadcast /reload /dryrun handler
- templates.py    render_broadcast() Markdown 文案
- broadcast.py    BroadcastSvc 全员播报 + 指数退避
- notifications.py notify_admin()
"""