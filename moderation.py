# 機能群: モデレーション（警告/タイムアウト/キック/BAN/削除/各種ガード/ログ）
import re
import time
from datetime import timedelta

import discord

from core import (JST, bot, feature_cfg, feature_enabled, guild_data,
                  is_privileged, jst_now, register_feature, save_data,
                  command_group)

CAT = "moderation"

_G = command_group("moderation", "モデレーション", "モデレーション機能")


def _can(user, perm):
    if is_privileged(user):
        return True
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and getattr(perms, perm, False))


async def modlog(guild, title, fields, color=discord.Color.orange()):
    cfg = feature_cfg(guild.id, "modlog")
    if not cfg.get("enabled"):
        return
    cid = cfg.get("channel_id")
    if not cid:
        return
    channel = guild.get_channel(int(cid))
    if channel is None:
        return
    embed = discord.Embed(title=title, color=color)
    for name, value in fields:
        embed.add_field(name=name, value=str(value)[:1024], inline=True)
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _need(interaction, feature, perm):
    if interaction.guild is None:
        await interaction.response.send_message("⚠️ サーバーの中で使ってね。", ephemeral=True)
        return False
    if not feature_enabled(interaction.guild.id, feature):
        await interaction.response.send_message("⚠️ この機能は無効です。", ephemeral=True)
        return False
    if not _can(interaction.user, perm):
        await interaction.response.send_message("⚠️ 権限がありません。", ephemeral=True)
        return False
    return True


# ---------------------------------------------------------------- 警告
register_feature(
    "warn", CAT, "警告", "⚠️", "メンバーへ警告を記録する。",
    settings=[
        {"key": "threshold", "label": "自動タイムアウトになる警告回数（0=なし）",
         "type": "number", "default": 0},
        {"key": "timeout_minutes", "label": "自動タイムアウトの分数",
         "type": "number", "default": 10},
    ],
    help_text="/警告 @メンバー 理由 で記録。/警告一覧 で確認、/警告解除 で消せます。")


def _warns(gid, uid):
    return guild_data(gid).setdefault("warns", {}).setdefault(str(uid), [])


@_G.command(name="警告", description="メンバーに警告する（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", 理由="理由")
async def cmd_warn(interaction, メンバー: discord.Member, 理由: str = "理由なし"):
    if not await _need(interaction, "warn", "moderate_members"):
        return
    warns = _warns(interaction.guild.id, メンバー.id)
    warns.append({"by": interaction.user.id, "reason": 理由,
                  "at": jst_now().isoformat()})
    save_data()
    cfg = feature_cfg(interaction.guild.id, "warn")
    await interaction.response.send_message(
        f"⚠️ {メンバー.mention} に警告しました（累計 {len(warns)} 回）: {理由}",
        ephemeral=True)
    await modlog(interaction.guild, "⚠️ 警告",
                 [("対象", メンバー.mention), ("実行者", interaction.user.mention),
                  ("理由", 理由), ("累計", f"{len(warns)} 回")])
    threshold = int(cfg.get("threshold") or 0)
    if threshold and len(warns) >= threshold:
        try:
            await メンバー.timeout(
                timedelta(minutes=int(cfg.get("timeout_minutes") or 10)),
                reason="警告の累計による自動タイムアウト")
        except Exception:
            pass


@_G.command(name="警告一覧", description="メンバーの警告履歴を見る（モデレーター用）")
@discord.app_commands.describe(メンバー="対象")
async def cmd_warn_list(interaction, メンバー: discord.Member):
    if not await _need(interaction, "warn", "moderate_members"):
        return
    warns = _warns(interaction.guild.id, メンバー.id)
    if not warns:
        return await interaction.response.send_message(
            "警告はありません。", ephemeral=True)
    lines = [f"{i+1}. {w['reason']}（{w['at'][:10]}）"
             for i, w in enumerate(warns[-10:])]
    await interaction.response.send_message(
        f"⚠️ {メンバー.mention} の警告 {len(warns)} 件\n" + "\n".join(lines),
        ephemeral=True)


@_G.command(name="警告解除", description="メンバーの警告を全て消す（モデレーター用）")
@discord.app_commands.describe(メンバー="対象")
async def cmd_warn_clear(interaction, メンバー: discord.Member):
    if not await _need(interaction, "warn", "moderate_members"):
        return
    guild_data(interaction.guild.id).setdefault("warns", {})[str(メンバー.id)] = []
    save_data()
    await interaction.response.send_message(
        f"✅ {メンバー.mention} の警告を解除しました。", ephemeral=True)


# ---------------------------------------------------------------- 処分系
register_feature("timeout", CAT, "タイムアウト", "🔇",
                 "メンバーを一定時間タイムアウトする。",
                 help_text="/タイムアウト @メンバー 分数 理由 で実行します。")
