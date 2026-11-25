# 機能: チケット（種類セレクト式パネル＋Discord内で種類を自由に作れる設定）
import discord

from core import (bot, feature_cfg, is_privileged, refresh_panels,
                  register_feature, register_panel_refresher, save_config,
                  store)

register_feature(
    "tickets", "support", "チケット", "🎫",
    "種類を選んで問い合わせチケットを作成する。",
    settings=[
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "🎫 チケット"},
        {"key": "panel_text", "label": "パネルの説明文", "type": "text", "style": "long",
         "default": "お問い合わせの種類を選んでね。担当が対応します。"},
        {"key": "log_channel_id", "label": "ログ送信先チャンネル", "type": "channel",
         "default": None},
        {"key": "max_open", "label": "1人あたりの同時チケット数", "type": "number",
         "default": 1},
        {"key": "name_format", "label": "チャンネル名の形式", "type": "choice",
         "default": "user",
         "options": [("user", "ユーザー名"), ("number", "連番"),
                     ("type", "種類-ユーザー名"), ("name_type", "ユーザー名-種類")]},
    ],
    help_text=("管理者が /チケットパネル設置 でパネルを置き、種類の追加・担当ロール・"
               "作成先は /チケット設定 で、基本設定は /設定 → 🎫 サポート → チケット で行います。"),
)

DEFAULT_TYPES = ["問い合わせ", "相談", "その他"]
_MODAL_SELECT_OK = hasattr(discord.ui, "Label")


# ---------------------------------------------------------------- データ
def ticket_types(fcfg):
    types = fcfg.get("types")
    if not types:
        types = []
        for i, label in enumerate(DEFAULT_TYPES, 1):
            types.append({"key": f"t{i}", "label": label, "role_id": None,
                          "category_id": None, "subtypes": [],
                          "subtype_categories": {}})
        fcfg["types"] = types
        fcfg["seq"] = len(types)
    for t in types:
        t.setdefault("role_id", None)
        t.setdefault("category_id", None)
        t.setdefault("subtypes", [])
        t.setdefault("subtype_categories", {})
    return types


def get_type(fcfg, key):
    for t in ticket_types(fcfg):
        if t["key"] == key:
            return t
    return None


def _slug(text):
    out = []
    for ch in str(text).lower():
        out.append(ch if (ch.isalnum() or ch in "-_") else "-")
    s = "".join(out).strip("-")[:80]
    return s or "ticket"


def _channel_name(fcfg, ttype, user):
    fmt = fcfg.get("name_format") or "user"
    uname = _slug(getattr(user, "name", "user"))
    if fmt == "number":
        return f"ticket-{int(fcfg.get('counter') or 0):03d}"
    if fmt == "type":
        return f"{_slug(ttype['label'])}-{uname}"
    if fmt == "name_type":
        return f"{uname}-{_slug(ttype['label'])}"
    return f"ticket-{uname}"


def _open_count(guild, uid):
    prefix = f"ticket:{uid}:"
    return sum(1 for ch in getattr(guild, "text_channels", [])
               if (getattr(ch, "topic", None) or "").startswith(prefix))


def _resolve_category(guild, fcfg, ttype, subtype):
    cid = None
    if subtype:
        cid = (ttype.get("subtype_categories") or {}).get(subtype)
    if not cid:
        cid = ttype.get("category_id")
    if cid:
        for cat in getattr(guild, "categories", []):
            if cat.id == int(cid):
                return cat
    return None


async def _default_category(guild):
    for cat in getattr(guild, "categories", []):
        if cat.name == "🎫 チケット":
            return cat
    try:
        return await guild.create_category("🎫 チケット")
    except Exception:
        return None


async def _log(guild, fcfg, embed):
    cid = fcfg.get("log_channel_id")
    if not cid:
        return
    channel = guild.get_channel(int(cid))
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


