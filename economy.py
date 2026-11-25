# 機能群: レベル・経済（XP/レベル報酬/コイン/デイリー/送金/ランキング/ショップ/仕事/スロット）
import random
import time
from datetime import timedelta

import discord

from core import (bot, feature_cfg, feature_enabled, guild_data,
                  is_privileged, jst_now, register_feature, save_data,
                  user_data,
                  command_group)

CAT = "level"

_G = command_group("economy", "経済", "レベル・経済機能")


def _enabled(interaction, feature):
    return (interaction.guild is not None
            and feature_enabled(interaction.guild.id, feature))


# ---------------------------------------------------------------- レベル
register_feature(
    "level", CAT, "レベル・XP", "⭐",
    "発言でXPが貯まり、レベルが上がる。",
    settings=[
        {"key": "xp_min", "label": "1回の最小XP", "type": "number", "default": 15},
        {"key": "xp_max", "label": "1回の最大XP", "type": "number", "default": 25},
        {"key": "cooldown", "label": "XPが貯まる間隔（秒）", "type": "number",
         "default": 60},
        {"key": "announce_channel_id", "label": "レベルアップ通知チャンネル（空=その場）",
         "type": "channel", "default": None},
    ],
    help_text="/ランク で自分のレベルと順位が見られます。")


def xp_need(level):
    return 100 * max(1, level)


def _add_xp(gid, uid, amount):
    u = user_data(gid, uid)
    u["xp"] = int(u.get("xp") or 0) + amount
    u.setdefault("level", 1)
    ups = []
    while u["xp"] >= xp_need(u["level"]):
        u["xp"] -= xp_need(u["level"])
        u["level"] += 1
        ups.append(u["level"])
    return ups


@bot.listen("on_message")
async def _xp_listener(message):
    if message.guild is None or message.author.bot:
        return
    gid = message.guild.id
    if not feature_enabled(gid, "level"):
        return
    cfg = feature_cfg(gid, "level")
    u = user_data(gid, message.author.id)
    now = time.monotonic()
    if now - float(u.get("last_xp") or 0) < float(cfg.get("cooldown") or 60):
        return
    u["last_xp"] = now
    amount = random.randint(int(cfg.get("xp_min") or 15),
                            int(cfg.get("xp_max") or 25))
    ups = _add_xp(gid, message.author.id, amount)
    save_data()
    for level in ups:
        await _on_level_up(message, level)


async def _on_level_up(message, level):
    gid = message.guild.id
    cfg = feature_cfg(gid, "level")
    channel = message.channel
    cid = cfg.get("announce_channel_id")
    if cid:
        found = message.guild.get_channel(int(cid))
        if found is not None:
            channel = found
    try:
        await channel.send(
            f"🎉 {message.author.mention} がレベル {level} に上がりました！")
    except Exception:
        pass
    if feature_enabled(gid, "levelreward"):
        rewards = feature_cfg(gid, "levelreward").get("rewards") or {}
        role_id = rewards.get(str(level))
        if role_id:
            role = message.guild.get_role(int(role_id))
            if role is not None:
                try:
                    await message.author.add_roles(role)
                except Exception:
                    pass


def _rank_of(gid, uid):
    users = guild_data(gid).get("users", {})
    ordered = sorted(
        users.items(),
        key=lambda kv: (int(kv[1].get("level") or 1), int(kv[1].get("xp") or 0)),
        reverse=True)
    for i, (key, _) in enumerate(ordered, 1):
        if key == str(uid):
            return i
    return None


