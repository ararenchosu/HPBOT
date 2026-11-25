# 設定エレベーター（/設定）・常時設置パネル・ヘルプ（/ヘルプ）
# 階（フロア）にカテゴリを割り当てる方式。階を選ぶと乗車アニメーションが流れる。
# 画面遷移はすべてセレクトメニュー。ボタンは使わない。
import asyncio

import discord

from core import (CATEGORIES, FEATURES, bot, category_of, feature_cfg,
                  features_in, floors_map, is_privileged, refresh_panels,
                  register_feature, register_panel_refresher, save_config,
                  save_floors_map, store, visible_floors, command_group)

RIDE_STEP = 1.0  # 乗車アニメーションの1段階（25%）あたりの秒数

ON_OFF = [("on", "🟢 有効にする"), ("off", "⚪ 無効にする")]


register_feature(
    "elevator", "system", "エレベーター設定", "🛗",
    "エレベーターの各階に、このサーバーのカテゴリを割り当てる。階は無限に増やせる。",
    settings=[],
    help_text=("階を追加してサーバーのカテゴリを割り当てると、エレベーターでその階へ行けるようになります。"
               "割り当てのない階はパネルに表示されません（1階だけは常に表示）。"),
)


# ---------------------------------------------------------------- ギルド解決
_guilds = {}


def _guild(gid):
    g = _guilds.get(gid)
    if g is None:
        g = bot.get_guild(gid)
        if g is not None:
            _guilds[gid] = g
    return g


def _discord_category(gid, cid):
    """サーバー内のカテゴリ（チャンネルカテゴリ）をIDから引く"""
    if not cid:
        return None
    g = _guild(gid)
    if g is None:
        return None
    for c in getattr(g, "categories", []) or []:
        if c.id == cid:
            return c
    return None


def _floor_cat_names(gid, ids):
    names = []
    for cid in (ids or []):
        cat = _discord_category(gid, cid)
        if cat is not None:
            names.append(cat.name)
    return names


def _floor_label(gid, ids):
    """階の表示名: '📁 A / 📁 B'（なければ None）"""
    names = _floor_cat_names(gid, ids)
    if not names:
        return None
    return " / ".join(f"📁 {nm}" for nm in names)


def _fmt_value(item, value):
    t = item["type"]
    if t == "toggle":
        return "🟢 ON" if value else "⚪ OFF"
    if t == "channel":
        return f"<#{value}>" if value else "未設定"
    if t == "role":
        return f"<@&{value}>" if value else "未設定"
    if t == "choice":
        for v, label in item.get("options", []):
            if v == value:
                return label
        return str(value) if value is not None else "未設定"
    if value is None or value == "":
        return "未設定"
    s = str(value)
    return s if len(s) <= 80 else s[:80] + "…"


def _floor_lines(gid):
    m = floors_map(gid)
    lines = []
    for n in visible_floors(gid):
        label = _floor_label(gid, m.get(n))
        lines.append(f"**{n}階** — {label}" if label
                     else f"**{n}階** — 未設定")
    return lines


def _ride_embed(floor, pct, arrived=False):
    filled = int(pct / 10 + 0.5)
    bar = "█" * filled + "░" * (10 - filled)
    if arrived:
        desc = f"**{floor}階** に到着しました!!\n{bar} 100%"
    else:
        desc = f"**{floor}階** を選択しました\n移動中…\n{bar} {pct}%"
    return discord.Embed(title="🛗 エレベーター", description=desc,
                         color=discord.Color.blurple())


