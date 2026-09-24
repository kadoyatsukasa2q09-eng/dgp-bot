import discord
from discord import app_commands, Embed, Member
from discord.ext import tasks
import random
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ======================【全域常數設定】======================
MAX_PLAYERS = 100
AUTO_ELIMINATE_INTERVAL = 60
PLAYER_MAX_HP = 1000
PLAYER_DAMAGE_TAKEN = 50
HEAL_BY_SET_BUCKLE = 30
HEAL_REST_PERIOD = 50
# 大賽頻道 ID：可用環境變數 DGP_ALLOWED_CHANNEL_ID 覆寫（雲端部署用）
ALLOWED_CHANNEL_ID = int(os.environ.get("DGP_ALLOWED_CHANNEL_ID", "1516742058633728023"))

# 遊戲管理者：填入 Discord 使用者ID（數字），不需要報名入場即可使用全部管理指令
# 可用環境變數 DGP_ADMIN_IDS 覆寫（逗號分隔，雲端部署用）
GAME_ADMIN_IDS = [int(x) for x in os.environ.get("DGP_ADMIN_IDS", "").split(",") if x.strip()]

# 遊戲全域狀態
riders = dict()
game_active = False
sign_up_open = False
waiting_info = dict()

rest_period = True
jyamato_active = False
wait_boss_stage = False

boss_active = False
boss_hp = 0
MAX_BOSS_HP = 1000
BOSS_DAMAGE = 100
last_fight_boss_user = ""
last_game_ranking = []

# 邪魔徒資料
normal_jyamato = [
    {"name": "小型邪魔徒", "point": 50},
    {"name": "一般邪魔徒", "point": 80},
    {"name": "大型邪魔徒", "point": 120},
    {"name": "強化邪魔徒", "point": 150}
]

# 扣具資料
NORMAL_BUCKLES = ["Magnum", "Zombie", "Ninja", "Monster", "Beat", "Fever", "Arrow", "water", "claw", "drill", "chain array", "hammer"]
SEMI_RARE_BUCKLES = ["boost", "boost mk 2", "powered builder", "command twin", "fantasy", "jyamato"]
RARE_BUCKLES = ["bujin sword", "geats ix"]
ALL_BUCKLES = NORMAL_BUCKLES + SEMI_RARE_BUCKLES + RARE_BUCKLES
RARE_CHANCE = 0.15

# 身分組
ROLE_HOST = "主辦方"
ROLE_PARTICIPANT = "DGP參賽者"
ROLE_CHAMPION = "DGP冠軍"

# 扣具別名
BUCKLE_SHORTCUTS = {
    "BS": "bujin sword",
    "MAG": "Magnum",
    "GIX": "geats ix",
    "W": "water",
    "A": "Arrow",
    "MK2": "boost mk 2",
    "H": "hammer",
    "CA": "chain array",
    "N": "ninja",
    "BE": "beat",
    "C": "claw",
    "FA": "fantasy",
    "FE": "Fever",
    "CT": "command twin",
    "D": "drill",
    "BO": "boost",
    "Z": "Zombie",
    "MON": "monster",
    "P_BUILDER": "powered builder",
    "J": "jyamato"
}

# ======================【通用工具函數】======================
def resolve_buckle_shortcut(name: str) -> str:
    raw = name.strip()
    upper_raw = raw.upper()
    if upper_raw in BUCKLE_SHORTCUTS:
        return BUCKLE_SHORTCUTS[upper_raw]
    return raw

def get_used_names():
    return [r["riderName"].lower() for r in riders.values()]

async def send_global_embed(embed: Embed):
    channel = bot.get_channel(ALLOWED_CHANNEL_ID)
    if channel and isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"訊息發送失敗: {e}")

def is_host(interaction: discord.Interaction):
    # 遊戲管理者：填入 GAME_ADMIN_IDS 的使用者，不需參賽即可使用管理指令
    if interaction.user.id in GAME_ADMIN_IDS:
        return True
    if interaction.user.guild_permissions.kick_members:
        return True
    if isinstance(interaction.user, Member):
        for role in interaction.user.roles:
            if role.name == ROLE_HOST:
                return True
    return False

def get_random_buckle():
    if random.random() < RARE_CHANCE:
        return random.choice(RARE_BUCKLES)
    return random.choice(NORMAL_BUCKLES + SEMI_RARE_BUCKLES)

def heal_player_rest(player):
    player["hp"] = min(player["hp"] + HEAL_REST_PERIOD, PLAYER_MAX_HP)

async def check_player_death(user_id: str, guild: discord.Guild):
    if user_id in riders and riders[user_id]["hp"] <= 0:
        p_data = riders.pop(user_id)
        member = guild.get_member(int(user_id))
        if member:
            part_role = discord.utils.get(guild.roles, name=ROLE_PARTICIPANT)
            if part_role:
                try:
                    await member.remove_roles(part_role)
                except:
                    pass
        embed = Embed(title="💔 選手血量歸零・遭到淘汰！", color=0x3a0000)
        embed.description = f"騎士 **{p_data['riderName']}** 因傷勢過重失去參賽資格！\n剩餘人數：{len(riders)}/{MAX_PLAYERS}"
        await send_global_embed(embed)
        if len(riders) <= 1 and game_active:
            await auto_final_process()

def check_is_dgp_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != ALLOWED_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ 這裡不是 DGP 戰場！請至指定頻道 <#{ALLOWED_CHANNEL_ID}> 使用大賽指令。",
                ephemeral=True
            )
        return interaction.channel_id == ALLOWED_CHANNEL_ID
    return app_commands.check(predicate)

async def check_and_trigger_mission_clear(user_id: str, member: Member):
    p = riders.get(user_id)
    if not p or not p.get("active_mission"):
        return
    m = p["active_mission"]
    if m["current"] >= m["target"]:
        add_p = m["reward"]
        p["points"] += add_p
        embed = Embed(title=f"🎉 MISSION CLEAR ! 任務自動達成！", color=0x00ff00)
        embed.description = (
            f"恭喜騎士 **{p['riderName']}** ({member.mention})！\n"
            f"機器人感應到數據達標，自動結算秘密任務：\n"
            f"👉 **{m['description']}** (最終進度: `{m['current']}/{m['target']}`)"
        )
        embed.add_field(name="任務獎勵", value=f"`+{add_p} 積分`", inline=True)
        embed.add_field(name="目前總積分", value=f"`{p['points']} 積分`", inline=True)
        await send_global_embed(embed)
        p["active_mission"] = None

