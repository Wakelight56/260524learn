"""用户自定义插件 — 放在此目录的 .py 文件会自动加载

写法示例：新建一个 .py 文件，用 @register_plugin 装饰类即可：

    from src.plugin.base import Plugin, register_plugin
    from src.platform.event import MessageEvent

    @register_plugin
    class MyPlugin(Plugin):
        @property
        def name(self) -> str:
            return "my_plugin"

        async def on_message(self, event: MessageEvent) -> str | None:
            if event.message == "hello":
                return "world!"
            return None
"""