@_G.command(name="ランク", description="自分のレベルと順位を見る")
@discord.app_commands.describe(メンバー="見たいメンバー（省略で自分）")
async def cmd_rank(interaction, メンバー: discord.Member = None):
    if not _enabled(interaction, "level"):
        return await interaction.response.send_message(
            "⚠️ レベル機能は無効です。", ephemeral=True)
    target = メンバー or interaction.user
    u = user_data(interaction.guild.id, target.id)
    level = int(u.get("level") or 1)
    xp = int(u.get("xp") or 0)
    need = xp_need(level)
    filled = min(10, xp * 10 // max(1, need))
    bar = "█" * filled + "░" * (10 - filled)
    embed = discord.Embed(title=f"⭐ {target.display_name} のランク",
                          color=discord.Color.gold())
    embed.add_field(name="レベル", value=str(level), inline=True)
    embed.add_field(name="順位", value=f"{_rank_of(interaction.guild.id, target.id) or '-'} 位",
                    inline=True)
    embed.add_field(name="XP", value=f"{xp} / {need}\n{bar}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- レベル報酬
register_feature("levelreward", CAT, "レベル報酬ロール", "🎖️",
                 "レベル到達でロールを自動付与する。",
                 help_text="/レベル報酬設定 で「レベル→ロール」を登録します。")


class _RewardLevelModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="🎖️ 報酬レベルを入力")
        self.view = view
        self.level_input = discord.ui.TextInput(label="レベル（数字）",
                                                max_length=5)
        self.add_item(self.level_input)

    async def on_submit(self, interaction):
        try:
            level = int(str(self.level_input.value).strip())
            if level < 1:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "⚠️ 数字で入れてね。", ephemeral=True)
        self.view.pending_level = level
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class RewardSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self.pending_level = None
        self._build()

    def rewards(self):
        return feature_cfg(self.gid, "levelreward").setdefault("rewards", {})

    def embed(self):
        rewards = self.rewards()
        lines = [f"レベル {lv} → <@&{rid}>" for lv, rid in
                 sorted(rewards.items(), key=lambda kv: int(kv[0]))]
        embed = discord.Embed(
            title="🎖️ レベル報酬設定", color=discord.Color.gold(),
            description="\n".join(lines) if lines else "まだ登録がありません。")
        if self.pending_level:
            embed.add_field(name="登録中のレベル",
                            value=f"レベル {self.pending_level} のロールを選んでね",
                            inline=False)
        return embed

    def _build(self):
        self.clear_items()
        actions = [discord.SelectOption(label="➕ 報酬を追加（レベル入力）",
                                        value="add")]
        if self.rewards():
            actions.append(discord.SelectOption(label="🗑 報酬を削除", value="del"))
        sel = discord.ui.Select(placeholder="⚙️ 操作を選ぶ", options=actions, row=0)

        async def _act(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ 他の人の画面です。", ephemeral=True)
            v = _sel.values[0]
            if v == "add":
                return await interaction.response.send_modal(
                    _RewardLevelModal(self))
            if v == "del":
                self.pending_level = "del"
                self._build()
                return await interaction.response.edit_message(
                    embed=self.embed(), view=self)

        sel.callback = _act
        self.add_item(sel)
        if self.pending_level == "del":
            opts = [discord.SelectOption(
                label=f"レベル {lv}", value=lv) for lv in
                sorted(self.rewards().keys(), key=int)][:25]
            dsel = discord.ui.Select(placeholder="🗑 消すレベル", options=opts, row=1)

            async def _del(interaction, _sel=dsel):
                if interaction.user.id != self.owner_id:
                    return
                self.rewards().pop(_sel.values[0], None)
                from core import save_config
                save_config()
                self.pending_level = None
                self._build()
                await interaction.response.edit_message(
                    embed=self.embed(), view=self)

            dsel.callback = _del
            self.add_item(dsel)
        elif self.pending_level:
            rsel = discord.ui.RoleSelect(placeholder="🎖️ 付与するロール", row=1)

            async def _role(interaction, _sel=rsel):
                if interaction.user.id != self.owner_id:
                    return
                v = _sel.values[0]
                self.rewards()[str(self.pending_level)] = int(
                    getattr(v, "id", v))
                from core import save_config
                save_config()
                self.pending_level = None
                self._build()
                await interaction.response.edit_message(
                    embed=self.embed(), view=self)

            rsel.callback = _role
            self.add_item(rsel)


@_G.command(name="レベル報酬設定", description="レベル報酬ロールを設定する（管理者用）")
async def cmd_reward_settings(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "levelreward"):
        return await interaction.response.send_message(
            "⚠️ レベル報酬は無効です。/設定 で有効にしてね。", ephemeral=True)
    view = RewardSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- コイン
register_feature(
    "coins", CAT, "コイン", "🪙", "サーバー内通貨コイン。",
    settings=[
        {"key": "currency", "label": "通貨の名前", "type": "text", "default": "コイン"},
        {"key": "start", "label": "最初の所持金", "type": "number", "default": 1000},
    ],
    help_text="/残高 で所持金が見られます。")


def _coins(gid, uid):
    u = user_data(gid, uid)
    if "coins" not in u:
        u["coins"] = int(feature_cfg(gid, "coins").get("start") or 0)
    return int(u["coins"])


def _add_coins(gid, uid, amount):
    u = user_data(gid, uid)
    _coins(gid, uid)
    u["coins"] = max(0, int(u["coins"]) + int(amount))
    return int(u["coins"])


@_G.command(name="残高", description="コインの残高を見る")
@discord.app_commands.describe(メンバー="見たいメンバー（省略で自分）")
async def cmd_balance(interaction, メンバー: discord.Member = None):
    if not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ コイン機能は無効です。", ephemeral=True)
    target = メンバー or interaction.user
    currency = feature_cfg(interaction.guild.id, "coins").get("currency") or "コイン"
    await interaction.response.send_message(
        f"🪙 {target.mention} の残高: **{_coins(interaction.guild.id, target.id):,}** {currency}",
        ephemeral=True)


# ---------------------------------------------------------------- デイリー/送金
register_feature(
    "daily", CAT, "デイリーボーナス", "🎁", "1日1回コインがもらえる。",
    settings=[
        {"key": "amount", "label": "基本額", "type": "number", "default": 500},
        {"key": "streak_bonus", "label": "連続1日ごとの追加額", "type": "number",
         "default": 50},
    ])


@_G.command(name="デイリー", description="デイリーボーナスを受け取る")
async def cmd_daily(interaction):
    if not _enabled(interaction, "daily") or not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ デイリー（またはコイン）が無効です。", ephemeral=True)
    gid = interaction.guild.id
    cfg = feature_cfg(gid, "daily")
    u = user_data(gid, interaction.user.id)
    today = jst_now().date()
    last = u.get("last_daily")
    if last == today.isoformat():
        return await interaction.response.send_message(
            "🎁 今日はもう受け取り済みです。", ephemeral=True)
    yesterday = (today - timedelta(days=1)).isoformat()
    streak = int(u.get("streak") or 0) + 1 if last == yesterday else 1
    u["streak"] = streak
    u["last_daily"] = today.isoformat()
    amount = int(cfg.get("amount") or 500) + int(cfg.get("streak_bonus") or 0) * (streak - 1)
    balance = _add_coins(gid, interaction.user.id, amount)
    save_data()
    currency = feature_cfg(gid, "coins").get("currency") or "コイン"
    await interaction.response.send_message(
        f"🎁 デイリーボーナス **{amount:,}** {currency}（{streak} 日連続）\n"
        f"残高: **{balance:,}** {currency}")


register_feature("pay", CAT, "コイン送金", "💸", "メンバー同士でコインを送る。",
                 settings=[{"key": "min_amount", "label": "最小送金額",
                            "type": "number", "default": 1}])


@_G.command(name="送金", description="コインを送る")
@discord.app_commands.describe(メンバー="送り先", 金額="送る金額")
async def cmd_pay(interaction, メンバー: discord.Member, 金額: int):
    if not _enabled(interaction, "pay") or not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ 送金（またはコイン）が無効です。", ephemeral=True)
    gid = interaction.guild.id
    cfg = feature_cfg(gid, "pay")
    amount = int(金額)
    if amount < int(cfg.get("min_amount") or 1) or メンバー.id == interaction.user.id:
        return await interaction.response.send_message(
            "⚠️ 金額か送り先が変です。", ephemeral=True)
    if _coins(gid, interaction.user.id) < amount:
        return await interaction.response.send_message(
            "⚠️ 残高が足りません。", ephemeral=True)
    _add_coins(gid, interaction.user.id, -amount)
    _add_coins(gid, メンバー.id, amount)
    save_data()
    currency = feature_cfg(gid, "coins").get("currency") or "コイン"
    await interaction.response.send_message(
        f"💸 {メンバー.mention} に **{amount:,}** {currency} を送りました。")


# ---------------------------------------------------------------- ランキング
register_feature("ranking", CAT, "ランキング", "🏆",
                 "レベルとコインのランキングを表示する。")


class RankingView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=300)
        self.gid = gid
        self.owner_id = owner_id
        sel = discord.ui.Select(
            placeholder="🏆 見たいランキング",
            options=[discord.SelectOption(label="⭐ レベル", value="level"),
                     discord.SelectOption(label="🪙 コイン", value="coins")])
        sel.callback = self._cb
        self.add_item(sel)

    def _embed(self, kind):
        users = guild_data(self.gid).get("users", {})
        if kind == "level":
            ordered = sorted(users.items(), key=lambda kv: (
                int(kv[1].get("level") or 1), int(kv[1].get("xp") or 0)),
                reverse=True)
            lines = [f"{i}. <@{uid}> — レベル {u.get('level', 1)}"
                     for i, (uid, u) in enumerate(ordered[:10], 1)]
            title = "🏆 レベルランキング"
        else:
            ordered = sorted(users.items(),
                             key=lambda kv: int(kv[1].get("coins") or 0),
                             reverse=True)
            lines = [f"{i}. <@{uid}> — {int(u.get('coins') or 0):,}"
                     for i, (uid, u) in enumerate(ordered[:10], 1)]
            title = "🏆 コインランキング"
        return discord.Embed(title=title, color=discord.Color.gold(),
                             description="\n".join(lines) or "データがありません")

    async def _cb(self, interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "⚠️ 他の人の画面です。", ephemeral=True)
        from core import sel_values
        kind = sel_values(interaction, self.children[0])[0]
        await interaction.response.edit_message(embed=self._embed(kind), view=self)