# ---------------------------------------------------------------- 作成フロー
class TicketManageView(discord.ui.View):
    """チケット内の管理セレクト（常時有効）"""

    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_tickets:manage",
            placeholder="🎫 チケットの操作",
            options=[discord.SelectOption(
                label="🔒 このチケットをクローズ", value="close",
                description="チャンネルを削除します")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        channel = interaction.channel
        guild = interaction.guild
        if channel is None or guild is None:
            return
        topic = getattr(channel, "topic", None) or ""
        parts = topic.split(":")
        if len(parts) < 3 or parts[0] != "ticket":
            return await interaction.response.send_message(
                "⚠️ チケット情報が見つかりません。", ephemeral=True)
        owner_id = int(parts[1])
        fcfg = feature_cfg(guild.id, "tickets")
        ttype = get_type(fcfg, parts[2])
        user = interaction.user
        allowed = (user.id == owner_id or is_privileged(user)
                   or (ttype and ttype.get("role_id")
                       and any(r.id == int(ttype["role_id"])
                               for r in getattr(user, "roles", []))))
        if not allowed:
            return await interaction.response.send_message(
                "⚠️ クローズできるのは作成者・担当・管理者だけです。",
                ephemeral=True)
        embed = discord.Embed(title="🔒 チケットクローズ",
                              color=discord.Color.greyple())
        embed.add_field(name="作成者", value=f"<@{owner_id}>", inline=True)
        if ttype:
            embed.add_field(name="種類", value=ttype["label"], inline=True)
        embed.add_field(name="クローズした人", value=user.mention, inline=True)
        await _log(guild, fcfg, embed)
        try:
            await channel.delete(reason="チケットクローズ")
        except Exception:
            await interaction.response.send_message(
                "⚠️ チャンネルを削除できませんでした。", ephemeral=True)


async def _create_ticket(interaction, ttype, subtype, content):
    guild = interaction.guild
    user = interaction.user
    fcfg = feature_cfg(guild.id, "tickets")
    max_open = max(1, min(5, int(fcfg.get("max_open") or 1)))
    if _open_count(guild, user.id) >= max_open:
        return await interaction.followup.send(
            f"⚠️ 同時に開けるチケットは{max_open}件までです。", ephemeral=True)
    category = _resolve_category(guild, fcfg, ttype, subtype)
    if category is None:
        category = await _default_category(guild)
    if fcfg.get("name_format") == "number":
        fcfg["counter"] = int(fcfg.get("counter") or 0) + 1
        save_config()
    name = _channel_name(fcfg, ttype, user)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                          read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              manage_channels=True),
    }
    role = None
    if ttype.get("role_id"):
        role = guild.get_role(int(ttype["role_id"]))
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True)
    try:
        channel = await guild.create_text_channel(
            name=name, category=category, topic=f"ticket:{user.id}:{ttype['key']}",
            overwrites=overwrites, reason="チケット作成")
    except Exception:
        return await interaction.followup.send(
            "⚠️ チケットを作成できませんでした。BOTの権限を確認してね。",
            ephemeral=True)
    embed = discord.Embed(title=f"🎫 {ttype['label']}",
                          description=f"{user.mention} さん、担当の対応をお待ちください。",
                          color=discord.Color.blurple())
    if subtype:
        embed.add_field(name="📂 細かい種類", value=subtype, inline=False)
    embed.add_field(name="📝 内容", value=content[:1000], inline=False)
    try:
        await channel.send(embed=embed, view=TicketManageView())
    except Exception:
        pass
    log_embed = discord.Embed(title="🎫 チケット作成", color=discord.Color.green())
    log_embed.add_field(name="作成者", value=user.mention, inline=True)
    log_embed.add_field(name="種類", value=ttype["label"], inline=True)
    log_embed.add_field(name="チャンネル", value=channel.mention, inline=True)
    await _log(guild, fcfg, log_embed)
    await interaction.followup.send(
        f"🎫 チケットを作成しました: {channel.mention}", ephemeral=True)