class ItemModal(discord.ui.Modal):
    """text / number 型の設定値を入力するモーダル"""

    def __init__(self, view, item, current=None):
        super().__init__(title=f"✏️ {item['label']}"[:45])
        self.view = view
        self.item = item
        cur = current if current is not None else view.cfg().get(item["key"])
        self.text = discord.ui.TextInput(
            label=item["label"][:45],
            style=(discord.TextStyle.paragraph if item.get("style") == "long"
                   else discord.TextStyle.short),
            max_length=20 if item["type"] == "number" else 1000,
            placeholder="数字で入力" if item["type"] == "number" else None,
            default=str(cur)[:1000] if cur is not None else None)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        raw = str(self.text.value).strip()
        if self.item["type"] == "number":
            try:
                value = int(raw.replace(",", ""))
            except ValueError:
                return await interaction.response.send_message(
                    "⚠️ 数字で入力してね。", ephemeral=True)
        else:
            value = raw
        self.view.cfg()[self.item["key"]] = value
        save_config()
        await refresh_panels(self.view.gid)
        self.view.edit = None
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class ElevatorView(discord.ui.View):
    """設定エレベーター: 階 → 機能 → 項目 → 値、全部セレクトで移動する。
    readonly=True のときは閲覧のみ（パネルから一般メンバーが開いた場合）。"""

    def __init__(self, guild_id, owner_id, readonly=False, plain=False, guild=None):
        super().__init__(timeout=600)
        self.gid = guild_id
        if guild is not None:
            _guilds[guild_id] = guild
        self.owner_id = owner_id
        self.readonly = readonly
        self.plain = plain     # True = /設定用（エレベーター式でない素直な画面）
        self.floor = None      # 選択中の階（None = ロビー）
        self.category = None   # plainモードで選択中のカテゴリ
        self.feature = None    # 選択中の機能キー
        self.edit = None       # 編集中の項目キー
        self._build()

    # ---------- 状態 ----------
    def cfg(self):
        return feature_cfg(self.gid, self.feature)

    def feat(self):
        return FEATURES[self.feature]

    def floor_category(self):
        if self.floor is None:
            return None
        return floors_map(self.gid).get(self.floor)

    def current_category(self):
        if self.plain:
            return self.category
        return None

    def edit_item(self):
        if self.edit == "__toggle":
            return {"key": "__toggle", "label": "有効 / 無効", "type": "toggle"}
        if self.edit and self.edit.startswith("floor:"):
            return {"key": self.edit,
                    "label": f"{self.edit.split(':', 1)[1]}階のカテゴリ",
                    "type": "choice"}
        for item in self.feat()["settings"]:
            if item["key"] == self.edit:
                return item
        return None

    def _enabled(self, key):
        return bool(feature_cfg(self.gid, key).get("enabled"))

    # ---------- 画面構築 ----------
    def _build(self):
        self.clear_items()
        if self.plain:
            self._build_plain()
            return
        m = floors_map(self.gid)
        options = []
        for i in visible_floors(self.gid):
            names = _floor_cat_names(self.gid, m.get(i))
            if names:
                label = names[0] + (f" ほか{len(names) - 1}件" if len(names) > 1 else "")
                options.append(discord.SelectOption(
                    label=f"{i}階 — {label}"[:100], value=str(i),
                    emoji="📁", default=(self.floor == i)))
            else:
                options.append(discord.SelectOption(
                    label=f"{i}階 — 未設定", value=str(i),
                    default=(self.floor == i)))
        if not self.readonly:
            options.append(discord.SelectOption(
                label="階の割り当て設定", value="__floors", emoji="🛗",
                default=(self.feature == "elevator" and self.floor is None)))
        fsel = discord.ui.Select(placeholder="🛗 乗りたい階を選ぶ",
                                 options=options, row=0)

        async def _floor(interaction, _sel=fsel):
            if not await self._gate(interaction):
                return
            v = _sel.values[0]
            if v == "__floors":
                self.floor = None
                self.feature = "elevator"
                self.edit = None
                return await self._rerender(interaction)
            await self._ride(interaction, int(v))

        fsel.callback = _floor
        self.add_item(fsel)

        if self.feature == "elevator" and self.floor is None:
            self._build_feature_body()
            return
        return

    def _build_plain(self):
        cat_sel = discord.ui.Select(
            placeholder="🏢 カテゴリを選ぶ",
            options=[discord.SelectOption(
                label=f"{c['emoji']} {c['name']}", value=c["key"],
                description=c["desc"][:100],
                default=(c["key"] == self.category))
                for c in CATEGORIES if features_in(c["key"])],
            row=0)

        async def _cat(interaction, _sel=cat_sel):
            if not await self._gate(interaction):
                return
            self.category = _sel.values[0]
            self.feature = None
            self.edit = None
            await self._rerender(interaction)

        cat_sel.callback = _cat
        self.add_item(cat_sel)
        if self.category:
            self._build_feature_select(self.category)

    def _build_feature_select(self, cat_key):
        feats = features_in(cat_key)
        if feats:
            sel = discord.ui.Select(
                placeholder="🧩 機能を選ぶ",
                options=[discord.SelectOption(
                    label=f"{f['emoji']} {f['name']}", value=f["key"],
                    description=("🟢 有効" if self._enabled(f["key"]) else "⚪ 無効")
                    + f" — {f['desc']}"[:100],
                    default=(f["key"] == self.feature)) for f in feats],
                row=1)

            async def _feat(interaction, _sel=sel):
                if not await self._gate(interaction):
                    return
                self.feature = _sel.values[0]
                self.edit = None
                await self._rerender(interaction)

            sel.callback = _feat
            self.add_item(sel)
        if self.feature:
            self._build_feature_body()

    def _build_feature_body(self):
        if self.edit is None:
            if not self.readonly:
                if self.feature == "elevator":
                    self._build_elevator_items()
                else:
                    self._build_item_select()
        elif self.edit.startswith("floor:"):
            self._build_floor_editor()
        else:
            self._build_editor()

    def _build_elevator_items(self):
        m = floors_map(self.gid)
        options = [discord.SelectOption(
            label="🔘 有効 / 無効", value="__toggle",
            description="現在: " + ("🟢 有効" if self.cfg().get("enabled") else "⚪ 無効"))]
        for n in sorted(m.keys()):
            label = _floor_label(self.gid, m.get(n))
            options.append(discord.SelectOption(
                label=f"{n}階", value=f"floor:{n}",
                description=("現在: " + (label if label else "未設定"))[:100]))
        options.append(discord.SelectOption(
            label="➕ 階を追加", value="__add_floor",
            description="新しい階を増やす（無限に追加できる）"))
        title, text = _panel_texts(self.gid)
        options.append(discord.SelectOption(
            label="📝 パネルのタイトル", value="text:panel_title",
            description=f"現在: {title}"[:100]))
        options.append(discord.SelectOption(
            label="📝 パネルの説明文", value="text:panel_text",
            description=f"現在: {text}"[:100]))
        isel = discord.ui.Select(placeholder="⚙️ 階を選ぶ / 追加する",
                                 options=options, row=2)

        async def _item(interaction, _sel=isel):
            if not await self._gate(interaction):
                return
            v = _sel.values[0]
            if v == "__toggle":
                self.edit = "__toggle"
                return await self._rerender(interaction)
            if v.startswith("text:"):
                key = v.split(":", 1)[1]
                label = "パネルのタイトル" if key == "panel_title" else "パネルの説明文"
                ptitle, ptext = _panel_texts(self.gid)
                item = {"key": key, "label": label, "type": "text",
                        "style": "long" if key == "panel_text" else "short"}
                return await interaction.response.send_modal(
                    ItemModal(self, item,
                              current=ptitle if key == "panel_title" else ptext))
            if v == "__add_floor":
                mm = floors_map(self.gid)
                n = (max(mm.keys()) if mm else 0) + 1
                mm[n] = []
                save_floors_map(self.gid, mm)
                self.edit = f"floor:{n}"
                await self._rerender(interaction)
                await refresh_elevator_panel(self.gid)
                return
            self.edit = v
            await self._rerender(interaction)

        isel.callback = _item
        self.add_item(isel)

    def _build_floor_editor(self):
        n = int(self.edit.split(":", 1)[1])
        cur = floors_map(self.gid).get(n) or []
        opts = [discord.SelectOption(label="未設定", value="__none",
                                     default=(not cur))]
        g = _guild(self.gid)
        for c in (getattr(g, "categories", []) or [])[:23]:
            opts.append(discord.SelectOption(
                label=f"📁 {c.name}"[:100], value=str(c.id),
                default=(c.id in cur)))
        opts.append(discord.SelectOption(label="🗑 この階を削除", value="__delete"))
        vsel = discord.ui.Select(
            placeholder=f"✏️ {n}階のカテゴリを選ぶ（複数OK）",
            options=opts, row=2, min_values=1, max_values=len(opts))

        async def _val(interaction, _sel=vsel):
            if not await self._gate(interaction):
                return
            vals = list(_sel.values)
            mm = floors_map(self.gid)
            if "__delete" in vals:
                if n == 1:
                    mm[1] = []
                else:
                    mm.pop(n, None)
            elif "__none" in vals:
                mm[n] = []
            else:
                mm[n] = [int(v) for v in vals]
            save_floors_map(self.gid, mm)
            self.edit = None
            await self._rerender(interaction)
            await refresh_elevator_panel(self.gid)

        vsel.callback = _val
        self.add_item(vsel)
        back = discord.ui.Select(
            placeholder="⬅ 戻る",
            options=[discord.SelectOption(label="⬅ 階一覧に戻る", value="back")],
            row=3)

        async def _back(interaction, _sel=back):
            if not await self._gate(interaction):
                return
            self.edit = None
            await self._rerender(interaction)

        back.callback = _back
        self.add_item(back)

    def _build_item_select(self):
        feat = self.feat()
        options = [discord.SelectOption(
            label="🔘 有効 / 無効", value="__toggle",
            description="現在: " + ("🟢 有効" if self.cfg().get("enabled") else "⚪ 無効"))]
        for item in feat["settings"]:
            options.append(discord.SelectOption(
                label=item["label"], value=item["key"],
                description=f"現在: {_fmt_value(item, self.cfg().get(item['key']))}"[:100]))
        isel = discord.ui.Select(placeholder="⚙️ 設定する項目を選ぶ",
                                 options=options, row=2)

        async def _item(interaction, _sel=isel):
            if not await self._gate(interaction):
                return
            key = _sel.values[0]
            item = ({"key": "__toggle", "label": "有効 / 無効", "type": "toggle"}
                    if key == "__toggle" else
                    next(i for i in self.feat()["settings"] if i["key"] == key))
            if item["type"] in ("text", "number"):
                return await interaction.response.send_modal(ItemModal(self, item))
            self.edit = key
            await self._rerender(interaction)

        isel.callback = _item
        self.add_item(isel)

    def _build_editor(self):
        item = self.edit_item()
        cur = (self.cfg().get("enabled") if self.edit == "__toggle"
               else self.cfg().get(item["key"]))
        if item["type"] in ("toggle", "choice"):
            if item["type"] == "toggle":
                opts = [discord.SelectOption(label=label, value=v,
                                             default=((v == "on") == bool(cur)))
                        for v, label in ON_OFF]
            else:
                opts = [discord.SelectOption(label=label, value=str(v),
                                             default=(str(v) == str(cur)))
                        for v, label in item.get("options", [])]
            vsel = discord.ui.Select(placeholder=f"✏️ {item['label']} の値を選ぶ",
                                     options=opts, row=2)

            async def _val(interaction, _sel=vsel):
                if not await self._gate(interaction):
                    return
                v = _sel.values[0]
                if item["type"] == "toggle":
                    value = (v == "on")
                    if self.edit == "__toggle":
                        self.cfg()["enabled"] = value
                    else:
                        self.cfg()[item["key"]] = value
                else:
                    value = v
                    for ov, _label in item.get("options", []):
                        if str(ov) == v:
                            value = ov
                    self.cfg()[item["key"]] = value
                save_config()
                self.edit = None
                await self._rerender(interaction)
                await refresh_panels(self.gid)

            vsel.callback = _val
            self.add_item(vsel)
        elif item["type"] == "channel":
            csel = discord.ui.ChannelSelect(
                placeholder=f"✏️ {item['label']} を選ぶ",
                channel_types=[discord.ChannelType.text], row=2)

            async def _ch(interaction, _sel=csel):
                if not await self._gate(interaction):
                    return
                v = _sel.values[0]
                self.cfg()[item["key"]] = int(getattr(v, "id", v))
                save_config()
                self.edit = None
                await self._rerender(interaction)
                await refresh_panels(self.gid)

            csel.callback = _ch
            self.add_item(csel)
        elif item["type"] == "role":
            rsel = discord.ui.RoleSelect(
                placeholder=f"✏️ {item['label']} を選ぶ", row=2)

            async def _role(interaction, _sel=rsel):
                if not await self._gate(interaction):
                    return
                v = _sel.values[0]
                self.cfg()[item["key"]] = int(getattr(v, "id", v))
                save_config()
                self.edit = None
                await self._rerender(interaction)
                await refresh_panels(self.gid)

            rsel.callback = _role
            self.add_item(rsel)
        back = discord.ui.Select(
            placeholder="⬅ 戻る",
            options=[discord.SelectOption(label="⬅ 項目一覧に戻る", value="back")],
            row=3)

        async def _back(interaction, _sel=back):
            if not await self._gate(interaction):
                return
            self.edit = None
            await self._rerender(interaction)

        back.callback = _back
        self.add_item(back)

    # ---------- 乗車アニメーション ----------
    async def _ride(self, interaction, floor):
        await interaction.response.edit_message(
            embed=_ride_embed(floor, 0), view=None)
        for pct in (25, 50, 75, 100):
            await asyncio.sleep(RIDE_STEP)
            await interaction.edit_original_response(
                embed=_ride_embed(floor, pct))
        await interaction.edit_original_response(
            embed=_ride_embed(floor, 100, arrived=True))
        await asyncio.sleep(RIDE_STEP / 2)
        self.floor = floor
        self.feature = None
        self.edit = None
        self._build()
        await interaction.edit_original_response(embed=self.embed(), view=self)

    # ---------- 表示 ----------
    def embed(self):
        if self.edit is not None and self.feature:
            item = self.edit_item()
            return discord.Embed(
                title=f"✏️ {item['label']} を設定",
                description="下のセレクトで値を選んでね。選んだ瞬間に保存されるよ。",
                color=discord.Color.blurple())
        if self.feature:
            feat = self.feat()
            cfg = self.cfg()
            embed = discord.Embed(title=f"{feat['emoji']} {feat['name']}",
                                  description=feat["desc"],
                                  color=discord.Color.green() if cfg.get("enabled")
                                  else discord.Color.greyple())
            embed.add_field(name="状態",
                            value="🟢 有効" if cfg.get("enabled") else "⚪ 無効",
                            inline=False)
            if self.feature == "elevator":
                m = floors_map(self.gid)
                if m:
                    for n in sorted(m.keys()):
                        label = _floor_label(self.gid, m.get(n))
                        embed.add_field(
                            name=f"{n}階",
                            value=(label if label else "未設定"),
                            inline=True)
                else:
                    embed.add_field(name="階", value="まだ階がありません", inline=False)
            for item in feat["settings"]:
                embed.add_field(name=item["label"],
                                value=_fmt_value(item, cfg.get(item["key"])),
                                inline=True)
            if self.readonly:
                embed.set_footer(text="閲覧モード（設定の変更は管理者だけです）")
            else:
                embed.set_footer(text="下のセレクトで項目を選ぶと、その場で変更できるよ")
            return embed
        if self.plain:
            cat_key = self.current_category()
            if cat_key is not None:
                cat = category_of(cat_key)
                feats = features_in(cat_key)
                lines = [f"{f['emoji']} **{f['name']}**"
                         f"（{'🟢 有効' if self._enabled(f['key']) else '⚪ 無効'}）— {f['desc']}"
                         for f in feats]
                return discord.Embed(
                    title=f"{cat['emoji']} {cat['name']}",
                    description="\n".join(lines) if lines else "このカテゴリの機能はまだないよ。",
                    color=discord.Color.blurple())
            lines = [f"{c['emoji']} **{c['name']}** — {c['desc']}"
                     for c in CATEGORIES if features_in(c["key"])]
            return discord.Embed(
                title="⚙️ 設定",
                description="カテゴリを選んでね。\n\n" + "\n".join(lines),
                color=discord.Color.blurple())
        if self.floor is not None:
            ids = floors_map(self.gid).get(self.floor) or []
            cats = [c for c in (_discord_category(self.gid, cid) for cid in ids)
                    if c is not None]
            if not cats:
                return discord.Embed(
                    title=f"🛗 {self.floor}階",
                    description=("この階にはまだカテゴリが設定されてないよ。\n"
                                 "管理者は /設定 → システム → エレベーター設定 から設定できます。"),
                    color=discord.Color.greyple())
            embed = discord.Embed(title=f"🛗 {self.floor}階",
                                  color=discord.Color.blurple())
            for cat in cats[:10]:
                lines = []
                for ch in (getattr(cat, "channels", []) or [])[:25]:
                    if getattr(ch, "type", None) == discord.ChannelType.voice:
                        lines.append(f"🔊 {ch.name}")
                    else:
                        lines.append(f"<#{ch.id}>")
                embed.add_field(
                    name=f"📁 {cat.name}",
                    value="\n".join(lines) if lines else "チャンネルがありません",
                    inline=False)
            return embed
        title, text = _panel_texts(self.gid)
        return discord.Embed(
            title=title,
            description=text + "\n\n" + "\n".join(_floor_lines(self.gid)),
            color=discord.Color.blurple())

    async def _gate(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ これは他の人の設定画面です。", ephemeral=True)
            return False
        return True

    async def _rerender(self, interaction):
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)