@_G.command(name="ランキング", description="レベル/コインのランキングを見る")
async def cmd_ranking(interaction):
    if not _enabled(interaction, "ranking"):
        return await interaction.response.send_message(
            "⚠️ ランキングは無効です。", ephemeral=True)
    view = RankingView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view._embed("level"), view=view, ephemeral=True)


# ---------------------------------------------------------------- お仕事
register_feature(
    "work", CAT, "お仕事", "💼", "働いてコインを稼ぐ。",
    settings=[
        {"key": "min_pay", "label": "最低賃金", "type": "number", "default": 100},
        {"key": "max_pay", "label": "最高賃金", "type": "number", "default": 300},
        {"key": "cooldown_hours", "label": "間隔（時間）", "type": "number",
         "default": 1},
    ])

_JOBS = ["コンビニの店員", "配達", "プログラミング", "掃除", "農作業のお手伝い",
         "動画編集", "警備", "料理人の助手"]


@_G.command(name="お仕事", description="働いてコインを稼ぐ")
async def cmd_work(interaction):
    if not _enabled(interaction, "work") or not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ お仕事（またはコイン）が無効です。", ephemeral=True)
    gid = interaction.guild.id
    cfg = feature_cfg(gid, "work")
    u = user_data(gid, interaction.user.id)
    now = time.time()
    wait = float(cfg.get("cooldown_hours") or 1) * 3600
    if now - float(u.get("last_work") or 0) < wait:
        left = int(wait - (now - float(u.get("last_work") or 0)))
        return await interaction.response.send_message(
            f"💼 疲れている… あと {left // 60} 分休んでね。", ephemeral=True)
    u["last_work"] = now
    pay = random.randint(int(cfg.get("min_pay") or 100),
                         int(cfg.get("max_pay") or 300))
    balance = _add_coins(gid, interaction.user.id, pay)
    save_data()
    currency = feature_cfg(gid, "coins").get("currency") or "コイン"
    await interaction.response.send_message(
        f"💼 {random.choice(_JOBS)}をして **{pay:,}** {currency} 稼ぎました！"
        f"（残高 {balance:,}）")