register_feature("kick", CAT, "キック", "👢", "メンバーをキックする。",
                 help_text="/キック @メンバー 理由 で実行します。")
register_feature("ban", CAT, "BAN", "🔨", "メンバーのBANと解除。",
                 help_text="/バン @メンバー 理由、解除は /バン解除 ユーザーID。")


@_G.command(name="タイムアウト", description="メンバーをタイムアウトする（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", 分数="分数（最大40320）", 理由="理由")
async def cmd_timeout(interaction, メンバー: discord.Member, 分数: int,
                      理由: str = "理由なし"):
    if not await _need(interaction, "timeout", "moderate_members"):
        return
    minutes = max(1, min(40320, int(分数)))
    try:
        await メンバー.timeout(timedelta(minutes=minutes), reason=理由)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ タイムアウトできませんでした（権限・ロール順を確認）。", ephemeral=True)
    await interaction.response.send_message(
        f"🔇 {メンバー.mention} を {minutes} 分タイムアウトしました。", ephemeral=True)
    await modlog(interaction.guild, "🔇 タイムアウト",
                 [("対象", メンバー.mention), ("時間", f"{minutes} 分"),
                  ("理由", 理由)])


@_G.command(name="キック", description="メンバーをキックする（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", 理由="理由")
async def cmd_kick(interaction, メンバー: discord.Member, 理由: str = "理由なし"):
    if not await _need(interaction, "kick", "kick_members"):
        return
    try:
        await メンバー.kick(reason=理由)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ キックできませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"👢 {メンバー.mention} をキックしました。", ephemeral=True)
    await modlog(interaction.guild, "👢 キック",
                 [("対象", メンバー.mention), ("理由", 理由)])


@_G.command(name="バン", description="メンバーをBANする（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", 理由="理由")
async def cmd_ban(interaction, メンバー: discord.Member, 理由: str = "理由なし"):
    if not await _need(interaction, "ban", "ban_members"):
        return
    try:
        await メンバー.ban(reason=理由)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ BANできませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"🔨 {メンバー.mention} をBANしました。", ephemeral=True)
    await modlog(interaction.guild, "🔨 BAN",
                 [("対象", メンバー.mention), ("理由", 理由)],
                 color=discord.Color.red())


@_G.command(name="バン解除", description="ユーザーのBANを解除する（モデレーター用）")
@discord.app_commands.describe(ユーザーid="対象のユーザーID")
async def cmd_unban(interaction, ユーザーid: str):
    if not await _need(interaction, "ban", "ban_members"):
        return
    try:
        user = await bot.fetch_user(int(ユーザーid))
        await interaction.guild.unban(user)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 解除できませんでした（ID・BAN状態を確認）。", ephemeral=True)
    await interaction.response.send_message(
        f"✅ {user.mention} のBANを解除しました。", ephemeral=True)


# ---------------------------------------------------------------- 一括削除
register_feature("purge", CAT, "一括削除", "🧹",
                 "チャンネルのメッセージをまとめて削除する。",
                 settings=[{"key": "max_count", "label": "1回の上限件数",
                            "type": "number", "default": 200}],
                 help_text="/一括削除 件数 で直近のメッセージを消します。")


@_G.command(name="一括削除", description="メッセージを一括削除する（モデレーター用）")
@discord.app_commands.describe(件数="消す件数")
async def cmd_purge(interaction, 件数: int):
    if not await _need(interaction, "purge", "manage_messages"):
        return
    cfg = feature_cfg(interaction.guild.id, "purge")
    count = max(1, min(int(cfg.get("max_count") or 200), int(件数)))
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=count)
        n = len(deleted)
    except Exception:
        n = 0
    await interaction.followup.send(f"🧹 {n} 件削除しました。", ephemeral=True)
    await modlog(interaction.guild, "🧹 一括削除",
                 [("チャンネル", interaction.channel.mention),
                  ("件数", f"{n} 件"), ("実行者", interaction.user.mention)])


# ---------------------------------------------------------------- スローモード/ロック
register_feature("slowmode", CAT, "スローモード", "🐌",
                 "チャンネルのスローモードを設定する。",
                 help_text="/スローモード 秒数（0で解除）。")
register_feature("lock", CAT, "チャンネルロック", "🔒",
                 "チャンネルの発言を止める/再開する。",
                 help_text="/ロック と /ロック解除。")


@_G.command(name="スローモード", description="スローモードを設定する（モデレーター用）")
@discord.app_commands.describe(秒数="間隔の秒数（0=解除）")
async def cmd_slowmode(interaction, 秒数: int):
    if not await _need(interaction, "slowmode", "manage_channels"):
        return
    seconds = max(0, min(21600, int(秒数)))
    try:
        await interaction.channel.edit(slowmode_delay=seconds)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 設定できませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"🐌 スローモードを {seconds} 秒にしました。", ephemeral=True)


