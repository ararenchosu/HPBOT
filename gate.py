# 機能: 認証ゲート（ルール同意パネル → 認証ロール付与）
import discord

from core import (bot, feature_cfg, is_privileged, register_feature,
                  register_panel_refresher, save_config, store)

register_feature(
    "gate", "enter", "認証ゲート", "📜",
    "ルール同意パネルで同意したメンバーに認証ロールを付ける。",
    settings=[
        {"key": "role_id", "label": "認証ロール", "type": "role",
         "default": None},
        {"key": "remove_role_id", "label": "認証時に外すロール（任意）", "type": "role",
         "default": None},
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "📜 ルール確認・認証"},
        {"key": "panel_text", "label": "ルール文", "type": "text", "style": "long",
         "default": "サーバーのルールを確認して、同意できる場合のみ認証してね。"},
        {"key": "done_text", "label": "認証完了メッセージ", "type": "text",
         "default": "✅ 認証が完了しました！"},
    ],
    help_text=("管理者が /認証パネル設置 でパネルを置き、/設定 → 👋 入退室・認証 → "
               "認証ゲート で認証ロールと文面を決めます。BOTのロールが認証ロールより"
               "上にある必要があります。"),
)


def build_gate_embed(gid):
    cfg = feature_cfg(gid, "gate")
    return discord.Embed(
        title=cfg.get("panel_title") or "📜 ルール確認・認証",
        description=cfg.get("panel_text") or "",
        color=discord.Color.blurple())


class GatePanelView(discord.ui.View):
    """認証パネル（常時設置・再起動後も動作）"""

    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_gate:agree",
            placeholder="📜 ルールを確認したら選んでね",
            options=[discord.SelectOption(
                label="✅ ルールに同意して認証する", value="agree")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        guild = interaction.guild
        member = interaction.user
        if guild is None:
            return
        cfg = feature_cfg(guild.id, "gate")
        if not cfg.get("enabled"):
            return await interaction.response.send_message(
                "⚠️ 認証ゲートは今は無効です。", ephemeral=True)
        role_id = cfg.get("role_id")
        role = guild.get_role(int(role_id)) if role_id else None
        if role is None:
            return await interaction.response.send_message(
                "⚠️ 認証ロールがまだ設定されていません。管理者に伝えてね。",
                ephemeral=True)
        if role in getattr(member, "roles", []):
            return await interaction.response.send_message(
                "✅ もう認証済みだよ。", ephemeral=True)
        try:
            await member.add_roles(role, reason="認証ゲート")
        except Exception:
            return await interaction.response.send_message(
                "⚠️ ロールを付けられなかったよ。BOTの権限とロールの順番を"
                "管理者に確認してね。", ephemeral=True)
        remove_id = cfg.get("remove_role_id")
        if remove_id:
            remove_role = guild.get_role(int(remove_id))
            if remove_role is not None and remove_role in getattr(member, "roles", []):
                try:
                    await member.remove_roles(remove_role, reason="認証ゲート")
                except Exception:
                    pass
        await interaction.response.send_message(
            cfg.get("done_text") or "✅ 認証が完了しました！", ephemeral=True)


async def refresh_gate_panel(guild_id):
    loc = store.cfg(guild_id).get("gate_panel") or {}
    if not loc.get("channel_id") or not loc.get("message_id"):
        return
    channel = bot.get_channel(int(loc["channel_id"]))
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(int(loc["message_id"]))
        await msg.edit(embed=build_gate_embed(guild_id), view=GatePanelView())
    except Exception:
        pass


register_panel_refresher(refresh_gate_panel)


@bot.listen("on_ready")
async def _refresh_gate_on_ready():
    for gid in list(store.data.keys()):
        if gid.lstrip("-").isdigit():
            await refresh_gate_panel(int(gid))


@bot.tree.command(name="認証パネル設置", description="認証ゲートのパネルを設置する（管理者用）")
async def cmd_gate_panel(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    if not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get("gate_panel") or {}
    if old.get("channel_id") and old.get("message_id"):
        old_ch = interaction.guild.get_channel(int(old["channel_id"]))
        if old_ch is not None:
            try:
                old_msg = await old_ch.fetch_message(int(old["message_id"]))
                await old_msg.delete()
            except Exception:
                pass
    msg = await interaction.channel.send(
        embed=build_gate_embed(interaction.guild.id), view=GatePanelView())
    cfg["gate_panel"] = {"channel_id": interaction.channel.id,
                         "message_id": msg.id}
    save_config()
    await interaction.response.send_message(
        "📜 認証パネルを設置しました。", ephemeral=True)
