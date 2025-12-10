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
    "半融合": "生成角色与其他元素融合的半融合风格",
}

async def prompt_help(plugin, event: AstrMessageEvent):
    msg_lines = [
        "📘 手办化插件指令速览",
        "--------------------------------",
        "图生图: 发送图片 + 预设指令，或 @用户 + 预设指令",
        "文生图: /文生图 <描述>",
        "自定义提示词: /lm添加 <名称:提示词>",
        "查看提示词列表: /lm列表 (管理员)",
        "修改提示词: /lm修改 <名称:新提示词> (管理员)",
        "删除提示词: /lm删除 <名称> (管理员)",
        "查看预设效果: /lm效果 [预设名称]",
        "签到领取次数: /手办化签到",
        "查询次数: /手办化查询次数",
        "增加次数: /手办化增加用户次数  /手办化增加群组次数 (管理员)",
        "管理 API Key: /手办化添加key  /手办化key列表  /手办化删除key (管理员)",
    ]
    yield event.plain_result("\n".join(msg_lines))


async def show_effects(plugin, event: AstrMessageEvent):
    raw = event.message_str.strip()
    keyword = raw.split()[-1] if raw else ""
    if keyword:
        prompt = plugin.prompt_map.get(keyword)
        if not prompt:
            yield event.plain_result(f"未找到预设 [{keyword}]，请确认名称。")
            return
        description = COMMAND_DESCRIPTIONS.get(keyword, "暂无描述")
        msg = [
            f"🎯 预设 [{keyword}]",
            f"说明: {description}",
            "提示词:",
            prompt,
        ]
        yield event.plain_result("\n".join(msg))
        return

    msg_parts = ["🎨 可用图生图指令及效果说明 🎨", ""]
    for cmd_name in sorted(plugin.prompt_map.keys()):
        description = COMMAND_DESCRIPTIONS.get(cmd_name, "暂无描述")
        msg_parts.append(f"✨ {cmd_name}: {description}")

    msg_parts.append("")
    msg_parts.append("💡 使用 /lm效果 <预设名称> 查看具体提示词内容。")
    yield event.plain_result("\n".join(msg_parts))


