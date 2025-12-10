import asyncio
import base64
import functools
import io
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import aiohttp
from PIL import Image as PILImage

from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import At, Image, Reply, Plain
from astrbot.core.platform.astr_message_event import AstrMessageEvent

COMMAND_DESCRIPTIONS = {
    "手办化": "生成角色的手办造型，偏向立体模型展示",
    "手办化2": "生成另一种风格的手办造型，可能是细节或比例的不同",
    "手办化3": "生成不同版本的手办展示，更偏系列感",
    "手办化4": "生成手办化第四种风格，可能是更精致或特殊造型",
    "手办化5": "生成另一种改良版手办造型",
    "手办化6": "生成手办化的第六种衍生风格",
    "Q版化": "生成Q版（可爱简化比例）的角色形象",
    "痛屋化": "生成痛屋（贴满角色元素装饰的房间）场景",
    "痛屋化2": "生成改良版痛屋场景，更丰富或现代感",
    "痛车化": "生成痛车（贴有角色图案的车辆）造型",
    "cos化": "生成角色cosplay化的照片风格",
    "cos自拍": "生成角色自拍风格的cos照片",
    "孤独的我": "生成孤独、滑稽或小丑化的意境图",
    "第一视角": "生成第一人称视角场景，沉浸感强",
    "第三视角": "生成第三人称视角场景，看起来像他人在看角色",
    "鬼图": "生成灵异鬼图风格照片，带恐怖氛围",
    "贴纸化": "生成贴纸风格的小图，方便做表情或周边",
    "玉足": "生成角色玉足相关的画面或细节",
    "玩偶化": "生成毛绒玩偶（fumo）风格角色",
    "cos相遇": "生成两位cos角色相遇的场景",
    "三视图": "生成角色三视图（正面、侧面、背面）",
    "穿搭拆解": "生成角色服装穿搭的详细拆解图",
    "拆解图": "生成模型拆解或零件展示图",
    "角色界面": "生成类似游戏中角色信息界面的画面",
    "角色设定": "生成角色设定图，包含全身、武器、细节等",
    "3D打印": "生成适合3D打印的模型预览图",
    "微型化": "生成微缩模型、小比例角色形象",
    "挂件化": "生成挂件、钥匙扣风格的角色造型",
    "姿势表": "生成角色姿势参考表，多种动作合集",
    "高清修复": "对画面进行高清化、细节修复",
    "人物转身": "生成人物转身动作的连续画面",
    "绘画四宫格": "生成四宫格绘画对比图或进度展示",
    "发型九宫格": "生成九种不同发型的对比图",
    "头像九宫格": "生成九个不同风格的头像合集",
    "表情九宫格": "生成角色九种不同表情合集",
    "多机位": "生成多机位拍摄的场景视角合集",
    "电影分镜": "生成电影风格的分镜图",
    "动漫分镜": "生成动漫风格的分镜图",
    "真人化": "生成角色的真人化形象（真实感较强）",
    "真人化2": "生成另一种风格的真人化形象",
    "半真人": "生成半写实半动漫的混合风格",
    "半融合": "生成角色与其他元素融合的半融合风格"
}


