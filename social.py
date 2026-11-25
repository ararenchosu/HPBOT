# 機能群: 入退室まわり・交流（自己紹介/自動ロール/ウェルカムDM/ロールパネル/通報/提案/質問箱）
import discord

from core import (bot, feature_cfg, feature_enabled, is_privileged,
                  refresh_panels, register_feature, register_panel_refresher,
                  save_config, sel_values, store,
                  command_group)

CAT = "enter"

_GK = command_group("social", "交流", "交流・パネル機能")
_GS = command_group("support", "サポート", "サポート機能")


async def _install_panel(interaction, loc_key, embed, view):
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get(loc_key) or {}
    if old.get("channel_id") and old.get("message_id"):
        old_ch = interaction.guild.get_channel(int(old["channel_id"]))
        if old_ch is not None:
            try:
                old_msg = await old_ch.fetch_message(int(old["message_id"]))
                await old_msg.delete()
            except Exception:
                pass
    msg = await interaction.channel.send(embed=embed, view=view)
    cfg[loc_key] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    save_config()
    return msg


def _make_refresher(loc_key, embed_fn, view_fn):
    async def _refresh(guild_id):
        loc = store.cfg(guild_id).get(loc_key) or {}
        if not loc.get("channel_id") or not loc.get("message_id"):
            return
        channel = bot.get_channel(int(loc["channel_id"]))
        if channel is None:
            return
        try:
            msg = await channel.fetch_message(int(loc["message_id"]))
            await msg.edit(embed=embed_fn(guild_id), view=view_fn(guild_id))
        except Exception:
            pass
    return _refresh


def _admin_or_deny(interaction):
    return (interaction.guild is not None
            and is_privileged(interaction.user))


# ---------------------------------------------------------------- 参加時自動ロール / ウェルカムDM
register_feature("autorole", CAT, "参加時自動ロール", "🎽",
                 "参加したメンバーに自動でロールを付ける。",
                 settings=[{"key": "role_id", "label": "付けるロール",
                            "type": "role", "default": None}])
register_feature(
    "welcome_dm", CAT, "ウェルカムDM", "💌",
    "参加したメンバーにDMで挨拶を送る。",
    settings=[{"key": "text", "label": "DMの文面（{server}=サーバー名 {user}=名前）",
               "type": "text", "style": "long",
               "default": "{server} へようこそ、{user} さん！楽しんでいってね。"}])


@bot.listen("on_member_join")
async def _join_extras(member):
    gid = member.guild.id
    try:
        if feature_enabled(gid, "autorole"):
            rid = feature_cfg(gid, "autorole").get("role_id")
            if rid:
                role = member.guild.get_role(int(rid))
                if role is not None:
                    await member.add_roles(role)
    except Exception:
        pass
    try:
        if feature_enabled(gid, "welcome_dm"):
            text = feature_cfg(gid, "welcome_dm").get("text") or ""
            text = text.replace("{server}", member.guild.name).replace(
                "{user}", member.display_name)
            if text:
                await member.send(text)
    except Exception:
        pass


# ---------------------------------------------------------------- 自己紹介
register_feature(
    "intro", CAT, "自己紹介", "📝",
    "自己紹介パネルから投稿できる。",
    settings=[
        {"key": "channel_id", "label": "投稿先チャンネル", "type": "channel",
         "default": None},
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "📝 自己紹介"},
        {"key": "panel_text", "label": "パネルの説明文", "type": "text",
         "style": "long", "default": "自己紹介を書いてみんなに挨拶しよう！"},
    ],
    help_text="/自己紹介パネル設置 で設置。項目は /自己紹介設定 で追加できます"
              "（最大5つ）。")


def _intro_fields(fcfg):
    fields = fcfg.get("fields")
    if fields is None:
        fields = ["名前", "好きなゲーム", "ひとこと"]
        fcfg["fields"] = fields
    return fields


def build_intro_embed(gid):
    cfg = feature_cfg(gid, "intro")
    return discord.Embed(title=cfg.get("panel_title") or "📝 自己紹介",
                         description=cfg.get("panel_text") or "",
                         color=discord.Color.green())


