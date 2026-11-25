# 超高機能BOT 土台: Bot本体 / サーバー別設定ストア / 機能レジストリ / 権限
# 方針: 機能はモジュール単位で登録し、詳細設定は Discord 内（/設定エレベーター）で作る。
import json
import os

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
TOKEN = os.environ.get("MEGA_DISCORD_TOKEN", "")

TRUSTED_USER_IDS = {1546348374922625065, 1256574550901133377}


def _apply_mobile_status_patch():
    try:
        from discord.gateway import DiscordWebSocket
        if getattr(DiscordWebSocket, "_mega_mobile_patched", False):
            return
        orig = DiscordWebSocket.send_as_json

        async def patched(self, data):
            try:
                if isinstance(data, dict) and data.get("op") == 2 and isinstance(data.get("d"), dict):
                    props = data["d"].setdefault("properties", {})
                    props["os"] = "iOS"
                    props["browser"] = "Discord iOS"
                    props["device"] = "Discord iOS"
            except Exception:
                pass
            return await orig(self, data)

        DiscordWebSocket.send_as_json = patched
        DiscordWebSocket._mega_mobile_patched = True
    except Exception:
        pass


_apply_mobile_status_patch()


# ---------------------------------------------------------------- 設定ストア
class JsonStore:
    """サーバー（ギルド）ごとの設定を config.json に保存する"""

    def __init__(self, filename):
        self.path = os.path.join(BASE_DIR, filename)
        self.data = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def cfg(self, guild_id) -> dict:
        return self.data.setdefault(str(guild_id), {})


store = JsonStore("config.json")


def save_config():
    store.save()


# ---------------------------------------------------------------- パネル再描画フック
PANEL_REFRESHERS = []


def register_panel_refresher(fn):
    PANEL_REFRESHERS.append(fn)


async def refresh_panels(guild_id):
    """設定が保存されたら、設置済みパネル全部を最新表示に直す"""
    for fn in PANEL_REFRESHERS:
        try:
            await fn(guild_id)
        except Exception:
            pass


# ---------------------------------------------------------------- レジストリ
# カテゴリ（エレベーターの「階」）と機能（「部屋」）を登録する。
# 機能モジュールは register_feature で自分の設定項目（スキーマ）を宣言するだけで、
# 設定画面は hub.py がセレクトメニュー式に自動生成する。
CATEGORIES = []
FEATURES = {}


def register_category(key, name, emoji, desc):
    CATEGORIES.append({"key": key, "name": name, "emoji": emoji, "desc": desc})


def register_feature(key, category, name, emoji, desc, settings=None, help_text=""):
    FEATURES[key] = {
        "key": key, "category": category, "name": name, "emoji": emoji,
        "desc": desc, "settings": settings or [], "help": help_text,
    }


def category_of(key):
    for c in CATEGORIES:
        if c["key"] == key:
            return c
    return None


def features_in(category_key):
    return [f for f in FEATURES.values() if f["category"] == category_key]


def feature_cfg(guild_id, key) -> dict:
    """そのサーバーの機能設定（デフォルトを補完して返す）"""
    feat = FEATURES[key]
    allf = store.cfg(guild_id).setdefault("features", {})
    cfg = allf.setdefault(key, {})
    cfg.setdefault("enabled", False)
    for item in feat["settings"]:
        cfg.setdefault(item["key"], item.get("default"))
    return cfg


def feature_enabled(guild_id, key) -> bool:
    return bool(feature_cfg(guild_id, key).get("enabled"))


# ---------------------------------------------------------------- エレベーターの階
def floors_map(guild_id):
    """階 → サーバー内カテゴリIDの対応表 {階番号: [カテゴリID, ...]}。階は無限に増やせて、1階に複数カテゴリを置ける。"""
    cfg = feature_cfg(guild_id, "elevator")
    if not cfg.get("_floors_v2"):
        # 旧形式（floor_1..12）からの移行: 有効な割り当てだけ引き継ぐ
        valid = {c["key"] for c in CATEGORIES}
        m = {}
        for i in range(1, 13):
            v = cfg.pop(f"floor_{i}", None)
            if v in valid:
                m[str(i)] = v
        cfg["floors_map"] = m
        cfg["_floors_v2"] = True
        store.save()
    result = {}
    for k, v in (cfg.get("floors_map") or {}).items():
        if str(k).isdigit():
            result[int(k)] = _coerce_cat_ids(v)
    return result


def _coerce_cat_ids(v):
    if isinstance(v, int):
        return [v]
    if isinstance(v, str) and v.isdigit():
        return [int(v)]
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, int):
                out.append(x)
            elif isinstance(x, str) and x.isdigit():
                out.append(int(x))
        return out
    return []


def save_floors_map(guild_id, m):
    cfg = feature_cfg(guild_id, "elevator")
    cfg["floors_map"] = {str(k): v for k, v in m.items()}
    store.save()


def visible_floors(guild_id):
    """パネル等に表示する階: 割り当て済みの階 ＋ 常に1階（未設定でも1階だけは出す）"""
    m = floors_map(guild_id)
    return sorted({1} | {n for n, ids in m.items() if ids})


# カテゴリ（階）の定義 — 機能はこの下にぶら下がる
register_category("enter", "入退室・認証", "👋", "ウェルカム、認証ゲート、自己紹介など")
register_category("moderation", "モデレーション", "🛡️", "警告、スパム対策、監査ログなど")
register_category("level", "レベル・経済", "⭐", "XP、コイン、ランキング、ショップなど")
register_category("support", "サポート", "🎫", "チケット、FAQ、アンケートなど")
register_category("event", "運営・イベント", "📣", "募集、抽選、リマインダー、定期配信など")
register_category("auto", "自動化", "🔁", "リアクションロール、通知連携、誕生日など")
register_category("tool", "便利ツール", "🧰", "翻訳、チーム分け、計算機など")
register_category("entame", "エンタメ", "🎮", "ミニゲーム、クイズ、運勢など")
register_category("vc", "VC・読み上げ", "🔊", "読み上げ、VC通知など")
register_category("ai", "AI", "🤖", "AIチャット、要約など")
register_category("stats", "分析", "📊", "サーバー統計、アクティブ分析など")
register_category("system", "システム", "🏢", "基本設定、権限、バックアップなど")


# ---------------------------------------------------------------- 権限
def is_privileged(member) -> bool:
    """設定を触れる人: 信頼ユーザー or サーバー管理者"""
    if member is None:
        return False
    if member.id in TRUSTED_USER_IDS:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.administrator)


# ---------------------------------------------------------------- Bot 本体
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class MegaBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()


bot = MegaBot(command_prefix="!", intents=intents)


@tasks.loop(seconds=15)
async def _rotate_status():
    entries = [
        f"{len(bot.guilds)} 件のサーバーで稼働中",
        f"{len(bot.tree.get_commands())} 件のコマンド",
    ]
    idx = getattr(_rotate_status, "_idx", 0)
    _rotate_status._idx = idx + 1
    try:
        await bot.change_presence(
            activity=discord.Game(name=entries[idx % len(entries)]))
    except Exception:
        pass


@bot.listen("on_ready")
async def _start_status():
    if not _rotate_status.is_running():
        _rotate_status.start()