# ---------------------------------------------------------------- 常時設置パネル
PANEL_TITLE_DEFAULT = "🛗 エレベーター"
PANEL_TEXT_DEFAULT = "乗りたい階を選んでね。選んだ階に設定されたカテゴリが開きます。"


def _panel_texts(gid):
    cfg = feature_cfg(gid, "elevator")
    return (cfg.get("panel_title") or PANEL_TITLE_DEFAULT,
            cfg.get("panel_text") or PANEL_TEXT_DEFAULT)


def build_panel_embed(gid):
    title, text = _panel_texts(gid)
    return discord.Embed(
        title=title,
        description=text + "\n\n" + "\n".join(_floor_lines(gid)),
        color=discord.Color.blurple())


class ElevatorPanelView(discord.ui.View):
    """常時設置型エレベーターパネル（全員使用可能・再起動後も動作）"""

    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        m = floors_map(guild_id) if guild_id is not None else {}
        floors = visible_floors(guild_id) if guild_id is not None else [1]
        options = []
        for i in floors:
            label = _floor_label(guild_id, m.get(i)) if guild_id is not None else None
            options.append(discord.SelectOption(
                label=f"{i}階", value=str(i),
                description=(label if label else "未設定")[:100]))
        sel = discord.ui.Select(custom_id="mega_elevator:floor",
                                placeholder="🛗 乗りたい階を選んでね",
                                options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        floor = int(interaction.data["values"][0]) \
            if interaction.data and interaction.data.get("values") else None
        if floor is None:
            return
        session = ElevatorView(interaction.guild.id, interaction.user.id,
                               readonly=not is_privileged(interaction.user),
                               guild=interaction.guild)
        session.floor = floor
        await interaction.response.send_message(
            embed=_ride_embed(floor, 0), ephemeral=True)
        for pct in (25, 50, 75, 100):
            await asyncio.sleep(RIDE_STEP)
            await interaction.edit_original_response(
                embed=_ride_embed(floor, pct))
        await interaction.edit_original_response(
            embed=_ride_embed(floor, 100, arrived=True))
        await asyncio.sleep(RIDE_STEP / 2)
        session._build()
        await interaction.edit_original_response(
            embed=session.embed(), view=session)


async def refresh_elevator_panel(guild_id):
    """割り当て変更などを設置済みパネルへ反映する"""
    loc = store.cfg(guild_id).get("elevator_panel") or {}
    if not loc.get("channel_id") or not loc.get("message_id"):
        return
    channel = bot.get_channel(int(loc["channel_id"]))
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(int(loc["message_id"]))
        await msg.edit(embed=build_panel_embed(guild_id),
                       view=ElevatorPanelView(guild_id))
    except Exception:
        pass


register_panel_refresher(refresh_elevator_panel)


@bot.listen("on_ready")
async def _refresh_panels_on_ready():
    for g in bot.guilds:
        _guilds[g.id] = g
    for gid in list(store.data.keys()):
        if gid.lstrip("-").isdigit():
            await refresh_elevator_panel(int(gid))


# ---------------------------------------------------------------- ヘルプ
class HelpView(discord.ui.View):
    """ヘルプ: カテゴリ → 機能 のセレクトで説明を読む"""

    def __init__(self, guild_id):
        super().__init__(timeout=600)
        self.gid = guild_id
        self.category = None
        self.feature = None
        self._build()

    def _build(self):
        self.clear_items()
        cat_sel = discord.ui.Select(
            placeholder="🏢 カテゴリを選ぶ",
            options=[discord.SelectOption(
                label=f"{c['emoji']} {c['name']}", value=c["key"],
                description=c["desc"][:100],
                default=(c["key"] == self.category))
                for c in CATEGORIES if features_in(c["key"])],
            row=0)

        async def _cat(interaction, _sel=cat_sel):
            self.category = _sel.values[0]
            self.feature = None
            await self._rerender(interaction)

        cat_sel.callback = _cat
        self.add_item(cat_sel)
        if self.category:
            feats = features_in(self.category)
            if feats:
                fsel = discord.ui.Select(
                    placeholder="🧩 機能を選ぶ",
                    options=[discord.SelectOption(
                        label=f"{f['emoji']} {f['name']}", value=f["key"],
                        description=f["desc"][:100],
                        default=(f["key"] == self.feature)) for f in feats],
                    row=1)

                async def _feat(interaction, _sel=fsel):
                    self.feature = _sel.values[0]
                    await self._rerender(interaction)

                fsel.callback = _feat
                self.add_item(fsel)

    def embed(self):
        if self.feature:
            f = FEATURES[self.feature]
            embed = discord.Embed(title=f"{f['emoji']} {f['name']}",
                                  description=f["desc"],
                                  color=discord.Color.blurple())
            if f["help"]:
                embed.add_field(name="使い方", value=f["help"], inline=False)
            enabled = bool(feature_cfg(self.gid, self.feature).get("enabled"))
            embed.add_field(name="このサーバーでの状態",
                            value="🟢 有効" if enabled else "⚪ 無効（管理者が /設定 で有効化）",
                            inline=False)
            return embed
        if self.category:
            cat = category_of(self.category)
            feats = features_in(self.category)
            lines = [f"{f['emoji']} **{f['name']}** — {f['desc']}" for f in feats]
            return discord.Embed(
                title=f"{cat['emoji']} {cat['name']}",
                description="\n".join(lines) if lines else "このカテゴリの機能はまだないよ。",
                color=discord.Color.blurple())
        return discord.Embed(
            title="📖 ヘルプ",
            description="カテゴリを選ぶと、その中の機能の一覧と説明が見れるよ。",
            color=discord.Color.blurple())

    async def _rerender(self, interaction):
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)


