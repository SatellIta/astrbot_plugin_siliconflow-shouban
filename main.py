import asyncio
from typing import Any, Dict, List, Optional

from . import actions_count, actions_help, actions_image, actions_key, actions_prompt
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
@register(
    "astrbot_plugin_shoubanhua",
    "shskjw",
    "通过第三方api进行手办化等功能",
    "1.0.0",
    "https://github.com/shkjw/astrbot_plugin_shoubanhua",
)
class FigurineProPlugin(Star):
    ImageWorkflow = actions_image.ImageWorkflow

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.plugin_data_dir = StarTools.get_data_dir()
        self.user_counts_file = self.plugin_data_dir / "user_counts.json"
        self.user_counts: Dict[str, int] = {}
        self.group_counts_file = self.plugin_data_dir / "group_counts.json"
        self.group_counts: Dict[str, int] = {}
        self.user_checkin_file = self.plugin_data_dir / "user_checkin.json"
        self.user_checkin_data: Dict[str, str] = {}
        self.prompt_map: Dict[str, str] = {}
        self.key_index = 0
        self.key_lock = asyncio.Lock()
        self.iwf: Optional[FigurineProPlugin.ImageWorkflow] = None

    async def initialize(self):
        await actions_image.initialize(self)

    async def _load_prompt_map(self):
        await actions_prompt.load_prompt_map(self)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def on_figurine_request(self, event: AstrMessageEvent):
        async for result in actions_image.handle_figurine_request(self, event):
            yield result

    @filter.command("文生图", prefix_optional=True)
    async def on_text_to_image_request(self, event: AstrMessageEvent):
        async for result in actions_image.handle_text_to_image_request(self, event):
            yield result

    @filter.command("lm添加", aliases={"lma"}, prefix_optional=True)
    async def add_lm_prompt(self, event: AstrMessageEvent):
        async for result in actions_prompt.add_lm_prompt(self, event):
            yield result

    @filter.command("lm帮助", aliases={"lmh", "手办化帮助"}, prefix_optional=True)
    async def on_prompt_help(self, event: AstrMessageEvent):
        async for result in actions_help.prompt_help(self, event):
            yield result

    @filter.command("lm效果", aliases={"手办化效果"}, prefix_optional=True)
    async def on_show_effects(self, event: AstrMessageEvent):
        async for result in actions_help.show_effects(self, event):
            yield result

    @filter.command("lm列表", prefix_optional=True)
    async def on_list_prompts(self, event: AstrMessageEvent):
        async for result in actions_prompt.list_prompts(self, event):
            yield result

    @filter.command("lm修改", prefix_optional=True)
    async def on_update_prompt(self, event: AstrMessageEvent):
        async for result in actions_prompt.update_prompt(self, event):
            yield result

    @filter.command("lm删除", prefix_optional=True)
    async def on_delete_prompt(self, event: AstrMessageEvent):
        async for result in actions_prompt.delete_prompt(self, event):
            yield result

    def is_global_admin(self, event: AstrMessageEvent) -> bool:
        admin_ids = self.context.get_config().get("admins_id", [])
        return event.get_sender_id() in admin_ids

    async def _load_user_counts(self):
        await actions_count.load_user_counts(self)

    async def _save_user_counts(self):
        await actions_count.save_user_counts(self)

    def _get_user_count(self, user_id: str) -> int:
        return actions_count.get_user_count(self, user_id)

    async def _decrease_user_count(self, user_id: str):
        await actions_count.decrease_user_count(self, user_id)

    async def _load_group_counts(self):
        await actions_count.load_group_counts(self)

    async def _save_group_counts(self):
        await actions_count.save_group_counts(self)

    def _get_group_count(self, group_id: str) -> int:
        return actions_count.get_group_count(self, group_id)

    async def _decrease_group_count(self, group_id: str):
        await actions_count.decrease_group_count(self, group_id)

    async def _load_user_checkin_data(self):
        await actions_count.load_user_checkin_data(self)

    async def _save_user_checkin_data(self):
        await actions_count.save_user_checkin_data(self)

    @filter.command("手办化签到", prefix_optional=True)
    async def on_checkin(self, event: AstrMessageEvent):
        async for result in actions_count.handle_checkin(self, event):
            yield result

    @filter.command("手办化增加用户次数", prefix_optional=True)
    async def on_add_user_counts(self, event: AstrMessageEvent):
        async for result in actions_count.add_user_counts(self, event):
            yield result

    @filter.command("手办化增加群组次数", prefix_optional=True)
    async def on_add_group_counts(self, event: AstrMessageEvent):
        async for result in actions_count.add_group_counts(self, event):
            yield result

    @filter.command("手办化查询次数", prefix_optional=True)
    async def on_query_counts(self, event: AstrMessageEvent):
        async for result in actions_count.query_counts(self, event):
            yield result

    @filter.command("手办化添加key", prefix_optional=True)
    async def on_add_key(self, event: AstrMessageEvent):
        async for result in actions_key.add_key(self, event):
            yield result

    @filter.command("手办化key列表", prefix_optional=True)
    async def on_list_keys(self, event: AstrMessageEvent):
        async for result in actions_key.list_keys(self, event):
            yield result

    @filter.command("手办化删除key", prefix_optional=True)
    async def on_delete_key(self, event: AstrMessageEvent):
        async for result in actions_key.delete_key(self, event):
            yield result

    async def _get_api_key(self) -> str | None:
        return await actions_key.get_api_key(self)


    def _extract_image_url_from_response(self, data: Dict[str, Any]) -> str | None:
        return actions_image.extract_image_url_from_response(self, data)

    async def _call_api(self, image_bytes_list: List[bytes], prompt: str) -> str:
        return await actions_image.call_api(self, image_bytes_list, prompt)

    async def terminate(self):
        await actions_image.terminate(self)
