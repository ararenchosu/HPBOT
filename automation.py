# 機能群: 自動化（自動返信/定時メッセージ/自動スレッド/自動ピン/自動リアクション/誕生日）
import time

import discord
from discord.ext import tasks

from core import (bot, feature_cfg, feature_enabled, guild_data,
                  is_privileged, jst_now, register_feature, save_config,
                  save_data,
                  command_group)

CAT = "auto"

_G = command_group("auto", "自動化", "自動化機能")
_cooldowns = {}


def _cool(key, seconds):
    now = time.monotonic()
    if now - _cooldowns.get(key, 0) < seconds:
        return True
    _cooldowns[key] = now
    return False


# ---------------------------------------------------------------- キーワード系リスナー
register_feature("autoreply", CAT, "キーワード自動返信", "💬",
                 "キーワードに自動で返信する。",
                 help_text="/自動返信設定 でキーワードと返信を登録します。")
register_feature("autoreaction", CAT, "自動リアクション", "😀",
                 "キーワードを含む発言にリアクションを付ける。",
                 help_text="/自動リアクション設定 で登録します。")
register_feature("autopin", CAT, "自動ピン留め", "📌",
                 "キーワードを含む発言を自動でピン留めする。",
                 settings=[{"key": "keyword", "label": "ピン留めするキーワード",
                            "type": "text", "default": "📌"}])
register_feature("autothread", CAT, "自動スレッド", "🧵",
                 "指定チャンネルの投稿に自動でスレッドを作る。",
                 settings=[{"key": "channel_id", "label": "対象チャンネル",
                            "type": "channel", "default": None},
                           {"key": "name", "label": "スレッド名",
                            "type": "text", "default": "💬 スレッド"}])


@bot.listen("on_message")
async def _auto_listener(message):
    if message.guild is None or message.author.bot:
        return
    gid = message.guild.id
    content = message.content or ""
    try:
        if feature_enabled(gid, "autothread"):
            cfg = feature_cfg(gid, "autothread")
            if cfg.get("channel_id") and int(cfg["channel_id"]) == message.channel.id:
                await message.create_thread(
                    name=(cfg.get("name") or "💬 スレッド")[:100])
                return
        if feature_enabled(gid, "autopin"):
            keyword = feature_cfg(gid, "autopin").get("keyword") or "📌"
            if keyword and keyword in content:
                await message.pin()
                return
        if feature_enabled(gid, "autoreply"):
            rules = feature_cfg(gid, "autoreply").get("rules") or []
            for rule in rules:
                if rule["keyword"] in content:
                    if _cool((gid, message.channel.id, rule["keyword"]), 10):
                        break
                    await message.channel.send(
                        rule["reply"].replace("{user}", message.author.mention))
                    break
        if feature_enabled(gid, "autoreaction"):
            rules = feature_cfg(gid, "autoreaction").get("rules") or []
            for rule in rules:
                if rule["keyword"] in content:
                    try:
                        await message.add_reaction(rule["emoji"])
                    except Exception:
                        pass
                    break
    except Exception:
        pass