# ---------------------------------------------------------------- ショップ
register_feature("shop", CAT, "コインショップ", "🛒",
                 "コインでロールを買えるショップ。",
                 help_text="/ショップ設定 で商品（ロールと価格）を登録、/ショップ で購入。")


class _ShopPriceModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="🛒 価格を入力")
        self.view = view
        self.price = discord.ui.TextInput(label="価格（数字）", max_length=10)
        self.add_item(self.price)

    async def on_submit(self, interaction):
        try:
            price = int(str(self.price.value).strip())
            if price < 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "⚠️ 数字で入れてね。", ephemeral=True)
        self.view.pending_price = price
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class ShopSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self.pending_price = None
        self.deleting = False
        self._build()

    def items(self):
        return feature_cfg(self.gid, "shop").setdefault("items", {})

    def embed(self):
        items = self.items()
        lines = [f"<@&{rid}> — {price:,}" for rid, price in items.items()]
        embed = discord.Embed(
            title="🛒 ショップ設定", color=discord.Color.green(),
            description="\n".join(lines) if lines else "商品がありません。")
        if self.pending_price is not None:
            embed.add_field(name="登録中", value=f"価格 {self.pending_price:,} の"
                            "ロールを選んでね", inline=False)
        return embed

    def _save(self):
        from core import save_config
        save_config()

    def _build(self):
        self.clear_items()
        actions = [discord.SelectOption(label="➕ 商品を追加（価格入力）", value="add")]
        if self.items():
            actions.append(discord.SelectOption(label="🗑 商品を削除", value="del"))
        sel = discord.ui.Select(placeholder="⚙️ 操作を選ぶ", options=actions, row=0)

        async def _act(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "add":
                return await interaction.response.send_modal(
                    _ShopPriceModal(self))
            self.deleting = True
            self._build()
            await interaction.response.edit_message(embed=self.embed(), view=self)

        sel.callback = _act
        self.add_item(sel)
        if self.deleting:
            opts = [discord.SelectOption(label=f"ロール {rid}", value=rid)
                    for rid in list(self.items().keys())[:25]]
            dsel = discord.ui.Select(placeholder="🗑 消す商品のロールID",
                                     options=opts, row=1)

            async def _del(interaction, _sel=dsel):
                if interaction.user.id != self.owner_id:
                    return
                self.items().pop(_sel.values[0], None)
                self._save()
                self.deleting = False
                self._build()
                await interaction.response.edit_message(
                    embed=self.embed(), view=self)

            dsel.callback = _del
            self.add_item(dsel)
        elif self.pending_price is not None:
            rsel = discord.ui.RoleSelect(placeholder="🛒 商品にするロール", row=1)

            async def _role(interaction, _sel=rsel):
                if interaction.user.id != self.owner_id:
                    return
                v = _sel.values[0]
                self.items()[str(int(getattr(v, "id", v)))] = self.pending_price
                self._save()
                self.pending_price = None
                self._build()
                await interaction.response.edit_message(
                    embed=self.embed(), view=self)

            rsel.callback = _role
            self.add_item(rsel)


@_G.command(name="ショップ設定", description="コインショップの商品を設定する（管理者用）")
async def cmd_shop_settings(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "shop"):
        return await interaction.response.send_message(
            "⚠️ ショップは無効です。", ephemeral=True)
    view = ShopSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


class ShopView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=300)
        self.gid = gid
        self.owner_id = owner_id
        items = feature_cfg(gid, "shop").get("items") or {}
        options = []
        guild = bot.get_guild(gid)
        for rid, price in list(items.items())[:25]:
            role = guild.get_role(int(rid)) if guild else None
            options.append(discord.SelectOption(
                label=f"{role.name if role else rid} — {price:,}",
                value=str(rid)))
        if not options:
            options = [discord.SelectOption(label="（商品なし）", value="__none")]
        sel = discord.ui.Select(placeholder="🛒 買いたい商品", options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "⚠️ 他の人の画面です。", ephemeral=True)
        from core import sel_values
        rid = sel_values(interaction, self.children[0])[0]
        if rid == "__none":
            return
        items = feature_cfg(self.gid, "shop").get("items") or {}
        price = int(items.get(rid) or 0)
        if _coins(self.gid, interaction.user.id) < price:
            return await interaction.response.send_message(
                "⚠️ コインが足りません。", ephemeral=True)
        role = interaction.guild.get_role(int(rid))
        if role is None:
            return await interaction.response.send_message(
                "⚠️ ロールが見つかりません。", ephemeral=True)
        _add_coins(self.gid, interaction.user.id, -price)
        save_data()
        try:
            await interaction.user.add_roles(role)
        except Exception:
            _add_coins(self.gid, interaction.user.id, price)
            save_data()
            return await interaction.response.send_message(
                "⚠️ ロールを付けられなかったので返金しました。", ephemeral=True)
        await interaction.response.send_message(
            f"🛒 {role.mention} を購入しました！", ephemeral=True)