@_G.command(name="ロック", description="このチャンネルをロックする（モデレーター用）")
async def cmd_lock(interaction):
    if not await _need(interaction, "lock", "manage_channels"):
        return
    try:
        await interaction.channel.set_permissions(
            interaction.guild.default_role, send_messages=False)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ ロックできませんでした。", ephemeral=True)
    await interaction.response.send_message("🔒 チャンネルをロックしました。")


@_G.command(name="ロック解除", description="このチャンネルのロックを解除する（モデレーター用）")
async def cmd_unlock(interaction):
    if not await _need(interaction, "lock", "manage_channels"):
        return
    try:
        await interaction.channel.set_permissions(
            interaction.guild.default_role, send_messages=None)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 解除できませんでした。", ephemeral=True)
    await interaction.response.send_message("🔓 ロックを解除しました。")


# ---------------------------------------------------------------- ガード系（メッセージ監視）
register_feature(
    "ngword", CAT, "NGワード", "🚫", "NGワードを含む発言を自動削除する。",
    settings=[{"key": "words", "label": "NGワード（1行に1つ）", "type": "text",
               "style": "long", "default": ""}],
    help_text="/設定 でNGワードを1行に1つずつ登録します。")
register_feature(
    "spam", CAT, "連投対策", "🌊", "短時間の連投・同じ内容の繰り返しを止める。",
    settings=[
        {"key": "seconds", "label": "判定する秒数", "type": "number", "default": 5},
        {"key": "count", "label": "この件数以上で連投とみなす", "type": "number",
         "default": 5},
        {"key": "action", "label": "対処", "type": "choice", "default": "delete",
         "options": [("delete", "削除のみ"), ("timeout", "削除＋5分タイムアウト")]},
    ])
register_feature(
    "linkguard", CAT, "リンク規制", "🔗", "URLを含む発言を自動削除する。",
    settings=[{"key": "allow_admin", "label": "管理者は除外", "type": "toggle",
               "default": True}])
register_feature(
    "inviteguard", CAT, "招待リンク規制", "✉️",
    "他サーバーの招待リンクを自動削除する。")
register_feature(
    "mentionguard", CAT, "メンション規制", "📢",
    "メンションが多すぎる発言を自動削除する。",
    settings=[{"key": "max_mentions", "label": "上限メンション数", "type": "number",
               "default": 5}])

_history = {}
_URL_RE = re.compile(r"https?://", re.I)
_INVITE_RE = re.compile(r"(discord\.gg/|discord\.com/invite/)", re.I)


@bot.listen("on_message")
async def _guards(message):
    if message.guild is None or message.author.bot:
        return
    if is_privileged(message.author):
        gid = message.guild.id
        if not (feature_enabled(gid, "linkguard")
                and not feature_cfg(gid, "linkguard").get("allow_admin", True)):
            return
    gid = message.guild.id
    content = message.content or ""
    try:
        if feature_enabled(gid, "ngword"):
            words = [w.strip() for w in
                     str(feature_cfg(gid, "ngword").get("words") or "").splitlines()
                     if w.strip()]
            if any(w in content for w in words):
                await message.delete()
                await modlog(message.guild, "🚫 NGワード削除",
                             [("ユーザー", message.author.mention),
                              ("チャンネル", message.channel.mention)])
                return
        if feature_enabled(gid, "inviteguard") and _INVITE_RE.search(content):
            await message.delete()
            await modlog(message.guild, "✉️ 招待リンク削除",
                         [("ユーザー", message.author.mention)])
            return
        if feature_enabled(gid, "linkguard") and _URL_RE.search(content):
            await message.delete()
            await modlog(message.guild, "🔗 リンク削除",
                         [("ユーザー", message.author.mention)])
            return
        if feature_enabled(gid, "mentionguard"):
            limit = int(feature_cfg(gid, "mentionguard").get("max_mentions") or 5)
            if len(message.mentions) + len(message.role_mentions) > limit:
                await message.delete()
                await modlog(message.guild, "📢 メンション規制",
                             [("ユーザー", message.author.mention)])
                return
        if feature_enabled(gid, "spam"):
            cfg = feature_cfg(gid, "spam")
            window = float(cfg.get("seconds") or 5)
            limit = int(cfg.get("count") or 5)
            key = (gid, message.author.id)
            now = time.monotonic()
            hist = [t for t in _history.get(key, []) if now - t < window]
            hist.append(now)
            _history[key] = hist
            if len(hist) >= limit:
                _history[key] = []
                await message.delete()
                if cfg.get("action") == "timeout":
                    try:
                        await message.author.timeout(
                            timedelta(minutes=5), reason="連投対策")
                    except Exception:
                        pass
                await modlog(message.guild, "🌊 連投対策",
                             [("ユーザー", message.author.mention)])
    except Exception:
        pass


