# 機能群: 便利ツール（リマインダー/タイマー/情報表示/計算/メモ/ToDo/天気/QRなど）
import ast
import asyncio
import json
import operator
import random
import secrets
import string
import urllib.parse
import urllib.request
from datetime import timedelta

import discord
from discord.ext import tasks

from core import (bot, feature_enabled, guild_data, jst_now, register_feature,
                  save_data, sel_values, user_data,
                  command_group)

CAT = "tool"

_G = command_group("tool", "ツール", "便利ツール")


def _on(interaction, feature):
    return (interaction.guild is not None
            and feature_enabled(interaction.guild.id, feature))


async def _off(interaction, name):
    await interaction.response.send_message(
        f"⚠️ {name}は無効です。", ephemeral=True)


# ---------------------------------------------------------------- リマインダー / タイマー
register_feature("reminder", CAT, "リマインダー", "⏰",
                 "指定時間後に知らせる。")


@_G.command(name="リマインダー", description="指定分後にお知らせする")
@discord.app_commands.describe(分="何分後", 内容="知らせる内容")
async def cmd_reminder(interaction, 分: int, 内容: str):
    if not _on(interaction, "reminder"):
        return await _off(interaction, "リマインダー")
    minutes = max(1, min(60 * 24 * 30, int(分)))
    at = jst_now() + timedelta(minutes=minutes)
    items = guild_data(interaction.guild.id).setdefault("reminders", [])
    items.append({"uid": interaction.user.id,
                  "channel_id": interaction.channel.id,
                  "at": at.isoformat(), "text": 内容[:200]})
    save_data()
    await interaction.response.send_message(
        f"⏰ {minutes} 分後に「{内容}」をお知らせします。", ephemeral=True)


@tasks.loop(seconds=20)
async def _reminder_loop():
    from core import data_store
    from datetime import datetime
    now = jst_now()
    for gid_str in list(data_store.data.keys()):
        gid = int(gid_str)
        data = guild_data(gid)
        items = data.get("reminders", [])
        keep = []
        changed = False
        for item in items:
            try:
                at = datetime.fromisoformat(item["at"])
            except Exception:
                changed = True
                continue
            if at <= now:
                channel = bot.get_channel(int(item["channel_id"]))
                if channel is not None:
                    try:
                        await channel.send(
                            f"⏰ <@{item['uid']}> リマインダー: {item['text']}")
                    except Exception:
                        pass
                changed = True
            else:
                keep.append(item)
        if changed:
            data["reminders"] = keep
            save_data()


@bot.listen("on_ready")
async def _start_reminder_loop():
    if not _reminder_loop.is_running():
        _reminder_loop.start()


register_feature("timer", CAT, "タイマー", "⏱️", "その場で使えるタイマー。")


@_G.command(name="タイマー", description="タイマーをセットする")
@discord.app_commands.describe(分="分数", 内容="終わったら知らせる内容")
async def cmd_timer(interaction, 分: int, 内容: str = "時間です！"):
    if not _on(interaction, "timer"):
        return await _off(interaction, "タイマー")
    minutes = max(1, min(24 * 60, int(分)))
    await interaction.response.send_message(
        f"⏱️ {minutes} 分タイマーを開始しました。", ephemeral=True)
    channel = interaction.channel
    user = interaction.user

    async def _notify():
        await asyncio.sleep(minutes * 60)
        try:
            await channel.send(f"⏱️ {user.mention} {内容}")
        except Exception:
            pass

    asyncio.create_task(_notify())


# ---------------------------------------------------------------- 情報表示
register_feature("userinfo", CAT, "ユーザー情報", "👤",
                 "メンバーの情報を表示する。")