@_G.command(name="ショップ", description="コインショップで買い物する")
async def cmd_shop(interaction):
    if not _enabled(interaction, "shop") or not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ ショップ（またはコイン）が無効です。", ephemeral=True)
    view = ShopView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=discord.Embed(title="🛒 ショップ", color=discord.Color.green(),
                            description="買いたい商品を選んでね。"),
        view=view, ephemeral=True)


# ---------------------------------------------------------------- コインスロット
register_feature(
    "coinslot", CAT, "コインスロット", "🎰", "コインを賭けるスロット。",
    settings=[{"key": "min_bet", "label": "最小ベット", "type": "number",
               "default": 10},
              {"key": "max_bet", "label": "最大ベット", "type": "number",
               "default": 1000}])

_SLOT_FACES = ["🍒", "🍋", "🔔", "⭐", "💎"]
_SLOT_PAY = {3: 10, 2: 2}


@_G.command(name="コインスロット", description="コインを賭けてスロットを回す")
@discord.app_commands.describe(金額="賭ける金額")
async def cmd_coinslot(interaction, 金額: int):
    if not _enabled(interaction, "coinslot") or not _enabled(interaction, "coins"):
        return await interaction.response.send_message(
            "⚠️ スロット（またはコイン）が無効です。", ephemeral=True)
    gid = interaction.guild.id
    cfg = feature_cfg(gid, "coinslot")
    bet = int(金額)
    if bet < int(cfg.get("min_bet") or 10) or bet > int(cfg.get("max_bet") or 1000):
        return await interaction.response.send_message(
            f"⚠️ ベットは {cfg.get('min_bet')}〜{cfg.get('max_bet')} の間で。",
            ephemeral=True)
    if _coins(gid, interaction.user.id) < bet:
        return await interaction.response.send_message(
            "⚠️ コインが足りません。", ephemeral=True)
    faces = [random.choice(_SLOT_FACES) for _ in range(3)]
    best = max(faces.count(f) for f in set(faces))
    mult = _SLOT_PAY.get(best, 0)
    _add_coins(gid, interaction.user.id, -bet + bet * mult)
    save_data()
    currency = feature_cfg(gid, "coins").get("currency") or "コイン"
    result = (f"🎉 {mult} 倍！ **{bet * mult:,}** {currency} 獲得"
              if mult else "💦 ハズレ…")
    await interaction.response.send_message(
        f"🎰 {' | '.join(faces)}\n{result}")


