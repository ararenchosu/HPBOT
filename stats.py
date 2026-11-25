# 機能群: 分析（統計収集/サーバー統計/発言ランキング/参加推移/コマンド統計/メンバー数表示）
import time
from datetime import timedelta

import discord

from core import (bot, feature_enabled, guild_data, jst_now, register_feature,
                  save_data,
                  command_group)

CAT = "stats"

_G = command_group("stats", "統計", "分析・統計機能")


def _stats(gid):
    return guild_data(gid).setdefault("stats", {
        "user_msgs": {}, "channel_msgs": {}, "daily": {},
        "daily_user": {}, "commands": {}})


@bot.listen("on_message")
async def _collect_message(message):
    if message.guild is None or message.author.bot:
        return
    gid = message.guild.id
    if not feature_enabled(gid, "serverstats"):
        return
    stats = _stats(gid)
    uid = str(message.author.id)
    stats["user_msgs"][uid] = int(stats["user_msgs"].get(uid) or 0) + 1
    cid = str(message.channel.id)
    stats["channel_msgs"][cid] = int(stats["channel_msgs"].get(cid) or 0) + 1
    today = jst_now().date().isoformat()
    day = stats["daily"].setdefault(today, {"joins": 0, "msgs": 0})
    day["msgs"] = int(day.get("msgs") or 0) + 1
    du = stats["daily_user"].setdefault(today, {})
    du[uid] = int(du.get(uid) or 0) + 1
    save_data()


@bot.listen("on_member_join")
async def _collect_join(member):
    gid = member.guild.id
    if not feature_enabled(gid, "serverstats"):
        return
    stats = _stats(gid)
    today = jst_now().date().isoformat()
    day = stats["daily"].setdefault(today, {"joins": 0, "msgs": 0})
    day["joins"] = int(day.get("joins") or 0) + 1
    save_data()
    await _member_counter_update(member.guild)


@bot.listen("on_interaction")
async def _count_command(interaction):
    try:
        if interaction.type != discord.InteractionType.application_command:
            return
        if interaction.guild is None or interaction.command is None:
            return
        if not feature_enabled(interaction.guild.id, "serverstats"):
            return
        stats = _stats(interaction.guild.id)
        name = interaction.command.qualified_name
        stats["commands"][name] = int(stats["commands"].get(name) or 0) + 1
        save_data()
    except Exception:
        pass


def _on(interaction, feature="serverstats"):
    return (interaction.guild is not None
            and feature_enabled(interaction.guild.id, feature))


register_feature("serverstats", CAT, "サーバー統計", "📊",
                 "サーバーの活動統計を表示する（収集もこの機能）。")


@_G.command(name="サーバー統計", description="サーバーの統計を見る")
async def cmd_serverstats(interaction):
    if not _on(interaction):
        return await interaction.response.send_message(
            "⚠️ 統計は無効です。", ephemeral=True)
    guild = interaction.guild
    stats = _stats(guild.id)
    total_msgs = sum(stats["user_msgs"].values())
    top_channel = max(stats["channel_msgs"].items(),
                      key=lambda kv: kv[1], default=(None, 0))
    embed = discord.Embed(title=f"📊 {guild.name} の統計",
                          color=discord.Color.blue())
    embed.add_field(name="メンバー数", value=f"{guild.member_count} 人",
                    inline=True)
    embed.add_field(name="集計発言数", value=f"{total_msgs:,} 件", inline=True)
    if top_channel[0]:
        embed.add_field(name="一番活発なチャンネル",
                        value=f"<#{top_channel[0]}>（{top_channel[1]:,} 件）",
                        inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("msgstats", CAT, "発言ランキング", "💬",
                 "発言数ランキングを表示する。")


@_G.command(name="発言ランキング", description="発言数ランキングを見る")
async def cmd_msgstats(interaction):
    if not _on(interaction, "msgstats"):
        return await interaction.response.send_message(
            "⚠️ 発言ランキングは無効です。", ephemeral=True)
    stats = _stats(interaction.guild.id)
    ordered = sorted(stats["user_msgs"].items(), key=lambda kv: kv[1],
                     reverse=True)[:10]
    lines = [f"{i}. <@{uid}> — {n:,} 件" for i, (uid, n) in
             enumerate(ordered, 1)]
    await interaction.response.send_message(
        embed=discord.Embed(title="💬 発言ランキング",
                            description="\n".join(lines) or "データなし",
                            color=discord.Color.blue()),
        ephemeral=True)


register_feature("activerank", CAT, "アクティブランキング", "🔥",
                 "直近7日の発言ランキング。")


@_G.command(name="アクティブランキング", description="直近7日の発言ランキングを見る")
async def cmd_activerank(interaction):
    if not _on(interaction, "activerank"):
        return await interaction.response.send_message(
            "⚠️ アクティブランキングは無効です。", ephemeral=True)
    stats = _stats(interaction.guild.id)
    totals = {}
    today = jst_now().date()
    for offset in range(7):
        day = (today - timedelta(days=offset)).isoformat()
        for uid, n in stats["daily_user"].get(day, {}).items():
            totals[uid] = totals.get(uid, 0) + int(n)
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:10]
    lines = [f"{i}. <@{uid}> — {n:,} 件" for i, (uid, n) in
             enumerate(ordered, 1)]
    await interaction.response.send_message(
        embed=discord.Embed(title="🔥 アクティブランキング（7日）",
                            description="\n".join(lines) or "データなし",
                            color=discord.Color.orange()),
        ephemeral=True)