# ---------------------------------------------------------------- ルール設定（共通ビュー）
class _RuleModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="➕ ルールを追加")
        self.view = view
        self.keyword = discord.ui.TextInput(label="キーワード", max_length=100)
        self.value = discord.ui.TextInput(
            label=view.value_label, max_length=500,
            style=discord.TextStyle.paragraph if view.feature == "autoreply"
            else discord.TextStyle.short)
        self.add_item(self.keyword)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        rules = feature_cfg(self.view.gid, self.view.feature).setdefault(
            "rules", [])
        rules.append({"keyword": str(self.keyword.value).strip(),
                      "reply": str(self.value.value).strip(),
                      "emoji": str(self.value.value).strip()})
        rules[:] = rules[:25]
        save_config()
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class RuleSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id, feature, title, value_label):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self.feature = feature
        self.title = title
        self.value_label = value_label
        self._build()

    def rules(self):
        return feature_cfg(self.gid, self.feature).get("rules") or []

    def embed(self):
        lines = [f"・「{r['keyword']}」→ {r.get('reply') or r.get('emoji')}"
                 for r in self.rules()]
        return discord.Embed(
            title=self.title, color=discord.Color.blurple(),
            description="\n".join(lines) if lines else "ルールがありません。")

    def _build(self):
        self.clear_items()
        options = [discord.SelectOption(label="➕ ルールを追加", value="__add")]
        options += [discord.SelectOption(
            label=f"🗑 「{r['keyword']}」"[:100], value=str(i))
            for i, r in enumerate(self.rules())]
        sel = discord.ui.Select(placeholder="⚙️ 追加 / 削除", options=options)

        async def _cb(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "__add":
                if len(self.rules()) >= 25:
                    return await interaction.response.send_message(
                        "⚠️ ルールは最大25件です。", ephemeral=True)
                return await interaction.response.send_modal(
                    _RuleModal(self))
            rules = feature_cfg(self.gid, self.feature).setdefault("rules", [])
            del rules[int(v)]
            save_config()
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        sel.callback = _cb
        self.add_item(sel)


@_G.command(name="自動返信設定", description="キーワード自動返信を設定する（管理者用）")
async def cmd_autoreply_settings(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    view = RuleSettingsView(interaction.guild.id, interaction.user.id,
                            "autoreply", "💬 キーワード自動返信", "返信文")
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


@_G.command(name="自動リアクション設定", description="自動リアクションを設定する（管理者用）")
async def cmd_autoreaction_settings(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    view = RuleSettingsView(interaction.guild.id, interaction.user.id,
                            "autoreaction", "😀 自動リアクション", "絵文字")
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- 定時メッセージ
register_feature("scheduled", CAT, "定時メッセージ", "🕘",
                 "毎日決まった時刻にメッセージを送る。",
                 help_text="/定時メッセージ設定 で登録します（最大10件）。")


class _ScheduleModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="🕘 定時メッセージを追加")
        self.view = view
        self.time_input = discord.ui.TextInput(label="時刻（HH:MM）",
                                               max_length=5, placeholder="09:00")
        self.text_input = discord.ui.TextInput(
            label="本文", max_length=1000, style=discord.TextStyle.paragraph)
        self.add_item(self.time_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction):
        t = str(self.time_input.value).strip()
        parts = t.split(":")
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception:
            return await interaction.response.send_message(
                "⚠️ 時刻は 09:00 の形で入れてね。", ephemeral=True)
        channel_id = self.view.pending_channel
        if not channel_id:
            return await interaction.response.send_message(
                "⚠️ 先に送信先チャンネルを選んでね。", ephemeral=True)
        items = guild_data(self.view.gid).setdefault("schedules", [])
        items.append({"time": f"{h:02d}:{m:02d}", "channel_id": channel_id,
                      "text": str(self.text_input.value)[:1000],
                      "last_fired": ""})
        save_data()
        self.view._build()
        await interaction.response.edit_message(
            embed=self.view.embed(), view=self.view)


class ScheduleSettingsView(discord.ui.View):
    def __init__(self, gid, owner_id):
        super().__init__(timeout=600)
        self.gid = gid
        self.owner_id = owner_id
        self.pending_channel = None
        self._build()

    def items(self):
        return guild_data(self.gid).get("schedules", [])

    def embed(self):
        lines = [f"・{s['time']} → <#{s['channel_id']}>: {s['text'][:30]}"
                 for s in self.items()]
        return discord.Embed(
            title="🕘 定時メッセージ設定", color=discord.Color.blurple(),
            description="\n".join(lines) if lines else "登録がありません。")

    def _build(self):
        self.clear_items()
        csel = discord.ui.ChannelSelect(
            placeholder="📍 送信先チャンネル（先に選ぶ）",
            channel_types=[discord.ChannelType.text], row=0)

        async def _ch(interaction, _sel=csel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            self.pending_channel = int(getattr(v, "id", v))
            await interaction.response.send_message(
                f"送信先を <#{self.pending_channel}> にしました。"
                "次に「➕ 追加」を選んでね。", ephemeral=True)

        csel.callback = _ch
        self.add_item(csel)
        options = [discord.SelectOption(label="➕ 追加（時刻と本文）",
                                        value="__add")]
        options += [discord.SelectOption(
            label=f"🗑 {s['time']} のメッセージ"[:100], value=str(i))
            for i, s in enumerate(self.items())]
        sel = discord.ui.Select(placeholder="⚙️ 追加 / 削除", options=options,
                                row=1)

        async def _cb(interaction, _sel=sel):
            if interaction.user.id != self.owner_id:
                return
            v = _sel.values[0]
            if v == "__add":
                if len(self.items()) >= 10:
                    return await interaction.response.send_message(
                        "⚠️ 最大10件です。", ephemeral=True)
                return await interaction.response.send_modal(
                    _ScheduleModal(self))
            items = guild_data(self.gid).setdefault("schedules", [])
            del items[int(v)]
            save_data()
            self._build()
            await interaction.response.edit_message(
                embed=self.embed(), view=self)

        sel.callback = _cb
        self.add_item(sel)


@_G.command(name="定時メッセージ設定", description="定時メッセージを設定する（管理者用）")
async def cmd_schedule_settings(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "scheduled"):
        return await interaction.response.send_message(
            "⚠️ 定時メッセージは無効です。", ephemeral=True)
    view = ScheduleSettingsView(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True)


# ---------------------------------------------------------------- 誕生日
register_feature(
    "birthday", CAT, "誕生日お祝い", "🎂",
    "メンバーの誕生日を毎日9時にお祝いする。",
    settings=[{"key": "channel_id", "label": "お祝いチャンネル",
               "type": "channel", "default": None}])


class _BirthdayModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🎂 誕生日を登録")
        self.date = discord.ui.TextInput(label="誕生日（MM-DD）", max_length=5,
                                         placeholder="04-01")
        self.add_item(self.date)

    async def on_submit(self, interaction):
        text = str(self.date.value).strip()
        parts = text.split("-")
        try:
            month, day = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                raise ValueError
        except Exception:
            return await interaction.response.send_message(
                "⚠️ 04-01 の形で入れてね。", ephemeral=True)
        guild_data(interaction.guild.id).setdefault(
            "birthdays", {})[str(interaction.user.id)] = f"{month:02d}-{day:02d}"
        save_data()
        await interaction.response.send_message(
            f"🎂 誕生日を {month}月{day}日 で登録しました！", ephemeral=True)


@_G.command(name="誕生日登録", description="自分の誕生日を登録する")
async def cmd_birthday(interaction):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "birthday"):
        return await interaction.response.send_message(
            "⚠️ 誕生日機能は無効です。", ephemeral=True)
    await interaction.response.send_modal(_BirthdayModal())


# ---------------------------------------------------------------- 定期ループ
@tasks.loop(seconds=30)
async def _automation_loop():
    from core import data_store
    now = jst_now()
    hhmm = now.strftime("%H:%M")
    today = now.date().isoformat()
    for gid_str in list(data_store.data.keys()):
        gid = int(gid_str)
        data = guild_data(gid)
        if feature_enabled(gid, "scheduled"):
            for item in data.get("schedules", []):
                if item["time"] == hhmm and item.get("last_fired") != today:
                    item["last_fired"] = today
                    channel = bot.get_channel(int(item["channel_id"]))
                    if channel is not None:
                        try:
                            await channel.send(item["text"])
                        except Exception:
                            pass
                    save_data()
        if feature_enabled(gid, "birthday") and hhmm >= "09:00":
            cfg = feature_cfg(gid, "birthday")
            cid = cfg.get("channel_id")
            fired = data.setdefault("birthday_fired", {})
            if cid and fired.get(today) != "done":
                mmdd = now.strftime("%m-%d")
                people = [uid for uid, bd in
                          data.get("birthdays", {}).items() if bd == mmdd]
                if people:
                    channel = bot.get_channel(int(cid))
                    if channel is not None:
                        try:
                            await channel.send(
                                "🎂 今日は " + " ".join(
                                    f"<@{u}>" for u in people)
                                + " の誕生日です！おめでとう🎉")
                        except Exception:
                            pass
                fired[today] = "done"
                save_data()


@bot.listen("on_ready")
async def _start_automation_loop():
    if not _automation_loop.is_running():
        _automation_loop.start()