def get_buckle_attack_bonus(buckle_name: str) -> int:
    bl = buckle_name.lower()
    if bl == "bujin sword":
        return 100
    elif bl == "geats ix":
        return 200
    elif bl == "jyamato":
        return 200
    return 0

def get_buckle_is_rare_def(buckle_name: str) -> bool:
    return buckle_name.lower() in [x.lower() for x in RARE_BUCKLES]

def get_buckle_has_jyamato_shield(buckle_name: str) -> bool:
    return buckle_name.lower() == "jyamato"

# ======================【大賽結算邏輯】======================
async def auto_final_process():
    global game_active, sign_up_open, boss_active, rest_period
    global jyamato_active, wait_boss_stage, boss_hp, last_fight_boss_user, last_game_ranking

    game_active = False
    sign_up_open = False
    boss_active = False
    rest_period = True
    jyamato_active = False
    wait_boss_stage = False
    boss_hp = 0
    last_fight_boss_user = ""
    if not riders:
        return

    sorted_riders = sorted(list(riders.values()), key=lambda x:x["points"], reverse=True)
    last_game_ranking = sorted_riders.copy()

    winner_id, winner_data = random.choice(list(riders.items()))
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    part_role = discord.utils.get(guild.roles, name=ROLE_PARTICIPANT)
    champ_role = discord.utils.get(guild.roles, name=ROLE_CHAMPION)
    winner_member = guild.get_member(int(winner_id))
    if winner_member and part_role:
        try:
            await winner_member.remove_roles(part_role)
        except:
            pass
    if winner_member and champ_role:
        try:
            await winner_member.add_roles(champ_role)
        except:
            pass

    embed_win = Embed(title="🏆 決戰落幕！創世之神誕生！", color=0x9900ff)
    embed_win.description = f"本屆 DGP 冠軍：**{winner_data['riderName']}**\n恭喜獲得【{ROLE_CHAMPION}】稱號！"
    await send_global_embed(embed_win)

    embed_wish = Embed(title="✨ 理想的世界已重塑！", color=0xff00ff)
    embed_wish.add_field(name="冠軍實現的願望", value=winner_data.get("wish", "未填寫願望"), inline=False)
    embed_wish.add_field(name="最終累計總積分", value=str(winner_data.get("points", 0)), inline=False)
    embed_wish.description = "大賽圓滿結束，等待管理員使用 `/ready` 重新開啟新一輪大賽！"
    await send_global_embed(embed_wish)

    if part_role:
        for m in guild.members:
            try:
                await m.remove_roles(part_role)
            except:
                pass
    riders.clear()
    waiting_info.clear()

@tasks.loop(seconds=AUTO_ELIMINATE_INTERVAL)
async def auto_eliminate():
    return

# ======================【Bot 主程式初始化】======================
class DGPBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        auto_eliminate.start()

bot = DGPBot()