# ---------------------------------------------------------------- 新規アカウント規制
register_feature(
    "newaccount", CAT, "新規アカウント規制", "🆕",
    "作りたてのアカウントの参加を通知またはキックする。",
    settings=[
        {"key": "days", "label": "作成からこの日数未満を対象", "type": "number",
         "default": 3},
        {"key": "action", "label": "対処", "type": "choice", "default": "notify",
         "options": [("notify", "ログに通知のみ"), ("kick", "自動キック")]},
    ])


@bot.listen("on_member_join")
async def _newaccount_guard(member):
    try:
        if not feature_enabled(member.guild.id, "newaccount"):
            return
        cfg = feature_cfg(member.guild.id, "newaccount")
        age_days = (jst_now() - member.created_at.astimezone(JST)).days
        if age_days >= int(cfg.get("days") or 3):
            return
        await modlog(member.guild, "🆕 新規アカウント参加",
                     [("ユーザー", member.mention),
                      ("アカウント作成", f"{age_days} 日前")],
                     color=discord.Color.red())
        if cfg.get("action") == "kick":
            await member.kick(reason="新規アカウント規制")
    except Exception:
        pass


# ---------------------------------------------------------------- ログ/ロール/ニックネーム/ピン
register_feature("modlog", CAT, "モデレーションログ", "📋",
                 "処分や自動削除をログチャンネルに残す。",
                 settings=[{"key": "channel_id", "label": "ログチャンネル",
                            "type": "channel", "default": None}])
register_feature("rolemanage", CAT, "ロール管理", "🎭",
                 "コマンドでロールを付け外しする。",
                 help_text="/ロール付与 /ロール剥奪 @メンバー ロール名。")


@_G.command(name="ロール付与", description="メンバーにロールを付ける（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", ロール="付けるロール")
async def cmd_role_add(interaction, メンバー: discord.Member, ロール: discord.Role):
    if not await _need(interaction, "rolemanage", "manage_roles"):
        return
    try:
        await メンバー.add_roles(ロール)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 付けられませんでした（BOTのロール順を確認）。", ephemeral=True)
    await interaction.response.send_message(
        f"🎭 {メンバー.mention} に {ロール.mention} を付けました。", ephemeral=True)


@_G.command(name="ロール剥奪", description="メンバーのロールを外す（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", ロール="外すロール")
async def cmd_role_remove(interaction, メンバー: discord.Member, ロール: discord.Role):
    if not await _need(interaction, "rolemanage", "manage_roles"):
        return
    try:
        await メンバー.remove_roles(ロール)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 外せませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"🎭 {メンバー.mention} から {ロール.mention} を外しました。", ephemeral=True)


register_feature("nick", CAT, "ニックネーム変更", "✏️",
                 "メンバーのニックネームを変更する。",
                 help_text="/ニックネーム @メンバー 新しい名前。")


@_G.command(name="ニックネーム", description="ニックネームを変更する（モデレーター用）")
@discord.app_commands.describe(メンバー="対象", 名前="新しいニックネーム")
async def cmd_nick(interaction, メンバー: discord.Member, 名前: str):
    if not await _need(interaction, "nick", "manage_nicknames"):
        return
    try:
        await メンバー.edit(nick=名前[:32])
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 変更できませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"✏️ {メンバー.mention} のニックネームを変更しました。", ephemeral=True)


register_feature("pinmanage", CAT, "ピン留め管理", "📌",
                 "メッセージIDでピン留め・解除する。",
                 help_text="/ピン留め メッセージID（このチャンネル内）。")


@_G.command(name="ピン留め", description="メッセージをピン留めする（モデレーター用）")
@discord.app_commands.describe(メッセージid="このチャンネルのメッセージID")
async def cmd_pin(interaction, メッセージid: str):
    if not await _need(interaction, "pinmanage", "manage_messages"):
        return
    try:
        msg = await interaction.channel.fetch_message(int(メッセージid))
        await msg.pin()
    except Exception:
        return await interaction.response.send_message(
            "⚠️ ピン留めできませんでした。", ephemeral=True)
    await interaction.response.send_message("📌 ピン留めしました。", ephemeral=True)


@_G.command(name="ピン解除", description="メッセージのピン留めを外す（モデレーター用）")
@discord.app_commands.describe(メッセージid="このチャンネルのメッセージID")
async def cmd_unpin(interaction, メッセージid: str):
    if not await _need(interaction, "pinmanage", "manage_messages"):
        return
    try:
        msg = await interaction.channel.fetch_message(int(メッセージid))
        await msg.unpin()
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 解除できませんでした。", ephemeral=True)
    await interaction.response.send_message("📌 ピン留めを解除しました。", ephemeral=True)