@_G.command(name="ユーザー情報", description="メンバーの情報を見る")
@discord.app_commands.describe(メンバー="見たいメンバー（省略で自分）")
async def cmd_userinfo(interaction, メンバー: discord.Member = None):
    if not _on(interaction, "userinfo"):
        return await _off(interaction, "ユーザー情報")
    target = メンバー or interaction.user
    embed = discord.Embed(title=f"👤 {target.display_name}",
                          color=discord.Color.blurple())
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="ユーザー名", value=f"{target.mention} `{target.name}`",
                    inline=False)
    embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="アカウント作成",
                    value=target.created_at.strftime("%Y-%m-%d"), inline=True)
    if target.joined_at:
        embed.add_field(name="サーバー参加",
                        value=target.joined_at.strftime("%Y-%m-%d"), inline=True)
    roles = [r.mention for r in target.roles if r.name != "@everyone"][:15]
    embed.add_field(name="ロール", value=" ".join(roles) or "なし", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("serverinfo", CAT, "サーバー情報", "🏠",
                 "サーバーの情報を表示する。")


@_G.command(name="サーバー情報", description="サーバーの情報を見る")
async def cmd_serverinfo(interaction):
    if not _on(interaction, "serverinfo"):
        return await _off(interaction, "サーバー情報")
    guild = interaction.guild
    embed = discord.Embed(title=f"🏠 {guild.name}",
                          color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="メンバー数", value=f"{guild.member_count} 人",
                    inline=True)
    embed.add_field(name="チャンネル数", value=f"{len(guild.channels)} 件",
                    inline=True)
    embed.add_field(name="ロール数", value=f"{len(guild.roles)} 件", inline=True)
    embed.add_field(name="作成日",
                    value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="オーナー",
                    value=f"<@{guild.owner_id}>" if guild.owner_id else "-",
                    inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("avatar", CAT, "アバター表示", "🖼️",
                 "メンバーのアバターを大きく表示する。")


@_G.command(name="アバター", description="アバターを大きく見る")
@discord.app_commands.describe(メンバー="見たいメンバー（省略で自分）")
async def cmd_avatar(interaction, メンバー: discord.Member = None):
    if not _on(interaction, "avatar"):
        return await _off(interaction, "アバター表示")
    target = メンバー or interaction.user
    embed = discord.Embed(title=f"🖼️ {target.display_name} のアバター",
                          color=discord.Color.blurple())
    if target.display_avatar:
        embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("channelinfo", CAT, "チャンネル情報", "📺",
                 "チャンネルの情報を表示する。")


@_G.command(name="チャンネル情報", description="このチャンネルの情報を見る")
async def cmd_channelinfo(interaction):
    if not _on(interaction, "channelinfo"):
        return await _off(interaction, "チャンネル情報")
    ch = interaction.channel
    embed = discord.Embed(title=f"📺 #{getattr(ch, 'name', '?')}",
                          color=discord.Color.blurple())
    embed.add_field(name="ID", value=f"`{ch.id}`", inline=True)
    embed.add_field(name="作成日",
                    value=ch.created_at.strftime("%Y-%m-%d"), inline=True)
    if getattr(ch, "topic", None):
        embed.add_field(name="トピック", value=ch.topic, inline=False)
    if getattr(ch, "category", None):
        embed.add_field(name="カテゴリ", value=ch.category.name, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("roleinfo", CAT, "ロール情報", "🎭",
                 "ロールの情報を表示する。")


@_G.command(name="ロール情報", description="ロールの情報を見る")
@discord.app_commands.describe(ロール="見たいロール")
async def cmd_roleinfo(interaction, ロール: discord.Role):
    if not _on(interaction, "roleinfo"):
        return await _off(interaction, "ロール情報")
    embed = discord.Embed(title=f"🎭 {ロール.name}", color=ロール.color)
    embed.add_field(name="ID", value=f"`{ロール.id}`", inline=True)
    embed.add_field(name="メンバー数", value=f"{len(ロール.members)} 人",
                    inline=True)
    embed.add_field(name="作成日",
                    value=ロール.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="色", value=str(ロール.color), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- 計算 / 選択 / 占い系
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg}


def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.left), _calc(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    raise ValueError("bad")


register_feature("calc", CAT, "計算機", "🧮", "安全な計算機。")


@_G.command(name="計算", description="計算する")
@discord.app_commands.describe(式="例: 12*3+4")
async def cmd_calc(interaction, 式: str):
    if not _on(interaction, "calc"):
        return await _off(interaction, "計算機")
    try:
        result = _calc(ast.parse(式[:100], mode="eval"))
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        await interaction.response.send_message(f"🧮 `{式}` = **{result}**")
    except Exception:
        await interaction.response.send_message(
            "⚠️ 計算できませんでした。数字と + - * / % ** だけ使えます。",
            ephemeral=True)


register_feature("choice", CAT, "ランダム選択", "🎲",
                 "候補からランダムに1つ選ぶ。")


@_G.command(name="ランダム選択", description="候補から1つ選ぶ")
@discord.app_commands.describe(候補="空白区切りで候補")
async def cmd_choice(interaction, 候補: str):
    if not _on(interaction, "choice"):
        return await _off(interaction, "ランダム選択")
    items = [x for x in 候補.replace("、", " ").split(" ") if x.strip()]
    if len(items) < 2:
        return await interaction.response.send_message(
            "⚠️ 候補は2つ以上入れてね。", ephemeral=True)
    await interaction.response.send_message(
        f"🎲 選ばれたのは… **{random.choice(items)}**！")


register_feature("nitaku", CAT, "二択", "⚖️", "二択をランダムに決める。")


@_G.command(name="二択", description="二択で迷ったら決める")
@discord.app_commands.describe(候補a="1つ目", 候補b="2つ目")
async def cmd_nitaku(interaction, 候補a: str, 候補b: str):
    if not _on(interaction, "nitaku"):
        return await _off(interaction, "二択")
    pick = random.choice([候補a, 候補b])
    await interaction.response.send_message(f"⚖️ ズバリ… **{pick}**！")


register_feature("percent", CAT, "パーセント占い", "🔮",
                 "物事の確率を占う（1日固定）。")


@_G.command(name="パーセント", description="確率を占う")
@discord.app_commands.describe(内容="占いたいこと")
async def cmd_percent(interaction, 内容: str):
    if not _on(interaction, "percent"):
        return await _off(interaction, "パーセント占い")
    seed = f"{interaction.user.id}:{内容}:{jst_now().date().isoformat()}"
    value = random.Random(seed).randint(0, 100)
    await interaction.response.send_message(
        f"🔮 「{内容}」の確率は **{value}%** です。")


# ---------------------------------------------------------------- メモ / ToDo
register_feature("memo", CAT, "個人メモ", "📒", "自分だけのメモを保存する。")


class _MemoModal(discord.ui.Modal):
    def __init__(self, gid, uid):
        super().__init__(title="📒 メモを書く")
        u = user_data(gid, uid)
        self.text = discord.ui.TextInput(
            label="メモ", style=discord.TextStyle.paragraph, max_length=2000,
            required=False, default=u.get("memo") or None)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        user_data(interaction.guild.id,
                  interaction.user.id)["memo"] = str(self.text.value)
        save_data()
        await interaction.response.send_message("📒 メモを保存しました。",
                                                ephemeral=True)


@_G.command(name="メモ", description="個人メモを開く")
async def cmd_memo(interaction):
    if not _on(interaction, "memo"):
        return await _off(interaction, "個人メモ")
    await interaction.response.send_modal(
        _MemoModal(interaction.guild.id, interaction.user.id))


register_feature("todo", CAT, "ToDoリスト", "✅", "自分のToDoを管理する。")


class TodoView(discord.ui.View):
    def __init__(self, gid, uid):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self._build()

    def items(self):
        return user_data(self.gid, self.uid).setdefault("todos", [])

    def embed(self):
        lines = [f"{i+1}. {t}" for i, t in enumerate(self.items())]
        return discord.Embed(
            title="✅ ToDoリスト", color=discord.Color.green(),
            description="\n".join(lines) if lines else "空です。")

    def _build(self):
        self.clear_items()
        options = [discord.SelectOption(label="➕ 追加する", value="__add")]
        options += [discord.SelectOption(
            label=f"✅ 完了: {t}"[:100], value=str(i))
            for i, t in enumerate(self.items()[:24])]
        sel = discord.ui.Select(placeholder="✅ 追加 / 完了にする",
                                options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.user.id != self.uid:
            return
        v = sel_values(interaction, self.children[0])[0]
        if v == "__add":
            modal = discord.ui.Modal(title="✅ ToDoを追加")
            ti = discord.ui.TextInput(label="やること", max_length=200)
            modal.add_item(ti)

            async def _submit(it, _ti=ti):
                self.items().append(str(_ti.value))
                save_data()
                self._build()
                await it.response.edit_message(embed=self.embed(), view=self)

            modal.on_submit = _submit
            return await interaction.response.send_modal(modal)
        done = self.items().pop(int(v))
        save_data()
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await interaction.followup.send(f"✅ 「{done}」を完了にしました。",
                                        ephemeral=True)


@_G.command(name="todo", description="ToDoリストを開く")
async def cmd_todo(interaction):
    if not _on(interaction, "todo"):
        return await _off(interaction, "ToDoリスト")
    view = TodoView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- 天気 / QR / パスワード / 文字数 / タイムスタンプ / カラー
register_feature("weather", CAT, "天気", "🌤️", "天気予報を表示する。")


def _fetch_weather(city):
    url = ("https://wttr.in/" + urllib.parse.quote(city)
           + "?format=j1&lang=ja")
    req = urllib.request.Request(url, headers={"User-Agent": "curl"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8"))


@_G.command(name="天気", description="天気予報を見る")
@discord.app_commands.describe(場所="都市名（例: 加古川）")
async def cmd_weather(interaction, 場所: str = "加古川"):
    if not _on(interaction, "weather"):
        return await _off(interaction, "天気")
    await interaction.response.defer(ephemeral=True)
    try:
        data = await asyncio.to_thread(_fetch_weather, 場所)
        cur = data["current_condition"][0]
        area = data["nearest_area"][0]["areaName"][0]["value"]
        desc = (cur.get("lang_ja") or cur.get("weatherDesc"))[0]["value"]
        embed = discord.Embed(title=f"🌤️ {area} の天気",
                              color=discord.Color.sky_blue())
        embed.add_field(name="天気", value=desc, inline=True)
        embed.add_field(name="気温", value=f"{cur['temp_C']}℃", inline=True)
        embed.add_field(name="体感", value=f"{cur['FeelsLikeC']}℃", inline=True)
        embed.add_field(name="湿度", value=f"{cur['humidity']}%", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "⚠️ 天気を取得できませんでした。", ephemeral=True)


register_feature("qr", CAT, "QRコード", "🔳", "テキストからQRコードを作る。")


@_G.command(name="qr", description="QRコードを作る")
@discord.app_commands.describe(テキスト="URLやテキスト")
async def cmd_qr(interaction, テキスト: str):
    if not _on(interaction, "qr"):
        return await _off(interaction, "QRコード")
    url = ("https://api.qrserver.com/v1/create-qr-code/?size=240x240&data="
           + urllib.parse.quote(テキスト[:500]))
    embed = discord.Embed(title="🔳 QRコード", color=discord.Color.blurple())
    embed.set_image(url=url)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("password", CAT, "パスワード生成", "🔑",
                 "安全なパスワードを生成する。")


@_G.command(name="パスワード生成", description="ランダムパスワードを作る")
@discord.app_commands.describe(長さ="文字数（8〜64）")
async def cmd_password(interaction, 長さ: int = 16):
    if not _on(interaction, "password"):
        return await _off(interaction, "パスワード生成")
    n = max(8, min(64, int(長さ)))
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pw = "".join(secrets.choice(chars) for _ in range(n))
    await interaction.response.send_message(
        f"🔑 生成しました（この画面だけに表示）:\n`{pw}`", ephemeral=True)


register_feature("charcount", CAT, "文字数カウント", "🔢",
                 "文章の文字数を数える。")


class _CountModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🔢 文字数カウント")
        self.text = discord.ui.TextInput(
            label="文章", style=discord.TextStyle.paragraph, max_length=4000)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        text = str(self.text.value)
        await interaction.response.send_message(
            f"🔢 文字数: **{len(text)}**（空白なし {len(text.replace(' ', '').replace('　', ''))}）"
            f" / 行数: {text.count(chr(10)) + 1}", ephemeral=True)


@_G.command(name="文字数", description="文章の文字数を数える")
async def cmd_charcount(interaction):
    if not _on(interaction, "charcount"):
        return await _off(interaction, "文字数カウント")
    await interaction.response.send_modal(_CountModal())


register_feature("timestamp", CAT, "タイムスタンプ生成", "🕐",
                 "Discordのタイムスタンプ記法を作る。")


@_G.command(name="タイムスタンプ", description="タイムスタンプ記法を作る")
@discord.app_commands.describe(日時="YYYY-MM-DD HH:MM")
async def cmd_timestamp(interaction, 日時: str):
    if not _on(interaction, "timestamp"):
        return await _off(interaction, "タイムスタンプ生成")
    from events import _parse_dt
    dt = _parse_dt(日時)
    if dt is None:
        return await interaction.response.send_message(
            "⚠️ 「2026-12-31 20:00」の形で入れてね。", ephemeral=True)
    ts = int(dt.timestamp())
    lines = [f"`<t:{ts}>` → <t:{ts}>",
             f"`<t:{ts}:R>` → <t:{ts}:R>",
             f"`<t:{ts}:F>` → <t:{ts}:F>"]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


register_feature("color", CAT, "カラープレビュー", "🎨",
                 "色コードの情報を表示する。")


@_G.command(name="カラー", description="色コードの情報を見る")
@discord.app_commands.describe(色コード="例: #ff8800")
async def cmd_color(interaction, 色コード: str):
    if not _on(interaction, "color"):
        return await _off(interaction, "カラープレビュー")
    hexv = 色コード.strip().lstrip("#")
    try:
        value = int(hexv, 16)
        if not (0 <= value <= 0xFFFFFF):
            raise ValueError
    except ValueError:
        return await interaction.response.send_message(
            "⚠️ #ff8800 の形で入れてね。", ephemeral=True)
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    embed = discord.Embed(title=f"🎨 #{hexv.lower()}", color=value)
    embed.add_field(name="RGB", value=f"{r}, {g}, {b}", inline=True)
    embed.add_field(name="10進数", value=str(value), inline=True)
    embed.set_thumbnail(url=f"https://dummyimage.com/100x100/{hexv}/{hexv}.png")
    await interaction.response.send_message(embed=embed, ephemeral=True)
