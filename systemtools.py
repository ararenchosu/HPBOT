# 機能群: システム（設定バックアップ/告知/テンプレ/一括ロール/複製/メンバー出力/ピン一覧）
import io
import json

import discord

from core import (bot, data_store, feature_enabled, is_privileged,
                  register_feature, save_config, save_data, store,
                  command_group)

CAT = "system"

_G = command_group("system", "システム", "システム機能")


def _admin(interaction, feature):
    return (interaction.guild is not None
            and is_privileged(interaction.user)
            and feature_enabled(interaction.guild.id, feature))


# ---------------------------------------------------------------- バックアップ
register_feature("backup", CAT, "設定バックアップ", "💾",
                 "サーバー設定をJSONで書き出し/読み込みする。")


@_G.command(name="設定エクスポート", description="設定をJSONで書き出す（管理者用）")
async def cmd_export(interaction):
    if not _admin(interaction, "backup"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    gid = str(interaction.guild.id)
    payload = {"config": store.data.get(gid, {}),
               "data": data_store.data.get(gid, {})}
    raw = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    await interaction.response.send_message(
        "💾 設定ファイルです。大切に保管してね。",
        file=discord.File(io.BytesIO(raw), filename="mega-backup.json"),
        ephemeral=True)


@_G.command(name="設定インポート", description="設定JSONを読み込む（管理者用）")
@discord.app_commands.describe(ファイル="書き出したJSONファイル")
async def cmd_import(interaction, ファイル: discord.Attachment):
    if not _admin(interaction, "backup"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    try:
        raw = await ファイル.read()
        payload = json.loads(raw.decode("utf-8"))
        gid = str(interaction.guild.id)
        if "config" in payload:
            store.data[gid] = payload["config"]
            save_config()
        if "data" in payload:
            data_store.data[gid] = payload["data"]
            save_data()
        from core import refresh_panels
        await refresh_panels(interaction.guild.id)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 読み込めませんでした。書き出したファイルを使ってね。",
            ephemeral=True)
    await interaction.response.send_message(
        "💾 設定を読み込みました。", ephemeral=True)


# ---------------------------------------------------------------- 告知
register_feature("announce", CAT, "告知作成", "📣",
                 "BOT名義で告知Embedを投稿する。")


class _AnnounceModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="📣 告知を作成")
        self.title_input = discord.ui.TextInput(label="タイトル", max_length=100)
        self.body_input = discord.ui.TextInput(
            label="本文", style=discord.TextStyle.paragraph, max_length=2000)
        self.add_item(self.title_input)
        self.add_item(self.body_input)

    async def on_submit(self, interaction):
        embed = discord.Embed(
            title=str(self.title_input.value),
            description=str(self.body_input.value),
            color=discord.Color.blurple())
        embed.set_footer(text=f"告知: {interaction.guild.name}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("📣 告知を投稿しました。",
                                                ephemeral=True)