class IntroModal(discord.ui.Modal):
    def __init__(self, gid):
        super().__init__(title="📝 自己紹介")
        self.gid = gid
        self.inputs = []
        for label in _intro_fields(feature_cfg(gid, "intro"))[:5]:
            ti = discord.ui.TextInput(label=label[:45], max_length=300,
                                      required=False)
            self.inputs.append((label, ti))
            self.add_item(ti)

    async def on_submit(self, interaction):
        cfg = feature_cfg(self.gid, "intro")
        cid = cfg.get("channel_id")
        channel = interaction.guild.get_channel(int(cid)) if cid else None
        if channel is None:
            return await interaction.response.send_message(
                "⚠️ 投稿先チャンネルが未設定です。", ephemeral=True)
        embed = discord.Embed(title="📝 自己紹介",
                              color=discord.Color.green())
        embed.set_author(name=interaction.user.display_name,
                         icon_url=interaction.user.display_avatar.url
                         if interaction.user.display_avatar else None)
        for label, ti in self.inputs:
            if ti.value:
                embed.add_field(name=label, value=ti.value, inline=False)
        embed.set_footer(text=f"投稿者: {interaction.user.mention}")
        await channel.send(embed=embed)
        await interaction.response.send_message(
            "📝 自己紹介を投稿しました！", ephemeral=True)


class IntroPanelView(discord.ui.View):
    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_intro:open", placeholder="📝 自己紹介する",
            options=[discord.SelectOption(
                label="📝 自己紹介を書く", value="open")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.guild is None:
            return
        if not feature_enabled(interaction.guild.id, "intro"):
            return await interaction.response.send_message(
                "⚠️ 自己紹介は無効です。", ephemeral=True)
        await interaction.response.send_modal(
            IntroModal(interaction.guild.id))


register_panel_refresher(_make_refresher(
    "intro_panel", build_intro_embed, lambda gid: IntroPanelView(gid)))


@_GK.command(name="自己紹介パネル設置", description="自己紹介パネルを設置する（管理者用）")
async def cmd_intro_panel(interaction):
    if not _admin_or_deny(interaction):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    await _install_panel(interaction, "intro_panel",
                         build_intro_embed(interaction.guild.id),
                         IntroPanelView(interaction.guild.id))
    await interaction.response.send_message(
        "📝 自己紹介パネルを設置しました。", ephemeral=True)


class _FieldModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="📝 項目を追加")
        self.view = view
        self.name = discord.ui.TextInput(label="項目名", max_length=30)
        self.add_item(self.name)

    async def on_submit(self, interaction):
        fields = _intro_fields(feature_cfg(self.view.gid, "intro"))
        label = str(self.name.value).strip()
        if label and label not in fields and len(fields) < 5:
            fields.append(label)
            save_config()
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class IntroSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self._build()

    def embed(self):
        fields = _intro_fields(feature_cfg(self.gid, "intro"))
        return discord.Embed(
            title="📝 自己紹介の項目設定", color=discord.Color.green(),
            description="\n".join(f"・{f}" for f in fields) or "項目なし")

    def _build(self):
        self.clear_items()
        fields = _intro_fields(feature_cfg(self.gid, "intro"))
        options = [discord.SelectOption(label="➕ 項目を追加", value="__add")]
        options += [discord.SelectOption(label=f"🗑 {f}", value=f)
                    for f in fields]
        sel = discord.ui.Select(placeholder="⚙️ 追加 / 削除", options=options)

        async def _cb(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "__add":
                if len(fields) >= 5:
                    return await interaction.response.send_message(
                        "⚠️ 項目は最大5つです。", ephemeral=True)
                return await interaction.response.send_modal(
                    _FieldModal(self))
            fields.remove(v)
            save_config()
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        sel.callback = _cb
        self.add_item(sel)


@_GK.command(name="自己紹介設定", description="自己紹介の項目を設定する（管理者用）")
async def cmd_intro_settings(interaction):
    if not _admin_or_deny(interaction):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    view = IntroSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- ロール選択パネル
register_feature(
    "rolepanel", "auto", "ロール選択パネル", "🎭",
    "セレクトでロールを付け外しできるパネル。",
    settings=[
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "🎭 ロール選択"},
        {"key": "panel_text", "label": "パネルの説明文", "type": "text",
         "style": "long",
         "default": "欲しいロールを選んでね。もう一度選ぶと外れます。"},
    ],
    help_text="/ロールパネル設置 で設置。グループとロールは "
              "/ロールパネル設定 で作ります（グループごとに単一/複数）。")


def _role_groups(fcfg):
    groups = fcfg.get("groups")
    if groups is None:
        groups = []
        fcfg["groups"] = groups
        fcfg["seq"] = 0
    return groups


def _group(fcfg, key):
    for g in _role_groups(fcfg):
        if g["key"] == key:
            return g
    return None


