from typing import List

from astrbot import logger
from astrbot.core.platform.astr_message_event import AstrMessageEvent


def _get_prompt_list(plugin) -> List[str]:
    prompt_list = plugin.conf.get("prompt_list", [])
    return prompt_list if isinstance(prompt_list, list) else []


async def _persist_prompt_list(plugin, prompt_list: List[str]) -> None:
    await plugin.conf.set("prompt_list", prompt_list)
    await load_prompt_map(plugin)


def _find_prompt_index(prompt_list: List[str], key: str) -> int:
    for idx, item in enumerate(prompt_list):
        if item.strip().startswith(f"{key}:"):
            return idx
    return -1


async def load_prompt_map(plugin) -> None:
    logger.info("正在加载 prompts...")
    plugin.prompt_map.clear()
    prompt_list = _get_prompt_list(plugin)
    for item in prompt_list:
        try:
            if ":" in item:
                key, value = item.split(":", 1)
                plugin.prompt_map[key.strip()] = value.strip()
            else:
                logger.warning(f"跳过格式错误的 prompt (缺少冒号): {item}")
        except ValueError:
            logger.warning(f"跳过格式错误的 prompt: {item}")
    logger.info(f"加载了 {len(plugin.prompt_map)} 个 prompts。")


async def add_lm_prompt(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    raw = event.message_str.strip()
    if ":" not in raw:
        yield event.plain_result('格式错误, 正确示例:\n/lm添加 姿势表:为这幅图创建一个姿势表, 摆出各种姿势')
        return

    key, new_value = map(str.strip, raw.split(":", 1))
    prompt_list = _get_prompt_list(plugin)
    idx = _find_prompt_index(prompt_list, key)
    if idx >= 0:
        prompt_list[idx] = f"{key}:{new_value}"
    else:
        prompt_list.append(f"{key}:{new_value}")

    await _persist_prompt_list(plugin, prompt_list)
    yield event.plain_result(f"已保存LM生图提示语:\n{key}:{new_value}")


async def list_prompts(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    prompt_list = _get_prompt_list(plugin)
    if not prompt_list:
        yield event.plain_result("当前没有配置任何提示词。")
        return
    lines = ["当前提示词列表:"]
    for idx, entry in enumerate(prompt_list, start=1):
        lines.append(f"{idx}. {entry}")
    text = "\n".join(lines)
    try:
        url = await plugin.text_to_image(text)
        yield event.image_result(url)
    except Exception as exc:
        logger.error(f"lm列表文本转图片失败: {exc}")
        yield event.plain_result(text)


async def update_prompt(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    raw = event.message_str.strip()
    if ":" not in raw:
        yield event.plain_result('格式错误, 正确示例:\n/lm修改 姿势表:新的提示内容')
        return
    key, value = map(str.strip, raw.split(":", 1))
    prompt_list = _get_prompt_list(plugin)
    idx = _find_prompt_index(prompt_list, key)
    if idx < 0:
        yield event.plain_result(f"未找到需要修改的提示词 [{key}]，请先添加。")
        return
    prompt_list[idx] = f"{key}:{value}"
    await _persist_prompt_list(plugin, prompt_list)
    yield event.plain_result(f"✅ 已更新提示词:\n{key}:{value}")


async def delete_prompt(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    key = event.message_str.strip()
    if not key:
        yield event.plain_result('格式错误, 正确示例:\n/lm删除 姿势表')
        return
    prompt_list = _get_prompt_list(plugin)
    idx = _find_prompt_index(prompt_list, key)
    if idx < 0:
        yield event.plain_result(f"未找到提示词 [{key}]，无法删除。")
        return
    removed = prompt_list.pop(idx)
    await _persist_prompt_list(plugin, prompt_list)
    yield event.plain_result(f"✅ 已删除提示词: {removed}")