@register(
    "astrbot_plugin_shoubanhua",
    "shskjw",
    "通过第三方api进行手办化等功能",
    "1.0.0", 
    "https://github.com/shkjw/astrbot_plugin_shoubanhua",
)
class FigurineProPlugin(Star):
    class ImageWorkflow:
        def __init__(self, proxy_url: str | None = None):
            if proxy_url: logger.info(f"ImageWorkflow 使用代理: {proxy_url}")
            self.session = aiohttp.ClientSession()
            self.proxy = proxy_url

        async def _download_image(self, url: str) -> bytes | None:
            logger.info(f"正在尝试下载图片: {url}")
            try:
                async with self.session.get(url, proxy=self.proxy, timeout=30) as resp:
                    resp.raise_for_status()
                    return await resp.read()
            except aiohttp.ClientResponseError as e:
                logger.error(f"图片下载失败: HTTP状态码 {e.status}, URL: {url}, 原因: {e.message}")
                return None
            except asyncio.TimeoutError:
                logger.error(f"图片下载失败: 请求超时 (30s), URL: {url}")
                return None
            except Exception as e:
                logger.error(f"图片下载失败: 发生未知错误, URL: {url}, 错误类型: {type(e).__name__}, 错误: {e}",
                             exc_info=True)
                return None

        async def _get_avatar(self, user_id: str) -> bytes | None:
            if not user_id.isdigit(): logger.warning(f"无法获取非 QQ 平台或无效 QQ 号 {user_id} 的头像。"); return None
            avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
            return await self._download_image(avatar_url)

        def _extract_first_frame_sync(self, raw: bytes) -> bytes:
            img_io = io.BytesIO(raw)
            try:
                with PILImage.open(img_io) as img:
                    if getattr(img, "is_animated", False):
                        logger.info("检测到动图, 将抽取第一帧进行生成")
                        img.seek(0)
                        first_frame = img.convert("RGBA")
                        out_io = io.BytesIO()
                        first_frame.save(out_io, format="PNG")
                        return out_io.getvalue()
            except Exception as e:
                logger.warning(f"抽取图片帧时发生错误, 将返回原始数据: {e}", exc_info=True)
            return raw

        async def _load_bytes(self, src: str) -> bytes | None:
            raw: bytes | None = None
            loop = asyncio.get_running_loop()
            if Path(src).is_file():
                raw = await loop.run_in_executor(None, Path(src).read_bytes)
            elif src.startswith("http"):
                raw = await self._download_image(src)
            elif src.startswith("base64://"):
                raw = await loop.run_in_executor(None, base64.b64decode, src[9:])
            if not raw: return None
            return await loop.run_in_executor(None, self._extract_first_frame_sync, raw)

        async def get_images(self, event: AstrMessageEvent) -> List[bytes]:
            img_bytes_list: List[bytes] = []
            at_user_ids: List[str] = []

            for seg in event.message_obj.message:
                if isinstance(seg, Reply) and seg.chain:
                    for s_chain in seg.chain:
                        if isinstance(s_chain, Image):
                            if s_chain.url and (img := await self._load_bytes(s_chain.url)):
                                img_bytes_list.append(img)
                            elif s_chain.file and (img := await self._load_bytes(s_chain.file)):
                                img_bytes_list.append(img)

            for seg in event.message_obj.message:
                if isinstance(seg, Image):
                    if seg.url and (img := await self._load_bytes(seg.url)):
                        img_bytes_list.append(img)
                    elif seg.file and (img := await self._load_bytes(seg.file)):
                        img_bytes_list.append(img)
                elif isinstance(seg, At):
                    at_user_ids.append(str(seg.qq))

            if img_bytes_list:
                return img_bytes_list

            if at_user_ids:
                for user_id in at_user_ids:
                    if avatar := await self._get_avatar(user_id):
                        img_bytes_list.append(avatar)
                return img_bytes_list

            if avatar := await self._get_avatar(event.get_sender_id()):
                img_bytes_list.append(avatar)

            return img_bytes_list

        async def terminate(self):
            if self.session and not self.session.closed: await self.session.close()

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
        use_proxy = self.conf.get("use_proxy", False)
        proxy_url = self.conf.get("proxy_url") if use_proxy else None
        self.iwf = self.ImageWorkflow(proxy_url)
        await self._load_prompt_map()
        await self._load_user_counts()
        await self._load_group_counts()
        await self._load_user_checkin_data()
        logger.info("FigurinePro 插件已加载 (lmarena 风格)")
        if not self.conf.get("api_keys"):
            logger.warning("FigurinePro: 未配置任何 API 密钥，插件可能无法工作")

    async def _load_prompt_map(self):
        logger.info("正在加载 prompts...")
        self.prompt_map.clear()
        prompt_list = self.conf.get("prompt_list", [])
        for item in prompt_list:
            try:
                if ":" in item:
                    key, value = item.split(":", 1)
                    self.prompt_map[key.strip()] = value.strip()
                else:
                    logger.warning(f"跳过格式错误的 prompt (缺少冒号): {item}")
            except ValueError:
                logger.warning(f"跳过格式错误的 prompt: {item}")
        logger.info(f"加载了 {len(self.prompt_map)} 个 prompts。")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def on_figurine_request(self, event: AstrMessageEvent):
        if self.conf.get("prefix", True) and not event.is_at_or_wake_command:
            return
        text = event.message_str.strip()
        if not text: return
        cmd = text.split()[0].strip()
        bnn_command = self.conf.get("extra_prefix", "bnn")
        user_prompt = ""
        is_bnn = False
        if cmd == bnn_command:
            user_prompt = text.removeprefix(cmd).strip()
            is_bnn = True
            if not user_prompt: return
        elif cmd in self.prompt_map:
            user_prompt = self.prompt_map.get(cmd)
        else:
            return
        sender_id = event.get_sender_id()
        group_id = event.get_group_id()
        is_master = self.is_global_admin(event)
        if not is_master:
            if sender_id in self.conf.get("user_blacklist", []): return
            if group_id and group_id in self.conf.get("group_blacklist", []): return
            if self.conf.get("user_whitelist", []) and sender_id not in self.conf.get("user_whitelist", []): return
            if group_id and self.conf.get("group_whitelist", []) and group_id not in self.conf.get("group_whitelist",
                                                                                                   []): return
            user_count = self._get_user_count(sender_id)
            group_count = self._get_group_count(group_id) if group_id else 0
            user_limit_on = self.conf.get("enable_user_limit", True)
            group_limit_on = self.conf.get("enable_group_limit", False) and group_id
            has_group_count = not group_limit_on or group_count > 0
            has_user_count = not user_limit_on or user_count > 0
            if group_id:
                if not has_group_count and not has_user_count:
                    yield event.plain_result("❌ 本群次数与您的个人次数均已用尽。");
                    return
            elif not has_user_count:
                yield event.plain_result("❌ 您的使用次数已用完。");
                return
        if not self.iwf or not (img_bytes_list := await self.iwf.get_images(event)):
            if not is_bnn:
                yield event.plain_result("请发送或引用一张图片。");
                return
        images_to_process = []
        display_cmd = cmd
        if is_bnn:
            MAX_IMAGES = 5
            original_count = len(img_bytes_list)
            if original_count > MAX_IMAGES:
                images_to_process = img_bytes_list[:MAX_IMAGES]
                yield event.plain_result(f"🎨 检测到 {original_count} 张图片，已选取前 {MAX_IMAGES} 张…")
            else:
                images_to_process = img_bytes_list
            display_cmd = user_prompt[:10] + '...' if len(user_prompt) > 10 else user_prompt
            yield event.plain_result(f"🎨 检测到 {len(images_to_process)} 张图片，正在生成 [{display_cmd}]...")
        else:
            if not img_bytes_list:
                yield event.plain_result("请发送或引用一张图片。");
                return
            images_to_process = [img_bytes_list[0]]
            yield event.plain_result(f"🎨 收到请求，正在生成 [{cmd}]...")
        start_time = datetime.now()
        res_url = await self._call_api(images_to_process, user_prompt)
        elapsed = (datetime.now() - start_time).total_seconds()

        if res_url.startswith("http"):
            if not is_master:
                if self.conf.get("enable_user_limit", True):
                    await self._decrease_user_count(sender_id)
                if group_id and self.conf.get("enable_group_limit", False):
                    await self._decrease_group_count(group_id)

            caption_parts = [f"✅ 生成成功 ({elapsed:.2f}s)", f"预设: {display_cmd}"]
            if is_master:
                caption_parts.append(f"剩余次数: ∞")
            else:
                user_count = self._get_user_count(sender_id)
                caption_parts.append(f"个人剩余: {user_count}")
                if group_id and self.conf.get("enable_group_limit", False):
                    group_count = self._get_group_count(group_id)
                    caption_parts.append(f"群组剩余: {group_count}")
            
            # --- URL 处理逻辑 ---
            if "127.0.0.1" in res_url or "localhost" in res_url:
                # 本地URL，转换为文件路径
                image_name = res_url.split('/')[-1]
                # 使用 expanduser() 展开 ~
                local_path = Path(f"~/QQBot/antigravity2api-nodejs/public/images/{image_name}").expanduser()
                yield event.chain_result([Image.fromFileSystem(str(local_path)), Plain(" | ".join(caption_parts))])
            else:
                # 远程URL，直接使用
                yield event.chain_result([Image.fromURL(res_url), Plain(" | ".join(caption_parts))])
        else:
            yield event.plain_result(f"❌ 生成失败 ({elapsed:.2f}s)\n原因: {res_url}")
        event.stop_event()

    @filter.command("文生图", prefix_optional=True)
    async def on_text_to_image_request(self, event: AstrMessageEvent):
        prompt = event.message_str.strip()
        if not prompt:
            yield event.plain_result("请提供文生图的描述。用法: #文生图 <描述>")
            return

        sender_id = event.get_sender_id()
        group_id = event.get_group_id()
        is_master = self.is_global_admin(event)

        # --- 权限和次数检查 ---
        if not is_master:
            if sender_id in self.conf.get("user_blacklist", []): yield event.plain_result("❌ 您已被禁止使用此功能。")
            if group_id and group_id in self.conf.get("group_blacklist", []): yield event.plain_result("❌ 本群已被禁止使用此功能。")
            if self.conf.get("user_whitelist", []) and sender_id not in self.conf.get("user_whitelist", []): yield event.plain_result("❌ 您不在白名单中，无法使用此功能。")
            if group_id and self.conf.get("group_whitelist", []) and group_id not in self.conf.get("group_whitelist",
                                                                                                   []): yield event.plain_result("❌ 本群不在白名单中，无法使用此功能。")
            user_count = self._get_user_count(sender_id)
            group_count = self._get_group_count(group_id) if group_id else 0
            user_limit_on = self.conf.get("enable_user_limit", True)
            group_limit_on = self.conf.get("enable_group_limit", False) and group_id
            has_group_count = not group_limit_on or group_count > 0
            has_user_count = not user_limit_on or user_count > 0
            if group_id:
                if not has_user_count and not has_group_count:
                    yield event.plain_result("❌ 您的个人次数和本群次数均已用尽。")
            elif not has_user_count:
                yield event.plain_result("❌ 您的个人次数已用尽。")


        display_prompt = prompt[:20] + '...' if len(prompt) > 20 else prompt
        yield event.plain_result(f"🎨 收到文生图请求，正在生成 [{display_prompt}]...")

        start_time = datetime.now()
        # 调用通用API，但传入空的图片列表
        res_url = await self._call_api([], prompt)
        elapsed = (datetime.now() - start_time).total_seconds()

        if res_url.startswith("http"):
            if not is_master:
                if self.conf.get("enable_user_limit", True):
                    await self._decrease_user_count(sender_id)
                if group_id and self.conf.get("enable_group_limit", False):
                    await self._decrease_group_count(group_id)

            caption_parts = [f"✅ 生成成功 ({elapsed:.2f}s)"]
            if is_master:
                caption_parts.append(f"剩余次数: ∞")
            else:
                user_count = self._get_user_count(sender_id)
                caption_parts.append(f"个人剩余: {user_count}")
                if group_id and self.conf.get("enable_group_limit", False):
                    group_count = self._get_group_count(group_id)
                    caption_parts.append(f"群组剩余: {group_count}")

            # --- URL 处理逻辑 ---
            if "127.0.0.1" in res_url or "localhost" in res_url:
                # 本地URL，转换为文件路径
                image_name = res_url.split('/')[-1]
                # 使用 expanduser() 展开 ~
                local_path = Path(f"~/QQBot/antigravity2api-nodejs/public/images/{image_name}").expanduser()
                yield event.chain_result([Image.fromFileSystem(str(local_path)), Plain(" | ".join(caption_parts))])
            else:
                # 远程URL，直接使用
                yield event.chain_result([Image.fromURL(res_url), Plain(" | ".join(caption_parts))])
        else:
            yield event.plain_result(f"❌ 生成失败 ({elapsed:.2f}s)\n原因: {res_url}")
        event.stop_event()

    @filter.command("lm添加", aliases={"lma"}, prefix_optional=True)
    async def add_lm_prompt(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        raw = event.message_str.strip()
        if ":" not in raw:
            yield event.plain_result('格式错误, 正确示例:\n#lm添加 姿势表:为这幅图创建一个姿势表, 摆出各种姿势')
            return

        key, new_value = map(str.strip, raw.split(":", 1))
        prompt_list = self.conf.get("prompt_list", [])
        found = False
        for idx, item in enumerate(prompt_list):
            if item.strip().startswith(key + ":"):
                prompt_list[idx] = f"{key}:{new_value}"
                found = True
                break
        if not found: prompt_list.append(f"{key}:{new_value}")

        await self.conf.set("prompt_list", prompt_list)
        await self._load_prompt_map()
        yield event.plain_result(f"已保存LM生图提示语:\n{key}:{new_value}")

    @filter.command("lm帮助", aliases={"lmh", "手办化帮助"}, prefix_optional=True)
    async def on_prompt_help(self, event: AstrMessageEvent):
        keyword = event.message_str.strip()
        if not keyword:
            msg = "图生图预设指令: \n"
            msg += "、".join(self.prompt_map.keys())
            msg += "\n\n纯文本生图指令: \n#文生图 <你的描述>"
            msg += "\n\n发送图片 + 预设指令 或 @用户 + 预设指令 来进行图生图。"
            yield event.plain_result(msg)
            return

        prompt = self.prompt_map.get(keyword)
        if not prompt:
            yield event.plain_result("未找到此预设指令")
            return
        yield event.plain_result(f"预设 [{keyword}] 的内容:\n{prompt}")

    @filter.command("lm效果", aliases={"手办化效果"}, prefix_optional=True)
    async def on_show_effects(self, event: AstrMessageEvent):
        """显示所有可用的图生图指令及其效果说明"""
        msg_parts = ["🎨 可用图生图指令及效果说明 🎨\n"]

        # 从 prompt_map 获取当前所有可用的指令
        available_commands = self.prompt_map.keys()

        for cmd_name in sorted(available_commands):
            # 从 COMMAND_DESCRIPTIONS 获取指令的功能说明
            description = COMMAND_DESCRIPTIONS.get(cmd_name, "暂无描述")
            msg_parts.append(f"✨ {cmd_name}: {description}")

        msg_parts.append("\n" + ("-" * 20))
        # 添加文生图指令的说明
        msg_parts.append("\n📝 纯文本生图指令:")
        msg_parts.append("➡️ #文生图 <你的描述>")

        # 添加自定义图生图指令的说明
        bnn_command = self.conf.get("extra_prefix", "bnn")
        msg_parts.append(f"\n🎨 自定义图生图指令:")
        msg_parts.append(f"➡️ 发送图片 + #{bnn_command} <你的提示词>")

        msg_parts.append("\n" + ("-" * 20))
        msg_parts.append("\n💡 如需查看具体指令的英文提示词，请使用 #lm帮助 <指令名>")

        yield event.plain_result("\n".join(msg_parts))

    def is_global_admin(self, event: AstrMessageEvent) -> bool:
        admin_ids = self.context.get_config().get("admins_id", [])
        return event.get_sender_id() in admin_ids

    async def _load_user_counts(self):
        if not self.user_counts_file.exists(): self.user_counts = {}; return
        loop = asyncio.get_running_loop()
        try:
            content = await loop.run_in_executor(None, self.user_counts_file.read_text, "utf-8")
            data = await loop.run_in_executor(None, json.loads, content)
            if isinstance(data, dict): self.user_counts = {str(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"加载用户次数文件时发生错误: {e}", exc_info=True);
            self.user_counts = {}

    async def _save_user_counts(self):
        loop = asyncio.get_running_loop()
        try:
            json_data = await loop.run_in_executor(None,
                                                   functools.partial(json.dumps, self.user_counts, ensure_ascii=False,
                                                                     indent=4))
            await loop.run_in_executor(None, self.user_counts_file.write_text, json_data, "utf-8")
        except Exception as e:
            logger.error(f"保存用户次数文件时发生错误: {e}", exc_info=True)

    def _get_user_count(self, user_id: str) -> int:
        return self.user_counts.get(str(user_id), 0)

    async def _decrease_user_count(self, user_id: str):
        user_id_str = str(user_id)
        count = self._get_user_count(user_id_str)
        if count > 0: self.user_counts[user_id_str] = count - 1; await self._save_user_counts()

    async def _load_group_counts(self):
        if not self.group_counts_file.exists(): self.group_counts = {}; return
        loop = asyncio.get_running_loop()
        try:
            content = await loop.run_in_executor(None, self.group_counts_file.read_text, "utf-8")
            data = await loop.run_in_executor(None, json.loads, content)
            if isinstance(data, dict): self.group_counts = {str(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"加载群组次数文件时发生错误: {e}", exc_info=True);
            self.group_counts = {}

    async def _save_group_counts(self):
        loop = asyncio.get_running_loop()
        try:
            json_data = await loop.run_in_executor(None,
                                                   functools.partial(json.dumps, self.group_counts, ensure_ascii=False,
                                                                     indent=4))
            await loop.run_in_executor(None, self.group_counts_file.write_text, json_data, "utf-8")
        except Exception as e:
            logger.error(f"保存群组次数文件时发生错误: {e}", exc_info=True)

    def _get_group_count(self, group_id: str) -> int:
        return self.group_counts.get(str(group_id), 0)

    async def _decrease_group_count(self, group_id: str):
        group_id_str = str(group_id)
        count = self._get_group_count(group_id_str)
        if count > 0: self.group_counts[group_id_str] = count - 1; await self._save_group_counts()

    async def _load_user_checkin_data(self):
        if not self.user_checkin_file.exists(): self.user_checkin_data = {}; return
        loop = asyncio.get_running_loop()
        try:
            content = await loop.run_in_executor(None, self.user_checkin_file.read_text, "utf-8")
            data = await loop.run_in_executor(None, json.loads, content)
            if isinstance(data, dict): self.user_checkin_data = {str(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"加载用户签到文件时发生错误: {e}", exc_info=True);
            self.user_checkin_data = {}

    async def _save_user_checkin_data(self):
        loop = asyncio.get_running_loop()
        try:
            json_data = await loop.run_in_executor(None, functools.partial(json.dumps, self.user_checkin_data,
                                                                           ensure_ascii=False, indent=4))
            await loop.run_in_executor(None, self.user_checkin_file.write_text, json_data, "utf-8")
        except Exception as e:
            logger.error(f"保存用户签到文件时发生错误: {e}", exc_info=True)

    @filter.command("手办化签到", prefix_optional=True)
    async def on_checkin(self, event: AstrMessageEvent):
        if not self.conf.get("enable_checkin", False):
            yield event.plain_result("📅 本机器人未开启签到功能。")
            return
        user_id = event.get_sender_id()
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self.user_checkin_data.get(user_id) == today_str:
            yield event.plain_result(f"您今天已经签到过了。\n剩余次数: {self._get_user_count(user_id)}")
            return
        reward = 0
        if str(self.conf.get("enable_random_checkin", False)).lower() == 'true':
            max_reward = max(1, int(self.conf.get("checkin_random_reward_max", 5)))
            reward = random.randint(1, max_reward)
        else:
            reward = int(self.conf.get("checkin_fixed_reward", 3))
        current_count = self._get_user_count(user_id)
        new_count = current_count + reward
        self.user_counts[user_id] = new_count
        await self._save_user_counts()
        self.user_checkin_data[user_id] = today_str
        await self._save_user_checkin_data()
        yield event.plain_result(f"🎉 签到成功！获得 {reward} 次，当前剩余: {new_count} 次。")

    @filter.command("手办化增加用户次数", prefix_optional=True)
    async def on_add_user_counts(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        cmd_text = event.message_str.strip()
        at_seg = next((s for s in event.message_obj.message if isinstance(s, At)), None)
        target_qq, count = None, 0
        if at_seg:
            target_qq = str(at_seg.qq)
            match = re.search(r"(\d+)\s*$", cmd_text)
            if match: count = int(match.group(1))
        else:
            match = re.search(r"(\d+)\s+(\d+)", cmd_text)
            if match: target_qq, count = match.group(1), int(match.group(2))
        if not target_qq or count <= 0:
            yield event.plain_result(
                '格式错误:\n#手办化增加用户次数 @用户 <次数>\n或 #手办化增加用户次数 <QQ号> <次数>')
            return
        current_count = self._get_user_count(target_qq)
        self.user_counts[str(target_qq)] = current_count + count
        await self._save_user_counts()
        yield event.plain_result(f"✅ 已为用户 {target_qq} 增加 {count} 次，TA当前剩余 {current_count + count} 次。")

    @filter.command("手办化增加群组次数", prefix_optional=True)
    async def on_add_group_counts(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        match = re.search(r"(\d+)\s+(\d+)", event.message_str.strip())
        if not match:
            yield event.plain_result('格式错误: #手办化增加群组次数 <群号> <次数>')
            return
        target_group, count = match.group(1), int(match.group(2))
        current_count = self._get_group_count(target_group)
        self.group_counts[str(target_group)] = current_count + count
        await self._save_group_counts()
        yield event.plain_result(f"✅ 已为群组 {target_group} 增加 {count} 次，该群当前剩余 {current_count + count} 次。")

    @filter.command("手办化查询次数", prefix_optional=True)
    async def on_query_counts(self, event: AstrMessageEvent):
        user_id_to_query = event.get_sender_id()
        if self.is_global_admin(event):
            at_seg = next((s for s in event.message_obj.message if isinstance(s, At)), None)
            if at_seg:
                user_id_to_query = str(at_seg.qq)
            else:
                match = re.search(r"(\d+)", event.message_str)
                if match: user_id_to_query = match.group(1)
        user_count = self._get_user_count(user_id_to_query)
        reply_msg = f"用户 {user_id_to_query} 个人剩余次数为: {user_count}"
        if user_id_to_query == event.get_sender_id(): reply_msg = f"您好，您当前个人剩余次数为: {user_count}"
        if group_id := event.get_group_id(): reply_msg += f"\n本群共享剩余次数为: {self._get_group_count(group_id)}"
        yield event.plain_result(reply_msg)

    @filter.command("手办化添加key", prefix_optional=True)
    async def on_add_key(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        new_keys = event.message_str.strip().split()
        if not new_keys: yield event.plain_result("格式错误，请提供要添加的Key。"); return
        api_keys = self.conf.get("api_keys", [])
        added_keys = [key for key in new_keys if key not in api_keys]
        api_keys.extend(added_keys)
        await self.conf.set("api_keys", api_keys)
        yield event.plain_result(f"✅ 操作完成，新增 {len(added_keys)} 个Key，当前共 {len(api_keys)} 个。")

    @filter.command("手办化key列表", prefix_optional=True)
    async def on_list_keys(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        api_keys = self.conf.get("api_keys", [])
        if not api_keys: yield event.plain_result("📝 暂未配置任何 API Key。"); return
        key_list_str = "\n".join(f"{i + 1}. {key[:8]}...{key[-4:]}" for i, key in enumerate(api_keys))
        yield event.plain_result(f"🔑 API Key 列表:\n{key_list_str}")

    @filter.command("手办化删除key", prefix_optional=True)
    async def on_delete_key(self, event: AstrMessageEvent):
        if not self.is_global_admin(event): return
        param = event.message_str.strip()
        api_keys = self.conf.get("api_keys", [])
        if param.lower() == "all":
            await self.conf.set("api_keys", [])
            yield event.plain_result(f"✅ 已删除全部 {len(api_keys)} 个 Key。")
        elif param.isdigit() and 1 <= int(param) <= len(api_keys):
            removed_key = api_keys.pop(int(param) - 1)
            await self.conf.set("api_keys", api_keys)
            yield event.plain_result(f"✅ 已删除 Key: {removed_key[:8]}...")
        else:
            yield event.plain_result("格式错误，请使用 #手办化删除key <序号|all>")

    async def _get_api_key(self) -> str | None:
        keys = self.conf.get("api_keys", [])
        if not keys: return None
        async with self.key_lock:
            key = keys[self.key_index]
            self.key_index = (self.key_index + 1) % len(keys)
            return key


    def _extract_image_url_from_response(self, data: Dict[str, Any]) -> str | None:
        """
        从 API 响应中提取图片 URL。
        适配 火山引擎 ARK (Doubao) 的响应格式。
        """
        try:
            # 火山引擎的响应格式: {"data": [{"url": "..."}]}
            url = data["data"][0]["url"]
            logger.info(f"成功从 API 响应中提取到 URL: {url[:50]}...")
            return url
        except (IndexError, TypeError, KeyError):
            logger.warning(f"未能在响应中找到 'data[0].url'，原始响应 (截断): {str(data)[:200]}")
            return None

    async def _call_api(self, image_bytes_list: List[bytes], prompt: str) -> str:
        api_type = self.conf.get("api_type", "openai")
        
        # 根据 api_type 选择对应的 URL 和 Model
        if api_type == "volcengine":
            api_url = self.conf.get("volcengine_api_url") or self.conf.get("api_url") # 兼容旧配置
            model_name = self.conf.get("volcengine_model") or self.conf.get("model")
        elif api_type == "openai":
            api_url = self.conf.get("openai_api_url")
            model_name = self.conf.get("openai_model")
        else:
            return f"未知的 API 类型: {api_type}"

        if not api_url: return f"API URL 未配置 ({api_type})"
        if not model_name: return f"模型名称未配置 ({api_type})"

        api_key = await self._get_api_key()
        if not api_key: return "无可用的 API Key"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

        payload: Dict[str, Any] = {}

        if api_type == "volcengine":
            # --- 构建 火山引擎 ARK (Doubao) API payload ---
            payload = {
                "model": model_name,
                "prompt": prompt,
                "size": self.conf.get("image_size", "2K"),  # 从配置读取，默认 2K
                "sequential_image_generation": self.conf.get("sequential_image_generation", "disabled"),
                "stream": False,
                "response_format": "url",  # URL格式
                "watermark": self.conf.get("watermark", False)  # 从配置读取，默认False
            }
            # --- 添加图片 (图生图) ---
            if image_bytes_list:
                try:
                    img_b64 = base64.b64encode(image_bytes_list[0]).decode("utf-8")
                    payload["image"] = f"data:image/png;base64,{img_b64}"
                    if len(image_bytes_list) > 1:
                        logger.warning(f"检测到 {len(image_bytes_list)} 张图片，火山引擎模型仅支持单张，已选取第一张")
                except Exception as e:
                    logger.error(f"Base64 编码图片时出错: {e}", exc_info=True)
                    return f"图片编码失败: {e}"

        elif api_type == "openai":
            # 检查是否使用 Chat Completions API (根据 URL 判断)
            is_chat_api = "chat/completions" in api_url
            
            if is_chat_api:
                # --- 构建 Chat Completions API payload ---
                messages = []
                if image_bytes_list:
                    # 图生图 / Vision 模式
                    content = [{"type": "text", "text": prompt}]
                    try:
                        img_b64 = base64.b64encode(image_bytes_list[0]).decode("utf-8")
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}"
                            }
                        })
                        if len(image_bytes_list) > 1:
                            logger.warning(f"检测到 {len(image_bytes_list)} 张图片，Chat模式仅支持单张，已选取第一张")
                    except Exception as e:
                        logger.error(f"Base64 编码图片时出错: {e}", exc_info=True)
                        return f"图片编码失败: {e}"
                    messages.append({"role": "user", "content": content})
                else:
                    # 文生图 / 纯文本模式
                    messages.append({"role": "user", "content": prompt})
                
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "stream": False
                }
            else:
                # --- 构建 标准 OpenAI Image API payload (images/generations) ---
                payload = {
                    "model": model_name,
                    "prompt": prompt,
                    "n": 1,
                    "size": self.conf.get("image_size", "1024x1024"),
                    "response_format": "url"
                }
                # --- 添加图片 (图生图) ---
                if image_bytes_list:
                    try:
                        img_b64 = base64.b64encode(image_bytes_list[0]).decode("utf-8")
                        # 尝试使用 image 字段，部分兼容 API 可能使用 image_url 或其他字段，这里按常见兼容格式处理
                        payload["image"] = f"data:image/png;base64,{img_b64}"
                        if len(image_bytes_list) > 1:
                            logger.warning(f"检测到 {len(image_bytes_list)} 张图片，OpenAI 模式仅支持单张，已选取第一张")
                    except Exception as e:
                        logger.error(f"Base64 编码图片时出错: {e}", exc_info=True)
                        return f"图片编码失败: {e}"
        else:
            return f"未知的 API 类型: {api_type}"

        logger.info(f"发送到 API ({api_type}): URL={api_url}, Model={model_name}, HasImage={bool(image_bytes_list)}")

        try:
            if not self.iwf: return "ImageWorkflow 未初始化"
            async with self.iwf.session.post(api_url, json=payload, headers=headers, proxy=self.iwf.proxy,
                                             timeout=120) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"API 请求失败: HTTP {resp.status}, 响应: {error_text}")
                    return f"API请求失败 (HTTP {resp.status}): {error_text[:200]}"

                data = await resp.json()
                gen_image_url = None
                
                # 处理 Chat Completions API 响应
                if api_type == "openai" and "chat/completions" in api_url:
                    try:
                        content = data["choices"][0]["message"]["content"]
                        # 尝试从 content 中提取 URL
                        # 1. 检查是否包含 markdown 图片格式 ![...](url)
                        match = re.search(r'!\[.*?\]\((.*?)\)', content)
                        if match:
                            gen_image_url = match.group(1)
                        # 2. 检查是否包含 http/https 链接
                        elif "http" in content:
                            url_match = re.search(r'(https?://[^\s)]+)', content)
                            if url_match:
                                gen_image_url = url_match.group(1)
                        
                        if not gen_image_url:
                             # 如果内容本身看起来像 URL (虽然上面 regex 应该覆盖了，但作为兜底)
                            if content.strip().startswith("http"):
                                gen_image_url = content.strip()
                            else:
                                logger.warning(f"无法从Chat响应中提取图片URL，将返回原始content: {content}")
                                return content
                        
                        # 直接返回URL
                        return gen_image_url

                    except (KeyError, IndexError, TypeError) as e:
                        logger.error(f"解析Chat响应结构失败: {data}", exc_info=True)
                        return f"解析Chat响应失败: {str(data)[:200]}"
                else:
                    # 处理 标准 Image API 响应 (火山引擎 或 OpenAI Image)
                    # 检查响应格式 {"data": [{"url": "..."}]}
                    if "data" not in data or not data["data"]:
                        error_msg = f"API响应中未找到图片数据: {str(data)[:500]}..."
                        logger.error(f"API响应中未找到图片数据: {data}")
                        if "error" in data:
                            # 尝试提取错误信息
                            if isinstance(data["error"], dict):
                                return data["error"].get("message", json.dumps(data["error"]))
                            return str(data["error"])
                        return error_msg

                    gen_image_url = self._extract_image_url_from_response(data)

                if not gen_image_url:
                    error_msg = f"API响应解析失败: {str(data)[:500]}..."
                    logger.error(f"API响应解析失败: {data}")
                    return error_msg

                # 对于非Chat API，直接返回URL
                return gen_image_url
                    
        except asyncio.TimeoutError:
            logger.error("API 请求超时")
            return "请求超时"
        except Exception as e:
            logger.error(f"调用 API 时发生未知错误: {e}", exc_info=True)
            return f"发生未知错误: {e}"

    async def terminate(self):
        if self.iwf: await self.iwf.terminate()
        logger.info("[FigurinePro] 插件已终止")