@_G.command(name="告知", description="告知Embedを投稿する（管理者用）")
async def cmd_announce(interaction):
    if not _admin(interaction, "announce"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    await interaction.response.send_modal(_AnnounceModal())


# ---------------------------------------------------------------- チャンネルテンプレ
register_feature(
    "channeltemplate", CAT, "チャンネルテンプレ", "🏗️",
    "カテゴリとチャンネルをまとめて作成する。",
    settings=[{"key": "template", "label": "テンプレ（カテゴリ名: ch1, ch2 の形で1行ずつ）",
               "type": "text", "style": "long",
               "default": "📢 情報: お知らせ, ルール\n💬 交流: 雑談, 自己紹介\n"
                          "❓ サポート: 質問, チケット案内"}])


@_G.command(name="テンプレ適用", description="テンプレでチャンネルを作成する（管理者用）")
async def cmd_template(interaction):
    if not _admin(interaction, "channeltemplate"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    from core import feature_cfg
    text = feature_cfg(interaction.guild.id,
                       "channeltemplate").get("template") or ""
    await interaction.response.defer(ephemeral=True)
    created = 0
    for line in text.splitlines():
        if ":" not in line:
            continue
        cat_name, chans = line.split(":", 1)
        cat_name = cat_name.strip()
        if not cat_name:
            continue
        try:
            category = await interaction.guild.create_category(cat_name[:100])
            for name in chans.split(","):
                name = name.strip()
                if name:
                    await interaction.guild.create_text_channel(
                        name[:100], category=category)
                    created += 1
        except Exception:
            pass
    await interaction.followup.send(
        f"🏗️ テンプレを適用しました（{created} チャンネル作成）。",
        ephemeral=True)


# ---------------------------------------------------------------- 一括ロール
register_feature("bulkrole", CAT, "一括ロール付与", "🎁",
                 "条件に合う全員へロールを付ける。")


@_G.command(name="一括ロール", description="全員にロールを付ける（管理者用）")
@discord.app_commands.describe(ロール="付けるロール", 対象="対象")
@discord.app_commands.choices(対象=[
    discord.app_commands.Choice(name="全員", value="all"),
    discord.app_commands.Choice(name="BOT以外", value="human"),
    discord.app_commands.Choice(name="BOTのみ", value="bot")])
async def cmd_bulkrole(interaction, ロール: discord.Role, 対象: str = "human"):
    if not _admin(interaction, "bulkrole"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    count = 0
    for member in interaction.guild.members:
        if 対象 == "human" and member.bot:
            continue
        if 対象 == "bot" and not member.bot:
            continue
        if ロール in member.roles:
            continue
        try:
            await member.add_roles(ロール)
            count += 1
        except Exception:
            pass
    await interaction.followup.send(
        f"🎁 {count} 人に {ロール.mention} を付けました。", ephemeral=True)


# ---------------------------------------------------------------- チャンネル複製
register_feature("clone", CAT, "チャンネル複製", "📑",
                 "このチャンネルを複製する。")


@_G.command(name="チャンネル複製", description="このチャンネルを複製する（管理者用）")
async def cmd_clone(interaction):
    if not _admin(interaction, "clone"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    try:
        new_channel = await interaction.channel.clone()
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 複製できませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"📑 複製しました: {new_channel.mention}", ephemeral=True)


# ---------------------------------------------------------------- メンバー出力
register_feature("memberexport", CAT, "メンバー一覧出力", "📄",
                 "メンバー一覧をCSVで出力する。")


@_G.command(name="メンバー一覧出力", description="メンバー一覧をCSVで出す（管理者用）")
async def cmd_memberexport(interaction):
    if not _admin(interaction, "memberexport"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    lines = ["name,id,joined_at,is_bot"]
    for member in interaction.guild.members:
        joined = member.joined_at.strftime("%Y-%m-%d") if member.joined_at else ""
        lines.append(f"{member.name},{member.id},{joined},{member.bot}")
    raw = "\n".join(lines).encode("utf-8-sig")
    await interaction.response.send_message(
        "📄 メンバー一覧です。",
        file=discord.File(io.BytesIO(raw), filename="members.csv"),
        ephemeral=True)


# ---------------------------------------------------------------- ピン留め一覧
register_feature("pinlist", CAT, "ピン留め一覧", "📌",
                 "このチャンネルのピン留めを一覧表示する。")


@_G.command(name="ピン留め一覧", description="ピン留め一覧を見る")
async def cmd_pinlist(interaction):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "pinlist"):
        return await interaction.response.send_message(
            "⚠️ ピン留め一覧は無効です。", ephemeral=True)
    try:
        pins = await interaction.channel.pins()
    except Exception:
        pins = []
    if not pins:
        return await interaction.response.send_message(
            "📌 ピン留めはありません。", ephemeral=True)
    lines = [f"・[{m.author.display_name}] {m.content[:50] or '（本文なし）'} "
             f"{m.jump_url}" for m in pins[:15]]
    await interaction.response.send_message(
        "📌 **ピン留め一覧**\n" + "\n".join(lines), ephemeral=True)


# ---------------------------------------------------------------- カラーロール（複数色グラデーション対応）
register_feature(
    "colorrole", CAT, "カラーロール作成", "🌈",
    "単色・グラデーションのロールを作成する。",
    settings=[
        {"key": "palette", "label": "一括作成パレット（1行に 名前:#色1:#色2）",
         "type": "text", "style": "long",
         "default": "赤:#ff0000\n青:#0000ff\n虹:#ff0000:#0000ff"},
        {"key": "hoist", "label": "メンバー一覧で分けて表示", "type": "toggle",
         "default": True},
        {"key": "mentionable", "label": "メンション可能にする", "type": "toggle",
         "default": False},
    ],
    help_text=("/システム グラデーションロール 名前 色1 色2 で作成。"
               "色3まで入れるとホログラフィックになります"
               "（グラデーションはブーストLv2、ホロはLv3のサーバーで有効）。"))


def _parse_color(text):
    hexv = (text or "").strip().lstrip("#")
    value = int(hexv, 16)
    if not (0 <= value <= 0xFFFFFF):
        raise ValueError
    return discord.Colour(value)


async def _create_color_role(interaction, name, colors):
    from core import feature_cfg
    cfg = feature_cfg(interaction.guild.id, "colorrole")
    kwargs = {"name": name[:100],
              "colour": colors[0],
              "hoist": bool(cfg.get("hoist", True)),
              "mentionable": bool(cfg.get("mentionable", False)),
              "reason": "カラーロール作成"}
    if len(colors) >= 2:
        kwargs["secondary_colour"] = colors[1]
    if len(colors) >= 3:
        kwargs["tertiary_colour"] = colors[2]
    return await interaction.guild.create_role(**kwargs)


@_G.command(name="グラデーションロール",
            description="複数色のロールを作成する（管理者用）")
@discord.app_commands.describe(名前="ロール名", 色1="基本色 #ff0000",
                               色2="2色目（グラデーション）",
                               色3="3色目（ホログラフィック・任意）")
async def cmd_gradient_role(interaction, 名前: str, 色1: str, 色2: str,
                            色3: str = ""):
    if not _admin(interaction, "colorrole"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    try:
        colors = [_parse_color(色1), _parse_color(色2)]
        if 色3.strip():
            colors.append(_parse_color(色3))
    except ValueError:
        return await interaction.response.send_message(
            "⚠️ 色は #ff0000 の形で入れてね。", ephemeral=True)
    try:
        role = await _create_color_role(interaction, 名前, colors)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 作成できませんでした。BOTの権限とサーバーのブーストレベルを"
            "確認してね（グラデーションはLv2、ホロはLv3が必要）。",
            ephemeral=True)
    style = "ホログラフィック" if len(colors) >= 3 else "グラデーション"
    await interaction.response.send_message(
        f"🌈 {style}ロール {role.mention} を作成しました。", ephemeral=True)


@_G.command(name="カラーロール", description="単色のロールを作成する（管理者用）")
@discord.app_commands.describe(名前="ロール名", 色="色 #ff0000")
async def cmd_single_role(interaction, 名前: str, 色: str):
    if not _admin(interaction, "colorrole"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    try:
        color = _parse_color(色)
    except ValueError:
        return await interaction.response.send_message(
            "⚠️ 色は #ff0000 の形で入れてね。", ephemeral=True)
    try:
        role = await _create_color_role(interaction, 名前, [color])
    except Exception:
        return await interaction.response.send_message(
            "⚠️ 作成できませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"🌈 ロール {role.mention} を作成しました。", ephemeral=True)


@_G.command(name="カラーパレット作成",
            description="設定したパレットのロールを一括作成する（管理者用）")
async def cmd_palette_roles(interaction):
    if not _admin(interaction, "colorrole"):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます（または機能が無効）。", ephemeral=True)
    from core import feature_cfg
    text = feature_cfg(interaction.guild.id,
                       "colorrole").get("palette") or ""
    await interaction.response.defer(ephemeral=True)
    created, failed = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        parts = [p.strip() for p in line.split(":")]
        name, color_texts = parts[0], parts[1:]
        try:
            colors = [_parse_color(c) for c in color_texts if c]
            if not colors:
                raise ValueError
            role = await _create_color_role(interaction, name, colors)
            created.append(role.mention)
        except Exception:
            failed.append(name)
    message = f"🌈 {len(created)} 件作成しました。"
    if created:
        message += "\n" + " ".join(created)
    if failed:
        message += f"\n⚠️ 失敗: {', '.join(failed)}"
    await interaction.followup.send(message, ephemeral=True)