register_feature("jointrend", CAT, "参加推移", "📈",
                 "直近14日の参加人数の推移。")


@_G.command(name="参加推移", description="参加人数の推移を見る")
async def cmd_jointrend(interaction):
    if not _on(interaction, "jointrend"):
        return await interaction.response.send_message(
            "⚠️ 参加推移は無効です。", ephemeral=True)
    stats = _stats(interaction.guild.id)
    today = jst_now().date()
    lines = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        joins = int(stats["daily"].get(day.isoformat(), {}).get("joins") or 0)
        lines.append(f"{day.strftime('%m/%d')} {'█' * min(joins, 30)} {joins}")
    await interaction.response.send_message(
        "📈 **参加推移（14日）**\n```\n" + "\n".join(lines) + "\n```",
        ephemeral=True)


register_feature("cmdstats", CAT, "コマンド統計", "⌨️",
                 "よく使われるコマンドの集計。")


@_G.command(name="コマンド統計", description="コマンド使用統計を見る")
async def cmd_cmdstats(interaction):
    if not _on(interaction, "cmdstats"):
        return await interaction.response.send_message(
            "⚠️ コマンド統計は無効です。", ephemeral=True)
    stats = _stats(interaction.guild.id)
    ordered = sorted(stats["commands"].items(), key=lambda kv: kv[1],
                     reverse=True)[:10]
    lines = [f"{i}. /{name} — {n} 回" for i, (name, n) in
             enumerate(ordered, 1)]
    await interaction.response.send_message(
        embed=discord.Embed(title="⌨️ コマンド統計",
                            description="\n".join(lines) or "データなし",
                            color=discord.Color.blue()),
        ephemeral=True)


register_feature(
    "membercounter", CAT, "メンバー数カウンター", "👥",
    "チャンネル名にメンバー数を表示する。",
    settings=[{"key": "channel_id", "label": "対象チャンネル（名前が変わります）",
               "type": "channel", "default": None},
              {"key": "format", "label": "名前の形式（{count}=人数）",
               "type": "text", "default": "👥 メンバー: {count}人"}])

_counter_last = {}


async def _member_counter_update(guild):
    try:
        if not feature_enabled(guild.id, "membercounter"):
            return
        from core import feature_cfg
        cfg = feature_cfg(guild.id, "membercounter")
        cid = cfg.get("channel_id")
        if not cid:
            return
        now = time.monotonic()
        if now - _counter_last.get(guild.id, 0) < 300:
            return
        _counter_last[guild.id] = now
        channel = guild.get_channel(int(cid))
        if channel is None:
            return
        name = (cfg.get("format") or "👥 メンバー: {count}人").replace(
            "{count}", str(guild.member_count))
        if channel.name != name:
            await channel.edit(name=name[:100])
    except Exception:
        pass


@bot.listen("on_member_remove")
async def _collect_leave(member):
    await _member_counter_update(member.guild)