class TicketContentModal(discord.ui.Modal):
    """内容モーダル（細かい種類がある場合はセレクトも一緒に出る）"""

    def __init__(self, ttype, with_subtype_select=True):
        super().__init__(title=f"🎫 {ttype['label']}"[:45])
        self.ttype = ttype
        self.subtype_select = None
        subtypes = ttype.get("subtypes") or []
        if subtypes and with_subtype_select and _MODAL_SELECT_OK:
            self.subtype_select = discord.ui.Select(
                placeholder="📂 細かい種類を選ぶ",
                options=[discord.SelectOption(label=s[:100], value=s[:100])
                         for s in subtypes[:25]])
            self.add_item(discord.ui.Label(text="📂 細かい種類",
                                           component=self.subtype_select))
        self.content = discord.ui.TextInput(
            label="内容", style=discord.TextStyle.paragraph,
            max_length=1000, required=True,
            placeholder="問い合わせ内容を書いてね")
        self.add_item(self.content)

    async def on_submit(self, interaction):
        subtype = None
        if self.subtype_select is not None and self.subtype_select.values:
            subtype = self.subtype_select.values[0]
        await interaction.response.defer(ephemeral=True)
        await _create_ticket(interaction, self.ttype, subtype,
                             str(self.content.value))


class SubtypePickView(discord.ui.View):
    """モーダル内セレクトが使えない環境向けの細かい種類ピック"""

    def __init__(self, ttype, owner_id):
        super().__init__(timeout=300)
        self.ttype = ttype
        self.owner_id = owner_id
        sel = discord.ui.Select(
            placeholder="📂 細かい種類を選ぶ",
            options=[discord.SelectOption(label=s[:100], value=s[:100])
                     for s in (ttype.get("subtypes") or [])[:25]])

        async def _pick(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の画面です。", ephemeral=True)
            await interaction.response.send_modal(
                _SubtypeContentModal(ttype, _sel.values[0]))

        sel.callback = _pick
        self.add_item(sel)


class _SubtypeContentModal(discord.ui.Modal):
    def __init__(self, ttype, subtype):
        super().__init__(title=f"🎫 {ttype['label']}"[:45])
        self.ttype = ttype
        self.subtype = subtype
        self.content = discord.ui.TextInput(
            label="内容", style=discord.TextStyle.paragraph,
            max_length=1000, required=True)
        self.add_item(self.content)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await _create_ticket(interaction, self.ttype, self.subtype,
                             str(self.content.value))


class TicketPanelView(discord.ui.View):
    """チケットパネル（常時設置・再起動後も動作）"""

    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        options = []
        if guild_id is not None:
            fcfg = feature_cfg(guild_id, "tickets")
            for t in ticket_types(fcfg):
                options.append(discord.SelectOption(
                    label=t["label"][:100], value=t["key"]))
        if not options:
            options = [discord.SelectOption(
                label="（種類がありません）", value="__none")]
        sel = discord.ui.Select(custom_id="mega_tickets:create",
                                placeholder="🎫 種類を選んでね",
                                options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        guild = interaction.guild
        if guild is None:
            return
        fcfg = feature_cfg(guild.id, "tickets")
        if not fcfg.get("enabled"):
            return await interaction.response.send_message(
                "⚠️ チケットは今は無効です。", ephemeral=True)
        value = None
        if interaction.data and interaction.data.get("values"):
            value = interaction.data["values"][0]
        ttype = get_type(fcfg, value) if value else None
        if ttype is None:
            return await interaction.response.send_message(
                "⚠️ 種類が見つかりません。", ephemeral=True)
        max_open = max(1, min(5, int(fcfg.get("max_open") or 1)))
        if _open_count(guild, interaction.user.id) >= max_open:
            return await interaction.response.send_message(
                f"⚠️ 同時に開けるチケットは{max_open}件までです。",
                ephemeral=True)
        subtypes = ttype.get("subtypes") or []
        if subtypes and not _MODAL_SELECT_OK:
            return await interaction.response.send_message(
                embed=discord.Embed(title="📂 細かい種類を選んでね",
                                    color=discord.Color.blurple()),
                view=SubtypePickView(ttype, interaction.user.id), ephemeral=True)
        await interaction.response.send_modal(TicketContentModal(ttype))


def build_ticket_embed(gid):
    fcfg = feature_cfg(gid, "tickets")
    return discord.Embed(
        title=fcfg.get("panel_title") or "🎫 チケット",
        description=fcfg.get("panel_text") or "",
        color=discord.Color.blurple())


async def refresh_ticket_panel(guild_id):
    loc = store.cfg(guild_id).get("tickets_panel") or {}
    if not loc.get("channel_id") or not loc.get("message_id"):
        return
    channel = bot.get_channel(int(loc["channel_id"]))
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(int(loc["message_id"]))
        await msg.edit(embed=build_ticket_embed(guild_id),
                       view=TicketPanelView(guild_id))
    except Exception:
        pass


register_panel_refresher(refresh_ticket_panel)


@bot.listen("on_ready")
async def _refresh_tickets_on_ready():
    for gid in list(store.data.keys()):
        if gid.lstrip("-").isdigit():
            await refresh_ticket_panel(int(gid))


@bot.tree.command(name="チケットパネル設置", description="チケットパネルを設置する（管理者用）")
async def cmd_ticket_panel(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    if not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get("tickets_panel") or {}
    if old.get("channel_id") and old.get("message_id"):
        old_ch = interaction.guild.get_channel(int(old["channel_id"]))
        if old_ch is not None:
            try:
                old_msg = await old_ch.fetch_message(int(old["message_id"]))
                await old_msg.delete()
            except Exception:
                pass
    msg = await interaction.channel.send(
        embed=build_ticket_embed(interaction.guild.id),
        view=TicketPanelView(interaction.guild.id))
    cfg["tickets_panel"] = {"channel_id": interaction.channel.id,
                            "message_id": msg.id}
    save_config()
    await interaction.response.send_message(
        "🎫 チケットパネルを設置しました。", ephemeral=True)


# ---------------------------------------------------------------- 種類の設定
class _TypeLabelModal(discord.ui.Modal):
    def __init__(self, view, ttype=None):
        super().__init__(title="🎫 種類の名前"[:45])
        self.view = view
        self.ttype = ttype
        self.label_input = discord.ui.TextInput(
            label="種類の名前", max_length=50,
            default=ttype["label"] if ttype else None)
        self.add_item(self.label_input)

    async def on_submit(self, interaction):
        fcfg = feature_cfg(self.view.gid, "tickets")
        label = str(self.label_input.value).strip()[:50]
        if not label:
            return await interaction.response.send_message(
                "⚠️ 名前を入れてね。", ephemeral=True)
        if self.ttype is None:
            fcfg["seq"] = int(fcfg.get("seq") or 0) + 1
            t = {"key": f"t{fcfg['seq']}", "label": label, "role_id": None,
                 "category_id": None, "subtypes": [], "subtype_categories": {}}
            ticket_types(fcfg).append(t)
            self.view.type_key = t["key"]
        else:
            self.ttype["label"] = label
        save_config()
        await refresh_panels(self.view.gid)
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class _SubtypesModal(discord.ui.Modal):
    def __init__(self, view, ttype):
        super().__init__(title="📂 細かい種類（1行に1つ）"[:45])
        self.view = view
        self.ttype = ttype
        self.text = discord.ui.TextInput(
            label="細かい種類", style=discord.TextStyle.paragraph,
            max_length=1000, required=False,
            default="\n".join(ttype.get("subtypes") or []))
        self.add_item(self.text)

    async def on_submit(self, interaction):
        lines = [ln.strip()[:100] for ln in str(self.text.value).splitlines()
                 if ln.strip()][:25]
        self.ttype["subtypes"] = lines
        mapping = self.ttype.get("subtype_categories") or {}
        self.ttype["subtype_categories"] = {
            k: v for k, v in mapping.items() if k in lines}
        save_config()
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class TicketSettingsView(discord.ui.View):
    """/チケット設定: 種類の追加・編集をセレクトメニューで行う"""

    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=600)
        self.gid = guild_id
        self.owner_id = owner_id
        self.type_key = None
        self.subtype_for = None   # 作成場所を設定中の細かい種類
        self._build()

    def fcfg(self):
        return feature_cfg(self.gid, "tickets")

    def ttype(self):
        return get_type(self.fcfg(), self.type_key) if self.type_key else None

    async def _gate(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ これは他の人の設定画面です。", ephemeral=True)
            return False
        return True

    def embed(self):
        fcfg = self.fcfg()
        types = ticket_types(fcfg)
        embed = discord.Embed(title="🎫 チケット設定", color=discord.Color.blurple())
        t = self.ttype()
        if t is None:
            lines = [f"・{x['label']}" for x in types]
            embed.description = ("種類を選ぶと編集できます。\n\n"
                                 + ("\n".join(lines) if lines else "種類がありません"))
            return embed
        embed.description = f"**{t['label']}** を編集中"
        role = f"<@&{t['role_id']}>" if t.get("role_id") else "未設定"
        embed.add_field(name="担当ロール", value=role, inline=True)
        cat = "未設定"
        if t.get("category_id"):
            cat = f"<#{t['category_id']}>（カテゴリ）"
        embed.add_field(name="作成先カテゴリ", value=cat, inline=True)
        subs = t.get("subtypes") or []
        embed.add_field(name="細かい種類",
                        value="、".join(subs) if subs else "なし", inline=False)
        if self.subtype_for:
            embed.add_field(name="作成場所を設定中",
                            value=self.subtype_for, inline=False)
        return embed

    async def _rerender(self, interaction):
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def _build(self):
        self.clear_items()
        fcfg = self.fcfg()
        types = ticket_types(fcfg)
        options = [discord.SelectOption(
            label=t["label"][:100], value=t["key"],
            default=(t["key"] == self.type_key)) for t in types]
        options.append(discord.SelectOption(label="➕ 種類を追加", value="__add"))
        sel = discord.ui.Select(placeholder="🎫 種類を選ぶ / 追加する",
                                options=options, row=0)

        async def _type(interaction, _sel=sel):
            if not await self._gate(interaction):
                return
            v = _sel.values[0]
            if v == "__add":
                return await interaction.response.send_modal(
                    _TypeLabelModal(self))
            self.type_key = v
            self.subtype_for = None
            await self._rerender(interaction)

        sel.callback = _type
        self.add_item(sel)
        t = self.ttype()
        if t is None:
            return
        if self.subtype_for is not None:
            self._build_subtype_place(t)
            return
        actions = [
            discord.SelectOption(label="✏️ 名前を変更", value="rename"),
            discord.SelectOption(label="📂 細かい種類を編集", value="subtypes"),
            discord.SelectOption(label="📍 細かい種類の作成場所", value="subplace"),
            discord.SelectOption(label="📍 作成先カテゴリを未設定に戻す",
                                 value="clear_cat"),
            discord.SelectOption(label="🗑 この種類を削除", value="delete"),
        ]
        asel = discord.ui.Select(placeholder="⚙️ 操作を選ぶ", options=actions, row=1)

        async def _action(interaction, _sel=asel):
            if not await self._gate(interaction):
                return
            v = _sel.values[0]
            tt = self.ttype()
            if tt is None:
                return
            if v == "rename":
                return await interaction.response.send_modal(
                    _TypeLabelModal(self, tt))
            if v == "subtypes":
                return await interaction.response.send_modal(
                    _SubtypesModal(self, tt))
            if v == "subplace":
                if not (tt.get("subtypes") or []):
                    return await interaction.response.send_message(
                        "⚠️ 先に細かい種類を追加してね。", ephemeral=True)
                self.subtype_for = (tt["subtypes"] or [None])[0]
                return await self._rerender(interaction)
            if v == "clear_cat":
                tt["category_id"] = None
                save_config()
                return await self._rerender(interaction)
            if v == "delete":
                types_now = ticket_types(self.fcfg())
                if len(types_now) <= 1:
                    return await interaction.response.send_message(
                        "⚠️ 種類は最低1つ必要です。", ephemeral=True)
                self.fcfg()["types"] = [x for x in types_now
                                        if x["key"] != tt["key"]]
                self.type_key = None
                save_config()
                await refresh_panels(self.gid)
                return await self._rerender(interaction)

        asel.callback = _action
        self.add_item(asel)
        rsel = discord.ui.RoleSelect(placeholder="👥 担当ロールを選ぶ", row=2)

        async def _role(interaction, _sel=rsel):
            if not await self._gate(interaction):
                return
            tt = self.ttype()
            if tt is None:
                return
            v = _sel.values[0]
            tt["role_id"] = int(getattr(v, "id", v))
            save_config()
            await self._rerender(interaction)

        rsel.callback = _role
        self.add_item(rsel)
        csel = discord.ui.ChannelSelect(
            placeholder="📍 作成先カテゴリを選ぶ",
            channel_types=[discord.ChannelType.category], row=3)

        async def _cat(interaction, _sel=csel):
            if not await self._gate(interaction):
                return
            tt = self.ttype()
            if tt is None:
                return
            v = _sel.values[0]
            tt["category_id"] = int(getattr(v, "id", v))
            save_config()
            await self._rerender(interaction)

        csel.callback = _cat
        self.add_item(csel)

    def _build_subtype_place(self, t):
        subs = t.get("subtypes") or []
        sel = discord.ui.Select(
            placeholder="📂 作成場所を設定する細かい種類",
            options=[discord.SelectOption(
                label=s[:100], value=s[:100], default=(s == self.subtype_for))
                for s in subs[:25]], row=1)

        async def _sub(interaction, _sel=sel):
            if not await self._gate(interaction):
                return
            self.subtype_for = _sel.values[0]
            await self._rerender(interaction)

        sel.callback = _sub
        self.add_item(sel)
        csel = discord.ui.ChannelSelect(
            placeholder="📍 この細かい種類の作成先カテゴリ",
            channel_types=[discord.ChannelType.category], row=2)

        async def _cat(interaction, _sel=csel):
            if not await self._gate(interaction):
                return
            v = _sel.values[0]
            t.setdefault("subtype_categories", {})[self.subtype_for] = \
                int(getattr(v, "id", v))
            save_config()
            await self._rerender(interaction)

        csel.callback = _cat
        self.add_item(csel)
        back = discord.ui.Select(
            placeholder="⬅ 戻る",
            options=[discord.SelectOption(label="⬅ 種類の編集に戻る", value="back"),
                     discord.SelectOption(label="📍 この細かい種類の作成場所を外す",
                                          value="clear")], row=3)

        async def _back(interaction, _sel=back):
            if not await self._gate(interaction):
                return
            if _sel.values[0] == "clear" and self.subtype_for:
                (t.get("subtype_categories") or {}).pop(self.subtype_for, None)
                save_config()
            self.subtype_for = None
            await self._rerender(interaction)

        back.callback = _back
        self.add_item(back)


@bot.tree.command(name="チケット設定", description="チケットの種類などを設定する（管理者用）")
async def cmd_ticket_settings(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    if not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設定は管理者だけが使えます。", ephemeral=True)
    view = TicketSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)