def build_role_embed(gid):
    cfg = feature_cfg(gid, "rolepanel")
    embed = discord.Embed(title=cfg.get("panel_title") or "🎭 ロール選択",
                          description=cfg.get("panel_text") or "",
                          color=discord.Color.purple())
    guild = bot.get_guild(gid)
    for g in _role_groups(cfg):
        names = []
        for rid in g.get("roles", []):
            role = guild.get_role(int(rid)) if guild else None
            names.append(role.name if role else str(rid))
        embed.add_field(
            name=f"{g['label']}（{'どれか1つ' if g.get('single') else '複数OK'}）",
            value="、".join(names) or "（ロールなし）", inline=False)
    return embed


class RolePanelView(discord.ui.View):
    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        if guild_id is None:
            sel = discord.ui.Select(
                custom_id="mega_roles:pick", placeholder="🎭 ロール選択",
                options=[discord.SelectOption(label="ロール", value="__x")])
            sel.callback = self._cb
            self.add_item(sel)
            return
        cfg = feature_cfg(guild_id, "rolepanel")
        guild = bot.get_guild(guild_id)
        for g in _role_groups(cfg)[:5]:
            options = []
            for rid in g.get("roles", [])[:24]:
                role = guild.get_role(int(rid)) if guild else None
                options.append(discord.SelectOption(
                    label=(role.name if role else str(rid))[:100],
                    value=f"{g['key']}:{rid}"))
            options.append(discord.SelectOption(
                label="🧹 このグループのロールを全部外す",
                value=f"{g['key']}:__clear"))
            sel = discord.ui.Select(
                custom_id="mega_roles:pick",
                placeholder=f"🎭 {g['label']}"[:100],
                min_values=1,
                max_values=1 if g.get("single") else min(len(options), 25),
                options=options)
            sel.callback = self._cb
            self.add_item(sel)

    async def _cb(self, interaction):
        guild = interaction.guild
        if guild is None:
            return
        if not feature_enabled(guild.id, "rolepanel"):
            return await interaction.response.send_message(
                "⚠️ ロールパネルは無効です。", ephemeral=True)
        cfg = feature_cfg(guild.id, "rolepanel")
        values = sel_values(interaction)
        member = interaction.user
        held = {r.id for r in getattr(member, "roles", [])}
        notes = []
        by_group = {}
        for v in values:
            if ":" not in v:
                continue
            gkey, rid = v.split(":", 1)
            by_group.setdefault(gkey, []).append(rid)
        for gkey, rids in by_group.items():
            g = _group(cfg, gkey)
            if g is None:
                continue
            group_roles = [int(r) for r in g.get("roles", [])]
            if "__clear" in rids:
                for rid in group_roles:
                    if rid in held:
                        role = guild.get_role(rid)
                        if role:
                            try:
                                await member.remove_roles(role)
                                notes.append(f"➖ {role.name}")
                            except Exception:
                                pass
                continue
            chosen = [int(r) for r in rids]
            if g.get("single"):
                for rid in group_roles:
                    if rid != chosen[0] and rid in held:
                        role = guild.get_role(rid)
                        if role:
                            try:
                                await member.remove_roles(role)
                            except Exception:
                                pass
                rid = chosen[0]
                role = guild.get_role(rid)
                if role and rid not in held:
                    try:
                        await member.add_roles(role)
                        notes.append(f"➕ {role.name}")
                    except Exception:
                        notes.append(f"⚠️ {role.name} は付けられなかった")
                elif role:
                    try:
                        await member.remove_roles(role)
                        notes.append(f"➖ {role.name}")
                    except Exception:
                        pass
            else:
                for rid in chosen:
                    role = guild.get_role(rid)
                    if role is None:
                        continue
                    try:
                        if rid in held:
                            await member.remove_roles(role)
                            notes.append(f"➖ {role.name}")
                        else:
                            await member.add_roles(role)
                            notes.append(f"➕ {role.name}")
                    except Exception:
                        notes.append(f"⚠️ {role.name} は変更できなかった")
        await interaction.response.send_message(
            "\n".join(notes) if notes else "変更はありませんでした。",
            ephemeral=True)


register_panel_refresher(_make_refresher(
    "role_panel", build_role_embed, lambda gid: RolePanelView(gid)))


@_GK.command(name="ロールパネル設置", description="ロール選択パネルを設置する（管理者用）")
async def cmd_role_panel(interaction):
    if not _admin_or_deny(interaction):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    await _install_panel(interaction, "role_panel",
                         build_role_embed(interaction.guild.id),
                         RolePanelView(interaction.guild.id))
    await interaction.response.send_message(
        "🎭 ロールパネルを設置しました。", ephemeral=True)


