from typing import Optional

from astrbot.core.platform.astr_message_event import AstrMessageEvent


async def add_key(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    new_keys = event.message_str.strip().split()
    if not new_keys:
        yield event.plain_result("格式错误，请提供要添加的Key。")
        return
    api_keys = plugin.conf.get("api_keys", [])
    added_keys = [key for key in new_keys if key not in api_keys]
    api_keys.extend(added_keys)
    await plugin.conf.set("api_keys", api_keys)
    yield event.plain_result(f"✅ 操作完成，新增 {len(added_keys)} 个Key，当前共 {len(api_keys)} 个。")


async def list_keys(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    api_keys = plugin.conf.get("api_keys", [])
    if not api_keys:
        yield event.plain_result("📝 暂未配置任何 API Key。")
        return
    key_list_str = "\n".join(f"{i + 1}. {key[:8]}...{key[-4:]}" for i, key in enumerate(api_keys))
    yield event.plain_result(f"🔑 API Key 列表:\n{key_list_str}")


async def delete_key(plugin, event: AstrMessageEvent):
    if not plugin.is_global_admin(event):
        return
    param = event.message_str.strip()
    api_keys = plugin.conf.get("api_keys", [])
    if param.lower() == "all":
        await plugin.conf.set("api_keys", [])
        yield event.plain_result(f"✅ 已删除全部 {len(api_keys)} 个 Key。")
    elif param.isdigit() and 1 <= int(param) <= len(api_keys):
        removed_key = api_keys.pop(int(param) - 1)
        await plugin.conf.set("api_keys", api_keys)
        yield event.plain_result(f"✅ 已删除 Key: {removed_key[:8]}...")
    else:
        yield event.plain_result("格式错误，请使用 #手办化删除key <序号|all>")


async def get_api_key(plugin) -> Optional[str]:
    keys = plugin.conf.get("api_keys", [])
    if not keys:
        return None
    async with plugin.key_lock:
        key = keys[plugin.key_index]
        plugin.key_index = (plugin.key_index + 1) % len(keys)
        return key