@bot.event
async def on_ready():
    print(f"✅ DGP 欲望大賽 上線｜登入 {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ 已同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"指令同步失敗: {e}")
    await bot.change_presence(activity=discord.Game(name="/help 查看指令"))

# ======================【模組1：入場報名｜玩家資訊指令】======================
@bot.tree.command(name="help", description="DGP欲望大賽｜全部指令快速查閱")
@check_is_dgp_channel()
async def help_command(interaction: discord.Interaction):
    embed = Embed(title="🎮 DGP 欲望大賽｜指令一覽", color=0x2980b9)
    embed.add_field(
        name="🧑‍🤝‍🧑 玩家｜入場與資訊",
        value="""
`/entry [騎士名] [願望]` — 報名參賽
`/name_change [新名稱]` — 修改騎士名稱
`/health` — 查看血量&任務進度
`/rank` — 參賽者積分排行榜
`/rule` — 顯示完整大賽規則
""",
        inline=False
    )
    embed.add_field(
        name="⚔️ 玩家｜戰鬥與扣具",
        value="""
`/henshin` — 基礎變身(Entry Form)
`/set_buckle [扣具/簡稱]` — 單扣裝備，退出Dual‑On
`/dual_on [扣具1] [扣具2]` — Dual‑On雙扣同時裝備
`/dual_off` — 關閉Dual‑On，回到單扣模式
`/buckle_inventory` — 查看扣具背包&槽位
`/give_buckle [扣具] @玩家` — 轉贈扣具
`/gacha` — 抽扣具(首次免費，之後100積分)
`/fight` — 對邪魔徒/BOSS戰鬥
`/mission` — 領取隨機任務(後台自動結算)
`/battle @玩家` — 騎士PVP內戰
""",
        inline=False
    )
    embed.add_field(
        name="👑 主辦方｜大賽控制",
        value="""
`/ready` — 重置大賽、開啟報名
`/start` — 關閉報名，正式開戰
`/jyamato` — 召喚邪魔徒小兵
`/end_jyamato` — 清除小兵，進入等待BOSS
`/boss` — 召喚BOSS邪魔徒
`/elim @玩家` — 手動淘汰選手
`/game_stop` — 強制暫停大賽(保留數據)
`/game_resume` — 恢復被暫停的大賽
`/export_last_rank` — 匯出上一局排名
""",
        inline=False
    )
    embed.add_field(
        name="📌 扣具簡稱可用清單",
        value="""
`p_builder` → powered builder
`BS` → bujin sword
`GIX` → geats ix
`MK2` → boost mk 2
`J` → jyamato(邪魔徒半稀有扣具)

範例：`/set_buckle J`｜`/dual_on MAG J`
""",
        inline=False
    )
    embed.add_field(
        name="💡重要機制備註",
        value="""
• Dual‑On雙扣模式：兩個扣具攻擊加成疊加；被動防禦PVP全部生效；`/set_buckle`會退出雙扣
• 戰鬥完不會自動解除變身，只有擊敗BOSS才會解除
• jyamato：全場景攻擊+200；**僅PVP對戰可抵擋80%>80傷害，打邪魔徒/BOSS防禦無效**
• 稀有扣具：反擊傷害僅承受1/4，擁有攻擊加成
• 已關閉自動淘汰；僅手動/血量歸零淘汰
• PVP內戰血量歸零會直接淘汰選手
""",
        inline=False
    )
    embed.set_footer(text="DGP欲望大賽｜使用 /help 查詢本介面")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rule", description="查看 DGP 欲望大賽完整說明與指令集")
@check_is_dgp_channel()
async def rule_command(interaction: discord.Interaction):
    embed = Embed(title="📜 DGP 欲望大賽 完整規則", color=0x3399ff)
    embed.add_field(
        name="👑 【管理員 / 主辦方 指令】",
        value="`/ready` — 重置系統、開啟報名階段\n`/start` — 關閉報名、正式開始遊戲\n`/jyamato` — 開啟邪魔徒出沒階段\n`/end_jyamato` — 進入等待BOSS階段\n`/boss` — 召喚 BOSS 登場\n`/elim` — 手動淘汰選手\n`/game_stop` — 強制暫停大賽(保留玩家資料)\n`/game_resume` — 恢復已暫停大賽\n`/export_last_rank` — 匯出上一局排名",
        inline=False
    )
    embed.add_field(
        name="🦊 【玩家基礎指令】",
        value="`/entry` — 報名參賽\n`/name_change` — 修改騎士名稱\n`/henshin` — 基礎變身（Entry Form）\n`/set_buckle` — 單扣裝備扣具\n`/dual_on [扣1][扣2]` — Dual‑On雙扣同時裝備\n`/dual_off` — 退出雙扣模式\n`/fight` — 迎戰敵人（需先變身）\n`/mission` — 領取大賽隨機秘密任務\n`/health` — 查看自身血量與任務狀態\n`/rank` — 查看排行榜\n`/battle @玩家` — 騎士PVP內戰對決",
        inline=False
    )
    embed.add_field(
        name="⚔️ 【Dual‑On雙扣機制】",
        value="可同時裝備兩個背包內已擁有的扣具，攻擊加成全部疊加；PVP被動防禦全部生效；打邪魔徒/BOSS僅攻擊生效。執行`/set_buckle`會自動退出雙扣模式。",
        inline=False
    )
    embed.add_field(
        name="📌 扣具簡稱&特殊扣具說明",
        value="`p_builder` = powered builder，`J`=jyamato\n`jyamato(邪魔徒半稀有扣具)`：攻擊+200，**僅PVP騎士對打時，抵擋80%大於80的傷害，對邪魔徒/BOSS防禦效果無效**",
        inline=False
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="entry", description="報名參賽（僅報名階段可用）")
@app_commands.describe(rider_name="你的騎士名稱", wish="你若獲勝想要實現的願望")
@check_is_dgp_channel()
async def entry_command(interaction: discord.Interaction, rider_name: str, wish: str):
    if not sign_up_open:
        return await interaction.response.send_message("❌ 目前非報名階段，無法加入！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id in riders:
        return await interaction.response.send_message("❌ 你已經是參賽選手！", ephemeral=True)
    if len(riders) >= MAX_PLAYERS:
        return await interaction.response.send_message("🚫 名額已滿！", ephemeral=True)
    if rider_name.lower() in get_used_names():
        return await interaction.response.send_message("❌ 此名稱已被其他騎士使用！", ephemeral=True)

    id_core = f"ID-{random.random():.8f}".upper().replace(".", "")
    riders[user_id] = {
        "username": interaction.user.name,
        "riderName": rider_name,
        "idCore": id_core,
        "wish": wish,
        "points": 0,
        "buckles": [],
        "equipBuckle": "",
        "dual_on": False,
        "slot_left": None,
        "slot_right": None,
        "isHenshin": False,
        "hp": PLAYER_MAX_HP,
        "gacha_count": 0,
        "active_mission": None
    }
    part_role = discord.utils.get(interaction.guild.roles, name=ROLE_PARTICIPANT)
    if part_role and isinstance(interaction.user, Member):
        try:
            await interaction.user.add_roles(part_role)
        except:
            pass
    embed = Embed(title="🎟️ 欲望驅動器已發放・報名成功！", color=0xe60000)
    embed.add_field(name="騎士名稱", value=rider_name, inline=True)
    embed.add_field(name="ID核心編號", value=id_core, inline=True)
    embed.add_field(name="個人願望", value=wish, inline=False)
    embed.add_field(name="目前參賽人數", value=f"{len(riders)}/{MAX_PLAYERS}", inline=True)
    embed.description = "請靜待管理員使用 `/start` 開啟遊戲大賽！"
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="health", description="查看自身當前的血量與進行中的任務")
@check_is_dgp_channel()
async def health_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非本屆大賽選手！", ephemeral=True)
    p = riders[user_id]
    msg = f"❤️ 【{p['riderName']}】當前血量：`{p['hp']}/{PLAYER_MAX_HP}`"
    if p.get("active_mission"):
        m = p["active_mission"]
        m_type = "隻" if m["type"] == "kill" else "點"
        msg += f"\n📜 **進行中的任務**：{m['description']}\n📊 **目前判定進度**：`{m['current']}/{m['target']}` {m_type}"
    else:
        msg += f"\n📜 **目前無進行中任務**。可在非休息時段輸入 `/mission` 領取！"
    await interaction.response.send_message(msg)

@bot.tree.command(name="name_change", description="修改你的騎士名稱")
@check_is_dgp_channel()
async def name_change_command(interaction: discord.Interaction, new_name: str):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    if new_name.lower() in get_used_names():
        return await interaction.response.send_message(f"❌ 名稱「{new_name}」已被佔用！", ephemeral=True)
    p = riders[user_id]
    old_name = p["riderName"]
    p["riderName"] = new_name
    await interaction.response.send_message(f"✅ 名稱變更成功：**{old_name}** ➔ **{new_name}**")

@bot.tree.command(name="rank", description="查看當前參賽名單與積分排行")
@check_is_dgp_channel()
async def rank_command(interaction: discord.Interaction):
    if not riders:
        return await interaction.response.send_message("📊 目前大賽沒有參賽選手。", ephemeral=True)
    sorted_riders = sorted(riders.values(), key=lambda x: x["points"], reverse=True)
    lines = []
    for idx, val in enumerate(sorted_riders, 1):
        if val["dual_on"]:
            eq_text = f"[Dual‑On] {val['slot_left']} + {val['slot_right']}"
        else:
            eq_text = val["equipBuckle"] if val["equipBuckle"] else "無"
        lines.append(f"#{idx} **{val['riderName']}** | 積分：`{val['points']}` | 血量：`{val['hp']}/{PLAYER_MAX_HP}` | 帶扣：`{eq_text}`")
    embed = Embed(title=f"📈 DGP 參賽名單與排行（{len(riders)}/{MAX_PLAYERS}）", description="\n".join(lines), color=0xffd700)
    await interaction.response.send_message(embed=embed)

# ======================【模組2：戰鬥｜變身、扣具、抽卡、Dual‑On、戰鬥、PVP、任務】======================
@bot.tree.command(name="henshin", description="基礎變身！進入 Entry Form 狀態")
@check_is_dgp_channel()
async def henshin_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    riders[user_id]["isHenshin"] = True
    embed = Embed(title="🦊 ENTRY RAISE !", color=0x00bfff)
    embed.description = f"騎士 **{riders[user_id]['riderName']}** 完成基礎變身，準備迎戰！"
    await interaction.response.send_message("變身成功！")
    await send_global_embed(embed)

@bot.tree.command(name="gacha", description="隨機抽取一個神秘帶扣（Buckle）")
@check_is_dgp_channel()
async def gacha_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    if "gacha_count" not in p:
        p["gacha_count"] = 0
    if p["gacha_count"] > 0:
        if p["points"] < 100:
            return await interaction.response.send_message(f"❌ 抽獎失敗！第二次開始每次需要 `100` 點積分，你目前只有 `{p['points']}` 點。", ephemeral=True)
        p["points"] -= 100
        cost_msg = "（扣除 100 點積分）"
    else:
        cost_msg = "（首次抽獎免費！）"
    p["gacha_count"] += 1
    buckle = get_random_buckle()
    p["buckles"].append(buckle)
    if buckle in RARE_BUCKLES:
        embed = Embed(title="🌟 HIGHLIGHT! 極度奢華！", color=0xffd700)
        embed.description = f"{interaction.user.mention} 幸運爆棚！抽中傳奇稀有帶扣：**{buckle.upper()}**！ {cost_msg}"
        embed.add_field(name="💰 當前剩餘積分", value=f"`{p['points']}` 點", inline=False)
        await interaction.response.send_message(embed=embed)
    else:
        embed = Embed(title="🎰 欲望大賽物資箱", color=0x9966ff)
        embed.description = f"獲得帶扣：**{buckle}**\n請使用 `/buckle_inventory` 查看背包並裝裝備。 {cost_msg}"
        embed.add_field(name="💰 當前剩餘積分", value=f"`{p['points']}` 點", inline=False)
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buckle_inventory", description="查看自己擁有的帶扣背包與裝備狀態(包含Dual‑On槽位)")
@check_is_dgp_channel()
async def buckle_inventory_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    inv = "、".join(p["buckles"]) if p["buckles"] else "無"
    if p["dual_on"]:
        eq_text = f"🟦左槽：`{p['slot_left']}`\n🟥右槽：`{p['slot_right']}`\n🔥【DUAL‑ON 雙扣模式開啟】"
    else:
        eq_text = p["equipBuckle"] if p["equipBuckle"] else "未裝備（Entry Form）"
    embed = Embed(title="🎒 我的帶扣背包", color=0x66ccff)
    embed.add_field(name="🎒 持有帶扣", value=inv, inline=False)
    embed.add_field(name="🦊 當前裝備狀態", value=eq_text, inline=False)
    embed.add_field(name="❤️ 當前血量", value=f"{p['hp']}/{PLAYER_MAX_HP}", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="set_buckle", description="裝備單個帶扣，會自動退出Dual‑On雙扣模式")
@app_commands.describe(buckle_name="扣具名稱或簡稱，例如 p_builder、J、BS、GIX")
@check_is_dgp_channel()
async def set_buckle_command(interaction: discord.Interaction, buckle_name: str):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    search_name = resolve_buckle_shortcut(buckle_name)
    matched_buckle = next((b for b in p["buckles"] if b.lower() == search_name.lower()), None)
    if not matched_buckle:
        return await interaction.response.send_message(f"❌ 你的背包裡沒有 {buckle_name} 這個帶扣！", ephemeral=True)

    p["dual_on"] = False
    p["slot_left"] = None
    p["slot_right"] = None

    p["isHenshin"] = True
    p["hp"] = min(p["hp"] + HEAL_BY_SET_BUCKLE, PLAYER_MAX_HP)
    p["equipBuckle"] = matched_buckle
    await interaction.response.send_message(f"成功插拔帶扣！已退出Dual‑On(若原先開啟)", ephemeral=True)
    if matched_buckle.lower() == "bujin sword":
        embed = Embed(title="⚔️ SET AVENGE ! BUJIN SWORD !", color=0xff4500)
        embed.description = f"{interaction.user.mention} 裝備了【武神之刃】！黑闇斬擊蓄勢待發！(傷害 +100)"
    elif matched_buckle.lower() == "geats ix":
        embed = Embed(title="🦊 SET IGNITION ! DYNAMITE BOOST ! GEATS IX !", color=0xff6600)
        embed.description = f"{interaction.user.mention} 裝備了【GEATS IX】！創世之力已降臨！(傷害 +200)"
    elif matched_buckle.lower() == "jyamato":
        embed = Embed(title="🌿 SET JYAMATO ! 邪魔徒裝甲 !", color=0x228B22)
        embed.description = f"{interaction.user.mention} 裝備了【Jyamato邪魔徒帶扣】！荊棘之力湧現！\n⚔️攻擊傷害+200｜🛡️PVP對戰時可抵擋80%大於80的傷害（對邪魔徒/BOSS無效）"
    else:
        embed = Embed(title="⚔️ WEAPON RAISE !", color=0x33dd33)
        embed.description = f"騎士 **{p['riderName']}** 裝備了 **{matched_buckle}** 帶扣！\n✨ 體力微幅回復，當前血量：`{p['hp']}/{PLAYER_MAX_HP}`"
    await send_global_embed(embed)

@bot.tree.command(name="dual_on", description="Dual‑On！同時裝備兩個扣具，兩個加成疊加，需要背包擁有兩個扣具")
@app_commands.describe(buckle1="第一個扣具/簡稱", buckle2="第二個扣具/簡稱")
@check_is_dgp_channel()
async def dual_on_command(interaction: discord.Interaction, buckle1: str, buckle2: str):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    s1 = resolve_buckle_shortcut(buckle1)
    s2 = resolve_buckle_shortcut(buckle2)
    b1 = next((b for b in p["buckles"] if b.lower() == s1.lower()), None)
    b2 = next((b for b in p["buckles"] if b.lower() == s2.lower()), None)
    if not b1 or not b2:
        return await interaction.response.send_message("❌ 你的背包沒有其中一個扣具！請確認兩個扣具都已經抽到。", ephemeral=True)
    if b1.lower() == b2.lower():
        return await interaction.response.send_message("❌ 不允許左右槽裝備同一個扣具！", ephemeral=True)

    p["dual_on"] = True
    p["slot_left"] = b1
    p["slot_right"] = b2
    p["isHenshin"] = True
    p["hp"] = min(p["hp"] + HEAL_BY_SET_BUCKLE, PLAYER_MAX_HP)
    await interaction.response.send_message("🔥 DUAL‑ON 雙重武裝！變身完成", ephemeral=True)
    embed = Embed(title="🔥 DUAL‑ON！GET READY FOR TWO POWER！", color=0xff8822)
    embed.description = (
        f"{interaction.user.mention} 驅動器雙槽全部装填！\n"
        f"🟦左槽：**{b1}**\n🟥右槽：**{b2}**\n"
        f"✨兩個扣具的攻擊加成全部疊加！PVP被動防禦同時生效\n"
        f"💡使用 `/dual_off` 關閉雙扣模式，或是 `/set_buckle` 切換單扣"
    )
    await send_global_embed(embed)

@bot.tree.command(name="dual_off", description="關閉Dual‑On雙扣模式，回到普通單扣狀態(清空左右槽)")
@check_is_dgp_channel()
async def dual_off_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    if not p["dual_on"]:
        return await interaction.response.send_message("⚠️ 你現在沒有開啟Dual‑On雙扣模式", ephemeral=True)
    p["dual_on"] = False
    p["slot_left"] = None
    p["slot_right"] = None
    await interaction.response.send_message("✅ 已關閉Dual‑On雙重武裝，回到Entry Form狀態，請使用 `/set_buckle`裝備單一扣具", ephemeral=True)

@bot.tree.command(name="give_buckle", description="將你的帶扣割愛轉贈給其他參賽騎士")
@app_commands.describe(buckle_name="扣具名/簡稱", target_player="接收的騎士")
@check_is_dgp_channel()
async def give_buckle_command(interaction: discord.Interaction, buckle_name: str, target_player: Member):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    user_id = str(interaction.user.id)
    target_id = str(target_player.id)
    if user_id not in riders or target_id not in riders:
        return await interaction.response.send_message("⚠️ 贈送方或接收方並非參賽選手！", ephemeral=True)
    sender = riders[user_id]
    receiver = riders[target_id]
    search_name = resolve_buckle_shortcut(buckle_name)
    matched_buckle = next((b for b in sender["buckles"] if b.lower() == search_name.lower()), None)
    if not matched_buckle:
        return await interaction.response.send_message(f"❌ 你身上沒有 {buckle_name} 帶扣可以轉贈！", ephemeral=True)
    sender["buckles"].remove(matched_buckle)
    receiver["buckles"].append(matched_buckle)
    embed = Embed(title="🔄 物資資助轉移", color=0xffaa00)
    embed.description = f"騎士 **{sender['riderName']}** 將帶扣 **{matched_buckle}** 轉贈交給了 **{receiver['riderName']}**！"
    await interaction.response.send_message("贈送成功！", ephemeral=True)
    await send_global_embed(embed)

@bot.tree.command(name="fight", description="迎戰當前場上的邪魔徒或 BOSS（需先完成變身）")
@check_is_dgp_channel()
async def fight_command(interaction: discord.Interaction):
    global boss_hp, boss_active, rest_period, wait_boss_stage, jyamato_active, last_fight_boss_user
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    if rest_period:
        return await interaction.response.send_message("☕ 目前為休息時段，邪魔徒尚未出沒，無法戰鬥！", ephemeral=True)
    if wait_boss_stage:
        return await interaction.response.send_message("⚠️ 戰場清理完畢，正等待 BOSS 降臨，目前沒有小兵！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    if not p["isHenshin"]:
        return await interaction.response.send_message("❌ 請先使用 `/henshin` / `/set_buckle` / `/dual_on` 進行武裝變身才能作戰！", ephemeral=True)
    take_dmg = PLAYER_DAMAGE_TAKEN

    atk_bonus = 0
    if p["dual_on"]:
        atk_bonus += get_buckle_attack_bonus(p["slot_left"])
        atk_bonus += get_buckle_attack_bonus(p["slot_right"])
    else:
        atk_bonus += get_buckle_attack_bonus(p["equipBuckle"])

    def_has_rare_def = False
    if p["dual_on"]:
        def_has_rare_def |= get_buckle_is_rare_def(p["slot_left"])
        def_has_rare_def |= get_buckle_is_rare_def(p["slot_right"])
    else:
        def_has_rare_def |= get_buckle_is_rare_def(p["equipBuckle"])
    if def_has_rare_def:
        take_dmg = PLAYER_DAMAGE_TAKEN // 4

    if boss_active:
        dmg = BOSS_DAMAGE + atk_bonus
        boss_hp -= dmg
        last_fight_boss_user = p["riderName"]
        is_counter = random.random() > 0.6
        if is_counter:
            p["hp"] -= take_dmg
        if p.get("active_mission") and p["active_mission"]["type"] == "damage":
            p["active_mission"]["current"] += dmg
        if boss_hp <= 0:
            boss_active = False
            rest_period = True
            wait_boss_stage = False
            jyamato_active = False
            for pl in riders.values():
                heal_player_rest(pl)
            p["points"] += 500
            if p.get("active_mission") and p["active_mission"]["type"] == "kill":
                p["active_mission"]["current"] += 1
            embed = Embed(title="💥 擊碎核心！BOSS 邪魔徒 被成功擊敗！", color=0xff8800)
            embed.description = (
                f"🎯 最後一擊締造者：**{last_fight_boss_user}**\n"
                f"獲得豐厚擊殺積分：`+500` | 目前總積分：`{p['points']}`\n"
                f"➔ **大賽進入休息時段，全體存活選手回復 50 血量！**"
            )
            await interaction.response.send_message("你給予了BOSS最後一擊！")
            await send_global_embed(embed)
            await check_and_trigger_mission_clear(user_id, interaction.user)
            await check_player_death(user_id, interaction.guild)
        else:
            txt = f"⚔️ 奮力一擊！你對 BOSS 造成了 `{dmg}` 點傷害！(BOSS 剩餘血量: {boss_hp}/{MAX_BOSS_HP})"
            if is_counter:
                txt += f"\n💥 糟了！你受到了 BOSS 的沉重反擊！血量扣減 `{take_dmg}`，當前釋放剩餘血量：`{p['hp']}`"
            await interaction.response.send_message(txt)
            await check_and_trigger_mission_clear(user_id, interaction.user)
            await check_player_death(user_id, interaction.guild)
    else:
        enemy = random.choice(normal_jyamato)
        win = random.random() > 0.3
        is_counter = random.random() > 0.6
        simulated_dmg = 100 + atk_bonus
        if win:
            p["points"] += enemy["point"]
            if is_counter:
                p["hp"] -= take_dmg
            if p.get("active_mission"):
                if p["active_mission"]["type"] == "kill":
                    p["active_mission"]["current"] += 1
                elif p["active_mission"]["type"] == "damage":
                    p["active_mission"]["current"] += simulated_dmg
            embed = Embed(title=f"🏆 討伐成功！擊敗 {enemy['name']}", color=0x00cc00)
            embed.add_field(name="賺取積分", value=f"`+{enemy['point']}`", inline=True)
            embed.add_field(name="當前總積分", value=f"`{p['points']}`", inline=True)
            embed.add_field(name="剩餘健康度", value=f"`{p['hp']}/{PLAYER_MAX_HP}`", inline=False)
            await interaction.response.send_message(embed=embed)
            await check_and_trigger_mission_clear(user_id, interaction.user)
            await check_player_death(user_id, interaction.guild)
        else:
            if is_counter:
                p["hp"] -= take_dmg
            if p.get("active_mission") and p["active_mission"]["type"] == "damage":
                p["active_mission"]["current"] += (simulated_dmg // 2)
            embed = Embed(title=f"💥 戰術失誤！遭到 {enemy['name']} 擊退", color=0xff3333)
            embed.description = f"作戰失敗且防線失守！你承受了反擊傷害 `-{take_dmg}`，當前剩餘血量：`{p['hp']}`"
            await interaction.response.send_message(embed=embed)
            await check_and_trigger_mission_clear(user_id, interaction.user)
            await check_player_death(user_id, interaction.guild)

@bot.tree.command(name="mission", description="接取大賽官方分發的全新秘密任務（完成時機器人會自動幫你判定結算）")
@check_is_dgp_channel()
async def mission_command(interaction: discord.Interaction):
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    if rest_period:
        return await interaction.response.send_message("☕ 休息階段無法執行與派發任務！", ephemeral=True)
    user_id = str(interaction.user.id)
    if user_id not in riders:
        return await interaction.response.send_message("❌ 你並非參賽選手！", ephemeral=True)
    p = riders[user_id]
    if p.get("active_mission") is not None:
        m = p["active_mission"]
        m_type = "隻" if m["type"] == "kill" else "點"
        return await interaction.response.send_message(
            f"❌ 你身上已經有一個指派任務了！\n任務：{m['description']}\n📊 當前自動記錄進度：`{m['current']}/{m['target']}` {m_type}。\n💡 *你只需要繼續使用 `/fight` 作戰，一旦達標，機器人就會在頻道自動跳出完成訊息！不需手動交付。*",
            ephemeral=True
        )
    is_secret = random.random() < 0.3
    task_type = random.choice(["kill", "damage"])
    if is_secret:
        add_p = 200
        t_name = "隱藏特殊任務"
        color = 0xffcc00
        if task_type == "kill":
            target_val = random.randint(4, 6)
            desc = f"使用 `/fight` 討伐並擊殺 **{target_val}** 隻邪魔徒"
        else:
            target_val = random.randint(400, 600)
            desc = f"使用 `/fight` 對敵軍累積造成 **{target_val}** 點傷害"
    else:
        add_p = 100
        t_name = "一般大賽任務"
        color = 0x0088ff
        if task_type == "kill":
            target_val = random.randint(1, 3)
            desc = f"使用 `/fight` 討伐並擊殺 **{target_val}** 隻邪魔徒"
        else:
            target_val = random.randint(100, 300)
            desc = f"使用 `/fight` 對敵軍累積造成 **{target_val}** 點傷害"
    p["active_mission"] = {
        "title_name": t_name,
        "type": task_type,
        "target": target_val,
        "current": 0,
        "reward": add_p,
        "description": desc
    }
    embed = Embed(title=f"📜 MISSION ACCEPTED ! 秘密任務接取成功！", color=color)
    embed.description = (
        f"**任務級別：** 【{t_name}】\n"
        f"**目標要求：** {desc}\n\n"
        f"💡 **【機器人貼心提示】**：\n"
        f"你現在可以去戰場安心使用 `/fight` 戰鬥了。每當你造成傷害或擊殺時，系統將在後台自動計算進度，**達標時機器人會自動在此發放完成廣播！**"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="battle", description="騎士內戰PVP，與其他參賽者戰鬥，支援Dual‑On雙扣加成與雙重被動")
@app_commands.describe(target="要挑戰的參賽者")
@check_is_dgp_channel()
async def battle_command(interaction: discord.Interaction, target: Member):
    if rest_period:
        return await interaction.response.send_message("❌ 休息階段無法發起內戰！", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 大賽尚未開始！", ephemeral=True)
    attacker_id = str(interaction.user.id)
    defender_id = str(target.id)
    if attacker_id not in riders:
        return await interaction.response.send_message("❌ 你不是本屆參賽騎士！", ephemeral=True)
    if defender_id not in riders:
        return await interaction.response.send_message("❌ 對方不是參賽騎士！", ephemeral=True)
    attacker = riders[attacker_id]
    defender = riders[defender_id]
    if not attacker["isHenshin"]:
        return await interaction.response.send_message("❌ 你必須先 /henshin /set_buckle /dual_on 變身才能戰鬥！", ephemeral=True)
    if not defender["isHenshin"]:
        return await interaction.response.send_message("❌ 對手尚未變身，無法開戰！", ephemeral=True)

    base_atk = 120
    if attacker["dual_on"]:
        base_atk += get_buckle_attack_bonus(attacker["slot_left"])
        base_atk += get_buckle_attack_bonus(attacker["slot_right"])
    else:
        base_atk += get_buckle_attack_bonus(attacker["equipBuckle"])

    take_dmg_def = base_atk
    msg_lines = []
    def_rare = False
    if defender["dual_on"]:
        def_rare |= get_buckle_is_rare_def(defender["slot_left"])
        def_rare |= get_buckle_is_rare_def(defender["slot_right"])
    else:
        def_rare |= get_buckle_is_rare_def(defender["equipBuckle"])
    if def_rare:
        take_dmg_def = int(take_dmg_def / 4)
        msg_lines.append("🛡️稀有扣具減傷生效，傷害縮減至1/4")

    def_jya_shield = False
    if defender["dual_on"]:
        def_jya_shield |= get_buckle_has_jyamato_shield(defender["slot_left"])
        def_jya_shield |= get_buckle_has_jyamato_shield(defender["slot_right"])
    else:
        def_jya_shield |= get_buckle_has_jyamato_shield(defender["equipBuckle"])
    if def_jya_shield and take_dmg_def > 80:
        original_d = take_dmg_def
        take_dmg_def = int(take_dmg_def * 0.2)
        msg_lines.append(f"🌿邪魔徒荊棘裝甲發動！抵擋80%傷害！原本:{original_d} →實際受到:{take_dmg_def}")

    counter_dmg = 0
    if random.randint(1, 100) >= 70:
        counter_dmg = random.randint(60, 110)
        if defender["dual_on"]:
            counter_dmg += get_buckle_attack_bonus(defender["slot_left"])
            counter_dmg += get_buckle_attack_bonus(defender["slot_right"])
        else:
            counter_dmg += get_buckle_attack_bonus(defender["equipBuckle"])

    defender["hp"] -= take_dmg_def
    attacker["hp"] -= counter_dmg

    gain_point = random.randint(20, 45)
    lose_point = random.randint(15, 35)
    attacker["points"] += gain_point
    defender["points"] -= lose_point

    riders[attacker_id] = attacker
    riders[defender_id] = defender

    await check_player_death(attacker_id, interaction.guild)
    await check_player_death(defender_id, interaction.guild)

    text = f"""⚔️騎士內戰對戰結果
進攻方：{attacker['riderName']} ({interaction.user.mention})
防守方：{defender['riderName']} ({target.mention})
進攻傷害：{take_dmg_def}
"""
    if msg_lines:
        text += "\n".join(msg_lines)+"\n"
    if counter_dmg > 0:
        text += f"💥防守方觸發反擊！反擊傷害：{counter_dmg}\n"
    text += f"""
{attacker['riderName']} HP：{attacker['hp']}｜積分 +{gain_point}
{defender['riderName']} HP：{defender['hp']}｜積分 -{lose_point}
"""
    await interaction.response.send_message(text)

# ======================【模組3：管理員｜大賽控制指令】======================
@bot.tree.command(name="game_stop", description="【管理員】強制暫停DGP大賽，保留所有玩家資料")
@check_is_dgp_channel()
async def game_stop_command(interaction: discord.Interaction):
    global game_active, rest_period, jyamato_active, boss_active, wait_boss_stage
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 僅限主辦方/管理員使用", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲並未執行", ephemeral=True)
    game_active = False
    rest_period = True
    jyamato_active = False
    boss_active = False
    wait_boss_stage = False
    embed = Embed(title="⏹️ 遊戲已強制暫停", color=0x999999)
    embed.description = "對局已掛起，全部玩家資料保留。\n使用 `/game_resume` 繼續遊戲。"
    await send_global_embed(embed)
    await interaction.response.send_message("✅ 已執行強制暫停", ephemeral=True)

@bot.tree.command(name="game_resume", description="【管理員】恢復被暫停的DGP大賽")
@check_is_dgp_channel()
async def game_resume_command(interaction: discord.Interaction):
    global game_active
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 僅限主辦方/管理員使用", ephemeral=True)
    if game_active:
        return await interaction.response.send_message("❌ 遊戲正在執行，不需恢復", ephemeral=True)
    if len(riders) == 0:
        return await interaction.response.send_message("❌ 沒有參賽選手，無法恢復，請使用 /ready 開新局", ephemeral=True)
    game_active = True
    embed = Embed(title="▶️ 遊戲已恢復執行", color=0x33dd33)
    embed.description = "從暫停狀態繼續DGP大賽。"
    await send_global_embed(embed)
    await interaction.response.send_message("✅ 已恢復遊戲", ephemeral=True)

@bot.tree.command(name="export_last_rank", description="【管理員】匯出上一局的排名紀錄")
@check_is_dgp_channel()
async def export_last_rank_command(interaction: discord.Interaction):
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 僅限主辦方/管理員使用", ephemeral=True)
    if not last_game_ranking:
        return await interaction.response.send_message("📭 沒有儲存上一局排名資料", ephemeral=True)
    lines = []
    for idx, entry in enumerate(last_game_ranking, 1):
        lines.append(f"#{idx} {entry['riderName']}｜積分:{entry['points']}｜願望:{entry['wish']}")
    embed = Embed(title="📋 上一局對局排名紀錄", description="\n".join(lines), color=0xffd700)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ready", description="【主辦方專用】重置系統並開放新一輪大賽的玩家報名通道")
@check_is_dgp_channel()
async def ready_command(interaction: discord.Interaction):
    global game_active, sign_up_open, boss_active, rest_period, jyamato_active, wait_boss_stage, boss_hp, last_fight_boss_user
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 只有被認成的【主辦方】或管理員能使用此權限！", ephemeral=True)
    if sign_up_open:
        return await interaction.response.send_message("⚠️ 報名通道本就處於開啟狀態！", ephemeral=True)
    game_active = False
    sign_up_open = True
    boss_active = False
    rest_period = True
    jyamato_active = False
    wait_boss_stage = False
    boss_hp = 0
    last_fight_boss_user = ""
    riders.clear()
    waiting_info.clear()
    await bot.change_presence(activity=discord.Game(name="DGP 報名開放中，使用 /entry"))
    embed = Embed(title="📢 DGP 欲望大賽｜參賽報名通道正式開啟！", color=0x2ecc71)
    embed.description = "請各位有意願改寫世界的準假面騎士們，使用斜線指令 `/entry` 登記姓名與願望！\n當主辦方準備就緒，將以 `/start` 封鎖通道並鳴槍開戰！"
    await interaction.response.send_message("大賽系統已重置，報名廣播已發出。")
    await send_global_embed(embed)

@bot.tree.command(name="start", description="【主辦方專用】截止選手報名，欲望大賽正式開戰")
@check_is_dgp_channel()
async def start_command(interaction: discord.Interaction):
    global game_active, sign_up_open, rest_period, jyamato_active, wait_boss_stage
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 權限不足！", ephemeral=True)
    if game_active:
        return await interaction.response.send_message("⚠️ 大賽早已在進行中！", ephemeral=True)
    if not sign_up_open:
        return await interaction.response.send_message("⚠️ 請先使用 `/ready` 啟動報名流程！", ephemeral=True)
    if len(riders) < 2:
        return await interaction.response.send_message(
            f"❌ 無法開始大賽！當前報名人數僅有 `{len(riders)}` 人。欲望大賽至少需要 2 名以上的選手才能開戰！",
            ephemeral=True
        )
    sign_up_open = False
    game_active = True
    rest_period = True
    jyamato_active = False
    wait_boss_stage = False
    for p in riders.values():
        heal_player_rest(p)
    await bot.change_presence(activity=discord.Game(name="DGP 激烈交戰中"))
    embed = Embed(title="⚔️ 欲望大賽・序幕正式拉開！", color=0xff4444)
    embed.description = "報名通道已永久關閉，不接受中途加入！\n目前大賽處於【第一輪休息時段】，全員血量充沛。請主辦方下達 `/jyamato` 指令引渡邪魔徒進場！"
    await interaction.response.send_message("大賽已正式激活！")
    await send_global_embed(embed)

@bot.tree.command(name="jyamato", description="【主辦方專用】驅使一般邪魔徒軍團入侵戰場")
@check_is_dgp_channel()
async def jyamato_command(interaction: discord.Interaction):
    global rest_period, jyamato_active, wait_boss_stage
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 權限不足！", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 欲望大賽尚未正式開始！", ephemeral=True)
    if boss_active:
        return await interaction.response.send_message("⚠️ BOSS 當前正在肆虐戰場，請先將其消滅！", ephemeral=True)
    if jyamato_active:
        return await interaction.response.send_message("⚠️ 邪魔徒攻勢已在演繹中！", ephemeral=True)
    rest_period = False
    jyamato_active = True
    wait_boss_stage = False
    enemy = random.choice(normal_jyamato)
    embed = Embed(title="👹 警報！邪魔徒大軍破壞結界來襲！", color=0x992d22)
    embed.description = f"偵測到大量 **{enemy['name']}** 的蹤跡！\n請全體騎士立刻完成變身，並以 `/fight` 捍衛城市！"
    await interaction.response.send_message("邪魔徒已投放。")
    await send_global_embed(embed)

@bot.tree.command(name="end_jyamato", description="【主辦方專用】終止小兵攻勢，令戰場進入等待 BOSS 降臨階段")
@check_is_dgp_channel()
async def end_jyamato_command(interaction: discord.Interaction):
    global jyamato_active, wait_boss_stage, rest_period
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 權限不足！", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    if not jyamato_active:
        return await interaction.response.send_message("⚠️ 當前戰場並非小兵邪魔徒肆虐階段！", ephemeral=True)
    jyamato_active = False
    wait_boss_stage = True
    rest_period = False
    embed = Embed(title="🛑 邪魔徒先鋒部隊已被完全驅散", color=0x666666)
    embed.description = "戰場已陷入死一般的寂靜...【等待 BOSS 戰略指令中】。\n請主辦方於適當時機使用 `/boss` 指令召喚最終頭目！"
    await interaction.response.send_message("已結束小兵突擊階段。")
    await send_global_embed(embed)

@bot.tree.command(name="boss", description="【主辦方專用】召喚最終 BOSS 邪魔徒強行降臨")
@check_is_dgp_channel()
async def boss_command(interaction: discord.Interaction):
    global wait_boss_stage, boss_active, boss_hp, last_fight_boss_user
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 權限不足！", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    if boss_active:
        return await interaction.response.send_message("⚠️ BOSS 早已橫行於場上！", ephemeral=True)
    if not wait_boss_stage:
        return await interaction.response.send_message("⚠️ 戰略衝突！請先利用 `/end_jyamato` 清除普通邪魔徒攻勢！", ephemeral=True)
    wait_boss_stage = False
    boss_active = True
    boss_hp = MAX_BOSS_HP
    last_fight_boss_user = ""
    embed = Embed(title="🔥 WARNING ! BOSS 級邪魔徒降臨！", color=0xff2222)
    embed.description = (
        f"🚨 **💥 威脅指數爆表 💥** 🚨\n"
        f"BOSS 總生命值：`{boss_hp}/{MAX_BOSS_HP}`\n"
        f"基礎攻擊傷害：`{BOSS_DAMAGE}`\n"
        f"請全體騎士通力協作，使用 `/fight` 抵禦進攻！補上最後一擊者將獨得 **500 積分**！"
    )
    await interaction.response.send_message("BOSS 指令已下達。")
    await send_global_embed(embed)

@bot.tree.command(name="elim", description="【主辦方專用】手動將指定違規 or 不合格的選手剝奪資格淘汰")
@check_is_dgp_channel()
async def elim_command(interaction: discord.Interaction, target_player: Member):
    if not is_host(interaction):
        return await interaction.response.send_message("⚠️ 權限不足！", ephemeral=True)
    if not game_active:
        return await interaction.response.send_message("❌ 遊戲尚未開始！", ephemeral=True)
    target_id = str(target_player.id)
    if target_id not in riders:
        return await interaction.response.send_message("⚠️ 該使用者並非參賽選手！", ephemeral=True)
    target_data = riders.pop(target_id)
    part_role = discord.utils.get(interaction.guild.roles, name=ROLE_PARTICIPANT)
    if part_role:
        try:
            await target_player.remove_roles(part_role)
        except:
            pass
    embed = Embed(title="💔 騎士參賽權益遭強制剝奪", color=0x660000)
    embed.description = f"管理員行使了主辦方特權，騎士 **{target_data['riderName']}** 被強制清除淘汰。\n剩餘人數：{len(riders)}/{MAX_PLAYERS}"
    await interaction.response.send_message(f"已淘汰該選手。")
    await send_global_embed(embed)
    if len(riders) <= 1 and game_active:
        await auto_final_process()

# ====================== Keep-Alive 網頁伺服器（Replit 免休眠用） ======================
# Replit 免費版會在沒人訪問時休眠，這個小型網頁伺服器讓 bot 隨時有回應，
# 配合定時訪問（UptimeRobot 或定期 ping）即可維持 bot 上線。
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("DGP 欲望大賽 bot 運行中 ✅".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # 不輸出雜訊到 log


def start_keep_alive():
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"🌐 Keep-Alive 網頁伺服器已啟動｜port {port}")


# ====================== 啟動Bot ======================
if __name__ == "__main__":
    start_keep_alive()
    TOKEN = os.environ.get("DGP_BOT_TOKEN", "填入你的Bot Token")
    bot.run(TOKEN)