class _GroupModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="🎭 グループを追加")
        self.view = view
        self.name = discord.ui.TextInput(label="グループ名", max_length=30)
        self.add_item(self.name)

    async def on_submit(self, interaction):
        cfg = feature_cfg(self.view.gid, "rolepanel")
        groups = _role_groups(cfg)
        if len(groups) >= 5:
            return await interaction.response.send_message(
                "⚠️ グループは最大5つです。", ephemeral=True)
        cfg["seq"] = int(cfg.get("seq") or 0) + 1
        g = {"key": f"g{cfg['seq']}", "label": str(self.name.value).strip()[:30],
             "single": True, "roles": []}
        groups.append(g)
        save_config()
        self.view.group_key = g["key"]
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class RolePanelSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self.group_key = None
        self._build()

    def cfg(self):
        return feature_cfg(self.gid, "rolepanel")

    def group(self):
        return _group(self.cfg(), self.group_key) if self.group_key else None

    def embed(self):
        embed = discord.Embed(title="🎭 ロールパネル設定",
                              color=discord.Color.purple())
        g = self.group()
        if g is None:
            groups = _role_groups(self.cfg())
            embed.description = ("グループを選んでね。\n"
                                 + "\n".join(f"・{x['label']}" for x in groups)
                                 if groups else "グループがありません。")
            return embed
        guild = bot.get_guild(self.gid)
        names = []
        for rid in g.get("roles", []):
            role = guild.get_role(int(rid)) if guild else None
            names.append(role.name if role else str(rid))
        embed.description = f"**{g['label']}** を編集中"
        embed.add_field(name="方式", value="どれか1つ" if g.get("single")
                        else "複数OK", inline=True)
        embed.add_field(name="ロール", value="、".join(names) or "なし",
                        inline=False)
        return embed

    def _build(self):
        self.clear_items()
        groups = _role_groups(self.cfg())
        options = [discord.SelectOption(label=g["label"][:100], value=g["key"],
                                        default=g["key"] == self.group_key)
                   for g in groups]
        options.append(discord.SelectOption(label="➕ グループを追加",
                                            value="__add"))
        sel = discord.ui.Select(placeholder="🎭 グループを選ぶ", options=options,
                                row=0)

        async def _pick(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "__add":
                return await interaction.response.send_modal(
                    _GroupModal(self))
            self.group_key = v
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        sel.callback = _pick
        self.add_item(sel)
        g = self.group()
        if g is None:
            return
        actions = [
            discord.SelectOption(
                label="🔀 方式を切り替え（単一/複数）", value="toggle_single"),
            discord.SelectOption(label="🗑 グループを削除", value="delete"),
        ]
        asel = discord.ui.Select(placeholder="⚙️ 操作", options=actions, row=1)

        async def _act(interaction, _sel=asel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "toggle_single":
                g["single"] = not g.get("single")
            elif v == "delete":
                self.cfg()["groups"] = [x for x in _role_groups(self.cfg())
                                        if x["key"] != g["key"]]
                self.group_key = None
            save_config()
            await refresh_panels(self.gid)
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        asel.callback = _act
        self.add_item(asel)
        rsel = discord.ui.RoleSelect(placeholder="➕ ロールを追加", row=2)

        async def _add(interaction, _sel=rsel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            rid = int(getattr(v, "id", v))
            if rid not in [int(r) for r in g.get("roles", [])]:
                g.setdefault("roles", []).append(rid)
                save_config()
                await refresh_panels(self.gid)
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        rsel.callback = _add
        self.add_item(rsel)
        if g.get("roles"):
            dopts = []
            guild = bot.get_guild(self.gid)
            for rid in g["roles"][:25]:
                role = guild.get_role(int(rid)) if guild else None
                dopts.append(discord.SelectOption(
                    label=f"🗑 {(role.name if role else str(rid))}"[:100],
                    value=str(rid)))
            dsel = discord.ui.Select(placeholder="🗑 ロールを外す",
                                     options=dopts, row=3)

            async def _del(interaction, _sel=dsel):
                if interaction.user.id != self.owner_id:
                    return
                g["roles"] = [r for r in g["roles"]
                              if str(r) != _sel.values[0]]
                save_config()
                await refresh_panels(self.gid)
                self._build()
                await interaction.response.edit_message(
                    embed=self.embed(), view=self)

            dsel.callback = _del
            self.add_item(dsel)


@_GK.command(name="ロールパネル設定", description="ロールパネルのグループを設定する（管理者用）")
async def cmd_role_settings(interaction):
    if not _admin_or_deny(interaction):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    view = RolePanelSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- 通報 / 提案 / 質問箱
def _simple_panel_feature(key, name, emoji, desc, channel_label, post_title,
                          modal_fields, loc_key, custom_id, color):
    register_feature(
        key, "support", name, emoji, desc,
        settings=[
            {"key": "channel_id", "label": channel_label, "type": "channel",
             "default": None},
            {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
             "default": f"{emoji} {name}"},
            {"key": "panel_text", "label": "パネルの説明文", "type": "text",
             "style": "long", "default": desc},
        ],
        help_text=f"/{name}パネル設置 で設置します。")

    def build_embed(gid):
        cfg = feature_cfg(gid, key)
        return discord.Embed(title=cfg.get("panel_title") or name,
                             description=cfg.get("panel_text") or "",
                             color=color)

    class _Modal(discord.ui.Modal):
        def __init__(self, gid):
            super().__init__(title=f"{emoji} {name}"[:45])
            self.gid = gid
            self.inputs = []
            for label, style in modal_fields:
                ti = discord.ui.TextInput(
                    label=label[:45], max_length=1000,
                    style=discord.TextStyle.paragraph
                    if style == "long" else discord.TextStyle.short)
                self.inputs.append((label, ti))
                self.add_item(ti)

        async def on_submit(self, interaction):
            cfg = feature_cfg(self.gid, key)
            cid = cfg.get("channel_id")
            channel = interaction.guild.get_channel(int(cid)) if cid else None
            if channel is None:
                return await interaction.response.send_message(
                    "⚠️ 送信先チャンネルが未設定です。", ephemeral=True)
            embed = discord.Embed(title=post_title, color=color)
            for label, ti in self.inputs:
                if ti.value:
                    embed.add_field(name=label, value=ti.value, inline=False)
            if key != "question":
                embed.set_footer(
                    text=f"送信者: {interaction.user.display_name} "
                         f"({interaction.user.id})")
            msg = await channel.send(embed=embed)
            if key == "suggestion":
                try:
                    await msg.add_reaction("👍")
                    await msg.add_reaction("👎")
                except Exception:
                    pass
            await interaction.response.send_message(
                "✅ 送信しました。ありがとうございます！", ephemeral=True)

    class _Panel(discord.ui.View):
        def __init__(self, guild_id=None):
            super().__init__(timeout=None)
            sel = discord.ui.Select(
                custom_id=custom_id, placeholder=f"{emoji} {name}",
                options=[discord.SelectOption(
                    label=f"{emoji} {name}する", value="open")])
            sel.callback = self._cb
            self.add_item(sel)

        async def _cb(self, interaction):
            if interaction.guild is None:
                return
            if not feature_enabled(interaction.guild.id, key):
                return await interaction.response.send_message(
                    f"⚠️ {name}は無効です。", ephemeral=True)
            await interaction.response.send_modal(
                _Modal(interaction.guild.id))

    register_panel_refresher(_make_refresher(
        loc_key, build_embed, lambda gid: _Panel(gid)))

    @_GS.command(name=f"{name}パネル設置",
                      description=f"{name}パネルを設置する（管理者用）")
    async def _cmd(interaction):
        if not _admin_or_deny(interaction):
            return await interaction.response.send_message(
                "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
        await _install_panel(interaction, loc_key,
                             build_embed(interaction.guild.id),
                             _Panel(interaction.guild.id))
        await interaction.response.send_message(
            f"{emoji} {name}パネルを設置しました。", ephemeral=True)

    return _Panel


ReportPanelView = _simple_panel_feature(
    "report", "通報", "🚨", "困ったことがあれば管理者へ通報できます。",
    "通報の送信先チャンネル", "🚨 通報",
    [("対象（ユーザー名など）", "short"), ("内容", "long")],
    "report_panel", "mega_report:open", discord.Color.red())
SuggestionPanelView = _simple_panel_feature(
    "suggestion", "提案", "💡", "サーバーへの提案を投稿できます。",
    "提案の投稿先チャンネル", "💡 提案",
    [("提案", "long")],
    "suggestion_panel", "mega_suggestion:open", discord.Color.yellow())
QuestionPanelView = _simple_panel_feature(
    "question", "質問箱", "❓", "匿名で質問できます。",
    "質問の投稿先チャンネル", "❓ 匿名質問",
    [("質問", "long")],
    "question_panel", "mega_question:open", discord.Color.blurple())
