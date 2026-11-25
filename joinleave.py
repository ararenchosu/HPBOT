# 機能: 入退室通知（参加・退出の詳細Embed）
# 表示形式は指定フォーマット: ユーザー名 / ユーザーID / アカウント作成日 / 作成からの経過
from datetime import datetime, timedelta, timezone

import discord

from core import bot, feature_cfg, register_feature

JST = timezone(timedelta(hours=9))

register_feature(
    "join_leave", "enter", "入退室通知", "📥",
    "メンバーが参加・退出したときに、詳細つきのEmbedで通知する。",
    settings=[
        {"key": "channel_id", "label": "送信先チャンネル", "type": "channel",
         "default": None},
        {"key": "join_on", "label": "参加メッセージ", "type": "toggle",
         "default": True},
        {"key": "leave_on", "label": "退出メッセージ", "type": "toggle",
         "default": True},
    ],
    help_text=("管理者が /設定 → 👋 入退室・認証 → 入退室通知 で有効化し、"
               "送信先チャンネルと参加/退出それぞれのON・OFFを決めます。"),
)


def _member_embed(member, joined: bool) -> discord.Embed:
    created = member.created_at
    days = (datetime.now(timezone.utc) - created).days
    created_jst = created.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    age_note = "（今日作成）" if days == 0 else f"（約{days}日前）"
    embed = discord.Embed(
        title="📥 メンバーが参加しました！" if joined else "📤 メンバーが退出しました！",
        color=discord.Color.green() if joined else discord.Color.red())
    embed.add_field(name="ユーザー名",
                    value=f"{member.mention}\n`{member.name}`", inline=False)
    embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=False)
    embed.add_field(name="アカウント作成日",
                    value=f"{created_jst}\n{age_note}", inline=False)
    embed.add_field(name="作成からの経過", value=f"{days}日", inline=False)
    try:
        embed.set_thumbnail(url=member.display_avatar.url)
    except Exception:
        pass
    return embed


async def _notify(member, joined: bool):
    try:
        cfg = feature_cfg(member.guild.id, "join_leave")
        if not cfg.get("enabled") or not cfg.get("channel_id"):
            return
        if joined and not cfg.get("join_on"):
            return
        if not joined and not cfg.get("leave_on"):
            return
        channel = member.guild.get_channel(int(cfg["channel_id"]))
        if channel is None:
            return
        await channel.send(embed=_member_embed(member, joined))
    except Exception:
        pass


@bot.listen("on_member_join")
async def _on_member_join(member):
    await _notify(member, True)


@bot.listen("on_member_remove")
async def _on_member_remove(member):
    await _notify(member, False)
