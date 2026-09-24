# 🦊 DGP 欲望大賽 Discord Bot

基於 discord.py 的假面騎士 Geats「欲望大賽」Discord 機器人。

## ✨ 功能總覽
- 完整報名 / 開賽 / 邪魔徒 / BOSS / 結算流程
- 扣具系統（抽卡、背包、贈送、簡稱別名）
- **Dual‑On 雙扣具**：左右槽同時裝備，攻擊加成疊加
- **Jyamato（邪魔徒）帶扣**：半稀有，攻擊+200，PVP 抵擋 80% 傷害
- 騎士 PVP 內戰 `/battle`
- 自動任務系統（後台自動結算）
- 遊戲暫停 / 恢復 / 匯出上一局排名
- 遊戲管理者（不需參賽即可管理）／主辦方／管理員權限

## 🚀 快速開始

### 1. 安裝依賴
```bash
pip install -r requirements.txt
```

### 2. 設定環境變數（重要！）
```bash
export DGP_BOT_TOKEN="你的Discord Bot Token"
```
或在本機建立 `.env`：
```
DGP_BOT_TOKEN=你的Token
```

### 3. 設定基本參數（main.py 頂部）
- `ALLOWED_CHANNEL_ID`：大賽專用頻道 ID
- `GAME_ADMIN_IDS`：遊戲管理者 Discord 使用者 ID 清單（不需參賽即可使用管理指令）

### 4. 執行
```bash
python main.py
```

## ⚠️ 安全提醒
**絕對不要把你的 Bot Token 提交到 GitHub。** 本專案已用 `.gitignore` 排除 `.env`，
請務必用環境變數或 `.env` 存放 Token，不要寫死在 `main.py`。

## ☁️ 雲端部署（Railway，24 小時運作）
1. 到 https://railway.app 用 **GitHub 帳號**登入
2. **New Project → Deploy from GitHub repo** → 選 `dgp-bot`
3. 在 **Variables** 新增以下環境變數：

| 變數 | 說明 |
|---|---|
| `DGP_BOT_TOKEN` | 你的 Discord Bot Token（必填） |
| `DGP_ALLOWED_CHANNEL_ID` | 大賽專用頻道 ID（選填，不填用程式內預設值） |
| `DGP_ADMIN_IDS` | 遊戲管理者 ID，多個用逗號分隔，例如 `111,222`（選填） |

4. Railway 會自動安裝依賴並執行 `python main.py`（由 `Procfile` 指定）
5. 部署完成後，Discord 內輸入 `/help` 測試

> 💡 之後更新：改完程式 `git push` 到 GitHub，Railway 會自動重新部署。

## 🧩 Replit 部署（免費，但會休眠）
1. 到 https://replit.com 登入
2. **Create** → **Import from GitHub** → 貼上 `https://github.com/kadoyatsukasa2q09-eng/dgp-bot`
3. 左側 **Tools → Secrets** 新增 `DGP_BOT_TOKEN`（你的 Bot Token）
4. 按 **Run** 執行，bot 上線
5. 開啟上方 Webview 網址（形如 `https://xxxx.repl.co`），複製它
6. 到 https://uptimerobot.com 建立免費 Monitor，類型 **HTTPS**、網址貼上 `https://xxxx.repl.co`、間隔 5 分鐘 → 建立
7. 之後 UptimeRobot 每 5 分鐘訪問一次，bot 就不會休眠（免費版 Replit 仍可能限制 CPU，適合一般遊玩）

## 📋 指令一覽
| 分類 | 指令 |
|---|---|
| 玩家入場 | `/entry` `/name_change` `/health` `/rank` |
| 戰鬥扣具 | `/henshin` `/set_buckle` `/dual_on` `/dual_off` `/buckle_inventory` `/give_buckle` `/gacha` `/fight` `/mission` `/battle` |
| 主辦方 | `/ready` `/start` `/jyamato` `/end_jyamato` `/boss` `/elim` `/game_stop` `/game_resume` `/export_last_rank` |
| 查詢 | `/help` `/rule` |

詳細規則請在 Discord 內使用 `/rule` 或 `/help` 查看。
