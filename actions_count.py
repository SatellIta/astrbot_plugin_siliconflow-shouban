import asyncio
import functools
import json
import random
import re
from datetime import datetime
from typing import Optional

from astrbot import logger
from astrbot.core.message.components import At
from astrbot.core.platform.astr_message_event import AstrMessageEvent


async def load_user_counts(plugin) -> None:
    if not plugin.user_counts_file.exists():
        plugin.user_counts = {}
        return
    loop = asyncio.get_running_loop()
    try:
        content = await loop.run_in_executor(None, plugin.user_counts_file.read_text, "utf-8")
        data = await loop.run_in_executor(None, json.loads, content)
        if isinstance(data, dict):
            plugin.user_counts = {str(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"加载用户次数文件时发生错误: {e}", exc_info=True)
        plugin.user_counts = {}


async def save_user_counts(plugin) -> None:
    loop = asyncio.get_running_loop()
    try:
        json_data = await loop.run_in_executor(
            None,
            functools.partial(json.dumps, plugin.user_counts, ensure_ascii=False, indent=4),
        )
        await loop.run_in_executor(None, plugin.user_counts_file.write_text, json_data, "utf-8")
    except Exception as e:
        logger.error(f"保存用户次数文件时发生错误: {e}", exc_info=True)


def get_user_count(plugin, user_id: str) -> int:
    return plugin.user_counts.get(str(user_id), 0)


async def decrease_user_count(plugin, user_id: str) -> None:
    user_id_str = str(user_id)
    count = get_user_count(plugin, user_id_str)
    if count > 0:
        plugin.user_counts[user_id_str] = count - 1
        await save_user_counts(plugin)


async def load_group_counts(plugin) -> None:
    if not plugin.group_counts_file.exists():
        plugin.group_counts = {}
        return
    loop = asyncio.get_running_loop()
    try:
        content = await loop.run_in_executor(None, plugin.group_counts_file.read_text, "utf-8")
        data = await loop.run_in_executor(None, json.loads, content)
        if isinstance(data, dict):
            plugin.group_counts = {str(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"加载群组次数文件时发生错误: {e}", exc_info=True)
        plugin.group_counts = {}


async def save_group_counts(plugin) -> None:
    loop = asyncio.get_running_loop()
    try:
        json_data = await loop.run_in_executor(
            None,
            functools.partial(json.dumps, plugin.group_counts, ensure_ascii=False, indent=4),
        )
        await loop.run_in_executor(None, plugin.group_counts_file.write_text, json_data, "utf-8")
    except Exception as e:
        logger.error(f"保存群组次数文件时发生错误: {e}", exc_info=True)


def get_group_count(plugin, group_id: Optional[str]) -> int:
    if group_id is None:
        return 0
    return plugin.group_counts.get(str(group_id), 0)


async def decrease_group_count(plugin, group_id: str) -> None:
    group_id_str = str(group_id)
    count = get_group_count(plugin, group_id_str)
    if count > 0:
        plugin.group_counts[group_id_str] = count - 1
        await save_group_counts(plugin)


async def load_user_checkin_data(plugin) -> None:
    if not plugin.user_checkin_file.exists():
        plugin.user_checkin_data = {}
        return
    loop = asyncio.get_running_loop()
    try:
        content = await loop.run_in_executor(None, plugin.user_checkin_file.read_text, "utf-8")
        data = await loop.run_in_executor(None, json.loads, content)
        if isinstance(data, dict):
            plugin.user_checkin_data = {str(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"加载用户签到文件时发生错误: {e}", exc_info=True)
        plugin.user_checkin_data = {}


async def save_user_checkin_data(plugin) -> None:
    loop = asyncio.get_running_loop()
    try:
        json_data = await loop.run_in_executor(
            None,
            functools.partial(json.dumps, plugin.user_checkin_data, ensure_ascii=False, indent=4),
        )
        await loop.run_in_executor(None, plugin.user_checkin_file.write_text, json_data, "utf-8")
    except Exception as e:
        logger.error(f"保存用户签到文件时发生错误: {e}", exc_info=True)


async def handle_checkin(plugin, event: AstrMessageEvent):
    if not plugin.conf.get("enable_checkin", False):
        yield event.plain_result("📅 本机器人未开启签到功能。")
        return
    user_id = event.get_sender_id()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if plugin.user_checkin_data.get(user_id) == today_str:
        yield event.plain_result(f"您今天已经签到过了。\n剩余次数: {plugin._get_user_count(user_id)}")
        return
    if str(plugin.conf.get("enable_random_checkin", False)).lower() == "true":
        max_reward = max(1, int(plugin.conf.get("checkin_random_reward_max", 5)))
        reward = random.randint(1, max_reward)
    else:
        reward = int(plugin.conf.get("checkin_fixed_reward", 3))
    current_count = plugin._get_user_count(user_id)
    new_count = current_count + reward
    plugin.user_counts[user_id] = new_count
    await save_user_counts(plugin)
    plugin.user_checkin_data[user_id] = today_str
    await save_user_checkin_data(plugin)
    yield event.plain_result(f"🎉 签到成功！获得 {reward} 次，当前剩余: {new_count} 次。")


async def add_user_counts(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    cmd_text = event.message_str.strip()
    at_seg = next((s for s in event.message_obj.message if isinstance(s, At)), None)
    target_qq, count = None, 0
    if at_seg:
        target_qq = str(at_seg.qq)
        match = re.search(r"(\d+)\s*$", cmd_text)
        if match:
            count = int(match.group(1))
    else:
        match = re.search(r"(\d+)\s+(\d+)", cmd_text)
        if match:
            target_qq, count = match.group(1), int(match.group(2))
    if not target_qq or count <= 0:
        yield event.plain_result('格式错误:\n#手办化增加用户次数 @用户 <次数>\n或 #手办化增加用户次数 <QQ号> <次数>')
        return
    current_count = plugin._get_user_count(target_qq)
    plugin.user_counts[str(target_qq)] = current_count + count
    await save_user_counts(plugin)
    yield event.plain_result(f"✅ 已为用户 {target_qq} 增加 {count} 次，TA当前剩余 {current_count + count} 次。")


async def add_group_counts(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    match = re.search(r"(\d+)\s+(\d+)", event.message_str.strip())
    if not match:
        yield event.plain_result('格式错误: #手办化增加群组次数 <群号> <次数>')
        return
    target_group, count = match.group(1), int(match.group(2))
    current_count = plugin._get_group_count(target_group)
    plugin.group_counts[str(target_group)] = current_count + count
    await save_group_counts(plugin)
    yield event.plain_result(f"✅ 已为群组 {target_group} 增加 {count} 次，该群当前剩余 {current_count + count} 次。")


async def query_counts(plugin, event: AstrMessageEvent):
    user_id_to_query = event.get_sender_id()
    if plugin.is_global_admin(event):
        at_seg = next((s for s in event.message_obj.message if isinstance(s, At)), None)
        if at_seg:
            user_id_to_query = str(at_seg.qq)
        else:
            match = re.search(r"(\d+)", event.message_str)
            if match:
                user_id_to_query = match.group(1)
    user_count = plugin._get_user_count(user_id_to_query)
    reply_msg = f"用户 {user_id_to_query} 个人剩余次数为: {user_count}"
    if user_id_to_query == event.get_sender_id():
        reply_msg = f"您好，您当前个人剩余次数为: {user_count}"
    if group_id := event.get_group_id():
        reply_msg += f"\n本群共享剩余次数为: {plugin._get_group_count(group_id)}"
    yield event.plain_result(reply_msg)