# ---------------------------------------------------------------- コマンド
@bot.tree.command(name="設定", description="設定エレベーター（管理者用）")
async def cmd_settings(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    if not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設定は管理者だけが使えます。", ephemeral=True)
    view = ElevatorView(interaction.guild.id, interaction.user.id,
                        plain=True, guild=interaction.guild)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


@command_group("panel", "パネル", "パネル設置").command(name="エレベーター設置", description="常時設置型エレベーターパネルを設置する（管理者用）")
async def cmd_elevator_panel(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    if not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get("elevator_panel") or {}
    if old.get("channel_id") and old.get("message_id"):
        old_ch = interaction.guild.get_channel(int(old["channel_id"]))
        if old_ch is not None:
            try:
                old_msg = await old_ch.fetch_message(int(old["message_id"]))
                await old_msg.delete()
            except Exception:
                pass
    msg = await interaction.channel.send(
        embed=build_panel_embed(interaction.guild.id),
        view=ElevatorPanelView(interaction.guild.id))
    cfg["elevator_panel"] = {"channel_id": interaction.channel.id,
                             "message_id": msg.id}
    save_config()
    await interaction.response.send_message(
        "🛗 エレベーターパネルを設置しました。", ephemeral=True)


@bot.tree.command(name="ヘルプ", description="機能の説明を見る")
async def cmd_help(interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "⚠️ サーバーの中で使ってね。", ephemeral=True)
    view = HelpView(interaction.guild.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)