# ---------------------------------------------------------------- 管理者調整
register_feature("xpadmin", CAT, "経験値管理", "🛠️",
                 "管理者がXPやレベルを調整する。")
register_feature("coinadmin", CAT, "コイン管理", "🏦",
                 "管理者がコインを増減する。")


@_G.command(name="経験値管理", description="XPを増減する（管理者用）")
@discord.app_commands.describe(メンバー="対象", 量="増減量（マイナス可）")
async def cmd_xpadmin(interaction, メンバー: discord.Member, 量: int):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "xpadmin"):
        return await interaction.response.send_message(
            "⚠️ 経験値管理は無効です。", ephemeral=True)
    gid = interaction.guild.id
    u = user_data(gid, メンバー.id)
    if int(量) >= 0:
        _add_xp(gid, メンバー.id, int(量))
    else:
        u["xp"] = max(0, int(u.get("xp") or 0) + int(量))
    save_data()
    await interaction.response.send_message(
        f"🛠️ {メンバー.mention} のXPを {int(量):+} しました"
        f"（レベル {u.get('level', 1)}）", ephemeral=True)


@_G.command(name="コイン管理", description="コインを増減する（管理者用）")
@discord.app_commands.describe(メンバー="対象", 量="増減量（マイナス可）")
async def cmd_coinadmin(interaction, メンバー: discord.Member, 量: int):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "coinadmin"):
        return await interaction.response.send_message(
            "⚠️ コイン管理は無効です。", ephemeral=True)
    balance = _add_coins(interaction.guild.id, メンバー.id, int(量))
    save_data()
    await interaction.response.send_message(
        f"🏦 {メンバー.mention} のコインを {int(量):+} しました"
        f"（残高 {balance:,}）", ephemeral=True)
