import asyncio
import base64
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import aiohttp
from PIL import Image as PILImage

from astrbot import logger
from astrbot.core.message.components import At, Image, Plain, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent

from . import actions_count, actions_key, actions_prompt


class ImageWorkflow:
    def __init__(self, proxy_url: str | None = None):
        if proxy_url:
            logger.info(f"ImageWorkflow 使用代理: {proxy_url}")
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
            logger.error(
                "图片下载失败: 发生未知错误, URL: %s, 错误类型: %s, 错误: %s",
                url,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return None

    async def _get_avatar(self, user_id: str) -> bytes | None:
        if not user_id.isdigit():
            logger.warning(f"无法获取非 QQ 平台或无效 QQ 号 {user_id} 的头像。")
            return None
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
        if not raw:
            return None
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
        if self.session and not self.session.closed:
            await self.session.close()


async def initialize(plugin) -> None:
    use_proxy = plugin.conf.get("use_proxy", False)
    proxy_url = plugin.conf.get("proxy_url") if use_proxy else None
    plugin.iwf = plugin.ImageWorkflow(proxy_url)
    await actions_prompt.load_prompt_map(plugin)
    await actions_count.load_user_counts(plugin)
    await actions_count.load_group_counts(plugin)
    await actions_count.load_user_checkin_data(plugin)
    logger.info("FigurinePro 插件已加载 (lmarena 风格)")
    if not plugin.conf.get("api_keys"):
        logger.warning("FigurinePro: 未配置任何 API 密钥，插件可能无法工作")


async def handle_figurine_request(plugin, event: AstrMessageEvent):
    if plugin.conf.get("prefix", True) and not event.is_at_or_wake_command:
        return
    text = event.message_str.strip()
    if not text:
        return
    cmd = text.split()[0].strip()
    bnn_command = plugin.conf.get("extra_prefix", "bnn")
    user_prompt = ""
    is_bnn = False
    if cmd == bnn_command:
        user_prompt = text.removeprefix(cmd).strip()
        is_bnn = True
        if not user_prompt:
            return
    elif cmd in plugin.prompt_map:
        user_prompt = plugin.prompt_map.get(cmd)
    else:
        return

    sender_id = event.get_sender_id()
    group_id = event.get_group_id()
    is_master = plugin.is_global_admin(event)
    if not is_master:
        if sender_id in plugin.conf.get("user_blacklist", []):
            return
        if group_id and group_id in plugin.conf.get("group_blacklist", []):
            return
        if plugin.conf.get("user_whitelist", []) and sender_id not in plugin.conf.get("user_whitelist", []):
            return
        if group_id and plugin.conf.get("group_whitelist", []) and group_id not in plugin.conf.get("group_whitelist", []):
            return
        user_count = plugin._get_user_count(sender_id)
        group_count = plugin._get_group_count(group_id) if group_id else 0
        user_limit_on = plugin.conf.get("enable_user_limit", True)
        group_limit_on = plugin.conf.get("enable_group_limit", False) and group_id
        has_group_count = not group_limit_on or group_count > 0
        has_user_count = not user_limit_on or user_count > 0
        if group_id:
            if not has_group_count and not has_user_count:
                yield event.plain_result("❌ 本群次数与您的个人次数均已用尽。")
                return
        elif not has_user_count:
            yield event.plain_result("❌ 您的使用次数已用完。")
            return

    img_bytes_list: List[bytes] = []
    if plugin.iwf:
        img_bytes_list = await plugin.iwf.get_images(event)
    if not plugin.iwf or not img_bytes_list:
        if not is_bnn:
            yield event.plain_result("请发送或引用一张图片。")
            return

    allow_multi_images = plugin.conf.get("api_type", "openai") == "openai"
    max_multi_cfg = plugin.conf.get("max_multi_images", 5)
    try:
        max_multi_images = max(1, int(max_multi_cfg))
    except (TypeError, ValueError):
        max_multi_images = 5

    images_to_process: List[bytes] = []
    display_cmd = cmd
    if is_bnn:
        max_images = max_multi_images if allow_multi_images else 1
        original_count = len(img_bytes_list)
        if original_count > max_images:
            images_to_process = img_bytes_list[:max_images]
            yield event.plain_result(f"🎨 检测到 {original_count} 张图片，已选取前 {max_images} 张…")
        else:
            images_to_process = img_bytes_list if allow_multi_images else img_bytes_list[:1]
        display_cmd = user_prompt[:10] + "..." if len(user_prompt) > 10 else user_prompt
        yield event.plain_result(f"🎨 检测到 {len(images_to_process)} 张图片，正在生成 [{display_cmd}]...")
    else:
        if not img_bytes_list:
            yield event.plain_result("请发送或引用一张图片。")
            return
        if allow_multi_images:
            if len(img_bytes_list) > max_multi_images:
                images_to_process = img_bytes_list[:max_multi_images]
                yield event.plain_result(
                    f"🎨 检测到 {len(img_bytes_list)} 张图片，已选取前 {max_multi_images} 张…"
                )
            else:
                images_to_process = img_bytes_list
        else:
            images_to_process = [img_bytes_list[0]]
        yield event.plain_result(f"🎨 收到请求，正在生成 [{cmd}]...")

    start_time = datetime.now()
    res_url = await call_api(plugin, images_to_process, user_prompt)
    elapsed = (datetime.now() - start_time).total_seconds()

    if res_url.startswith("http"):
        if not is_master:
            if plugin.conf.get("enable_user_limit", True):
                await plugin._decrease_user_count(sender_id)
            if group_id and plugin.conf.get("enable_group_limit", False):
                await plugin._decrease_group_count(group_id)

        caption_parts = [f"✅ 生成成功 ({elapsed:.2f}s)", f"预设: {display_cmd}"]
        if is_master:
            caption_parts.append("剩余次数: ∞")
        else:
            user_count = plugin._get_user_count(sender_id)
            caption_parts.append(f"个人剩余: {user_count}")
            if group_id and plugin.conf.get("enable_group_limit", False):
                group_count = plugin._get_group_count(group_id)
                caption_parts.append(f"群组剩余: {group_count}")

        if "127.0.0.1" in res_url or "localhost" in res_url:
            image_name = res_url.split("/")[-1]
            local_path = Path("~/QQBot/antigravity2api-nodejs/public/images/" + image_name).expanduser()
            yield event.chain_result([Image.fromFileSystem(str(local_path)), Plain(" | ".join(caption_parts))])
        else:
            yield event.chain_result([Image.fromURL(res_url), Plain(" | ".join(caption_parts))])
    else:
        yield event.plain_result(f"❌ 生成失败 ({elapsed:.2f}s)\n原因: {res_url}")
    event.stop_event()


async def handle_text_to_image_request(plugin, event: AstrMessageEvent):
    prompt = event.message_str.strip()
    if not prompt:
        yield event.plain_result("请提供文生图的描述。用法: #文生图 <描述>")
        return

    sender_id = event.get_sender_id()
    group_id = event.get_group_id()
    is_master = plugin.is_global_admin(event)

    if not is_master:
        if sender_id in plugin.conf.get("user_blacklist", []):
            yield event.plain_result("❌ 您已被禁止使用此功能。")
        if group_id and group_id in plugin.conf.get("group_blacklist", []):
            yield event.plain_result("❌ 本群已被禁止使用此功能。")
        if plugin.conf.get("user_whitelist", []) and sender_id not in plugin.conf.get("user_whitelist", []):
            yield event.plain_result("❌ 您不在白名单中，无法使用此功能。")
        if group_id and plugin.conf.get("group_whitelist", []) and group_id not in plugin.conf.get("group_whitelist", []):
            yield event.plain_result("❌ 本群不在白名单中，无法使用此功能。")
        user_count = plugin._get_user_count(sender_id)
        group_count = plugin._get_group_count(group_id) if group_id else 0
        user_limit_on = plugin.conf.get("enable_user_limit", True)
        group_limit_on = plugin.conf.get("enable_group_limit", False) and group_id
        has_group_count = not group_limit_on or group_count > 0
        has_user_count = not user_limit_on or user_count > 0
        if group_id:
            if not has_user_count and not has_group_count:
                yield event.plain_result("❌ 您的个人次数和本群次数均已用尽。")
        elif not has_user_count:
            yield event.plain_result("❌ 您的个人次数已用尽。")

    display_prompt = prompt[:20] + "..." if len(prompt) > 20 else prompt
    yield event.plain_result(f"🎨 收到文生图请求，正在生成 [{display_prompt}]...")

    start_time = datetime.now()
    res_url = await call_api(plugin, [], prompt)
    elapsed = (datetime.now() - start_time).total_seconds()

    if res_url.startswith("http"):
        if not is_master:
            if plugin.conf.get("enable_user_limit", True):
                await plugin._decrease_user_count(sender_id)
            if group_id and plugin.conf.get("enable_group_limit", False):
                await plugin._decrease_group_count(group_id)

        caption_parts = [f"✅ 生成成功 ({elapsed:.2f}s)"]
        if is_master:
            caption_parts.append("剩余次数: ∞")
        else:
            user_count = plugin._get_user_count(sender_id)
            caption_parts.append(f"个人剩余: {user_count}")
            if group_id and plugin.conf.get("enable_group_limit", False):
                group_count = plugin._get_group_count(group_id)
                caption_parts.append(f"群组剩余: {group_count}")

        if "127.0.0.1" in res_url or "localhost" in res_url:
            image_name = res_url.split("/")[-1]
            local_path = Path("~/QQBot/antigravity2api-nodejs/public/images/" + image_name).expanduser()
            yield event.chain_result([Image.fromFileSystem(str(local_path)), Plain(" | ".join(caption_parts))])
        else:
            yield event.chain_result([Image.fromURL(res_url), Plain(" | ".join(caption_parts))])
    else:
        yield event.plain_result(f"❌ 生成失败 ({elapsed:.2f}s)\n原因: {res_url}")
    event.stop_event()


def extract_image_url_from_response(plugin, data: Dict[str, Any]) -> str | None:
    try:
        url = data["data"][0]["url"]
        logger.info(f"成功从 API 响应中提取到 URL: {url[:50]}...")
        return url
    except (IndexError, TypeError, KeyError):
        logger.warning(f"未能在响应中找到 'data[0].url'，原始响应 (截断): {str(data)[:200]}")
        return None


async def call_api(plugin, image_bytes_list: List[bytes], prompt: str) -> str:
    api_type = plugin.conf.get("api_type", "openai")

    if api_type == "volcengine":
        api_url = plugin.conf.get("volcengine_api_url") or plugin.conf.get("api_url")
        model_name = plugin.conf.get("volcengine_model") or plugin.conf.get("model")
    elif api_type == "openai":
        api_url = plugin.conf.get("openai_api_url")
        model_name = plugin.conf.get("openai_model")
    else:
        return f"未知的 API 类型: {api_type}"

    if not api_url:
        return f"API URL 未配置 ({api_type})"
    if not model_name:
        return f"模型名称未配置 ({api_type})"

    api_key = await actions_key.get_api_key(plugin)
    if not api_key:
        return "无可用的 API Key"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    payload: Dict[str, Any] = {}

    if api_type == "volcengine":
        payload = {
            "model": model_name,
            "prompt": prompt,
            "size": plugin.conf.get("image_size", "2K"),
            "sequential_image_generation": plugin.conf.get("sequential_image_generation", "disabled"),
            "stream": False,
            "response_format": "url",
            "watermark": plugin.conf.get("watermark", False),
        }
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
        is_chat_api = "chat/completions" in api_url

        if is_chat_api:
            messages = []
            content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
            if image_bytes_list:
                appended = 0
                for idx, img_bytes in enumerate(image_bytes_list, start=1):
                    try:
                        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                        content.append(
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                        )
                        appended += 1
                    except Exception as exc:
                        logger.error(f"Base64 编码第 {idx} 张图片时出错: {exc}", exc_info=True)
                if appended == 0:
                    logger.warning("收到图像输入但全部编码失败，已回退为纯文本请求")
            messages.append({"role": "user", "content": content})

            payload = {
                "model": model_name,
                "messages": messages,
                "stream": False,
            }
        else:
            payload = {
                "model": model_name,
                "prompt": prompt,
                "n": 1,
                "size": plugin.conf.get("image_size", "1024x1024"),
                "response_format": "url",
            }
            if image_bytes_list:
                try:
                    if len(image_bytes_list) > 1:
                        logger.info(
                            "OpenAI 图像生成端点暂不支持多图输入，已仅使用第一张 (共 %d 张)",
                            len(image_bytes_list),
                        )
                    img_b64 = base64.b64encode(image_bytes_list[0]).decode("utf-8")
                    payload["image"] = f"data:image/png;base64,{img_b64}"
                except Exception as e:
                    logger.error(f"Base64 编码图片时出错: {e}", exc_info=True)
                    return f"图片编码失败: {e}"
    else:
        return f"未知的 API 类型: {api_type}"

    logger.info(
        "发送到 API (%s): URL=%s, Model=%s, HasImage=%s",
        api_type,
        api_url,
        model_name,
        bool(image_bytes_list),
    )

    try:
        if not plugin.iwf:
            return "ImageWorkflow 未初始化"
        async with plugin.iwf.session.post(
            api_url, json=payload, headers=headers, proxy=plugin.iwf.proxy, timeout=120
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"API 请求失败: HTTP {resp.status}, 响应: {error_text}")
                return f"API请求失败 (HTTP {resp.status}): {error_text[:200]}"

            data = await resp.json()
            gen_image_url = None

            if api_type == "openai" and "chat/completions" in api_url:
                try:
                    content = data["choices"][0]["message"]["content"]
                    match = re.search(r"!\[.*?\]\((.*?)\)", content)
                    if match:
                        gen_image_url = match.group(1)
                    elif "http" in content:
                        url_match = re.search(r"(https?://[^\s)]+)", content)
                        if url_match:
                            gen_image_url = url_match.group(1)
                    if not gen_image_url:
                        if content.strip().startswith("http"):
                            gen_image_url = content.strip()
                        else:
                            logger.warning(f"无法从Chat响应中提取图片URL，将返回原始content: {content}")
                            return content
                    return gen_image_url
                except (KeyError, IndexError, TypeError) as e:
                    logger.error(f"解析Chat响应结构失败: {data}", exc_info=True)
                    return f"解析Chat响应失败: {str(data)[:200]}"
            else:
                if "data" not in data or not data["data"]:
                    logger.error(f"API响应中未找到图片数据: {data}")
                    if "error" in data:
                        if isinstance(data["error"], dict):
                            return data["error"].get("message", json.dumps(data["error"]))
                        return str(data["error"])
                    return f"API响应中未找到图片数据: {str(data)[:500]}..."

                gen_image_url = extract_image_url_from_response(plugin, data)

            if not gen_image_url:
                logger.error(f"API响应解析失败: {data}")
                return f"API响应解析失败: {str(data)[:500]}..."

            return gen_image_url

    except asyncio.TimeoutError:
        logger.error("API 请求超时")
        return "请求超时"
    except Exception as e:
        logger.error(f"调用 API 时发生未知错误: {e}", exc_info=True)
        return f"发生未知错误: {e}"


async def terminate(plugin) -> None:
    if plugin.iwf:
        await plugin.iwf.terminate()
    logger.info("[FigurinePro] 插件已终止")
