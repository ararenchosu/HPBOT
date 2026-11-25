# 機能群: 運営・イベント（抽選/投票/アンケート/募集/出欠/順番/チーム分け/カウントダウン）
import random
from datetime import timedelta

import discord
from discord.ext import tasks

from core import (JST, bot, feature_enabled, guild_data, is_privileged,
                  jst_now, register_feature, save_data, sel_values, store,
                  save_config,
                  command_group)
from social import _install_panel, _make_refresher
from core import register_panel_refresher

CAT = "event"

_GE = command_group("event", "イベント", "運営・イベント機能")
_GK = command_group("social", "交流", "交流・パネル機能")


def _parse_dt(text):
    from datetime import datetime
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m-%d %H:%M", "%m/%d %H:%M"):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.year == 1900:
                dt = dt.replace(year=jst_now().year)
            return dt.replace(tzinfo=JST)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- 抽選
register_feature("giveaway", CAT, "抽選", "🎉",
                 "参加者を募って自動で抽選する。",
                 help_text="/抽選開始 景品 当選人数 時間（時間）で開始します。")


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_giveaway:join", placeholder="🎉 抽選",
            options=[discord.SelectOption(label="🎉 参加する / やめる",
                                          value="toggle")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        gid = interaction.guild.id
        data = guild_data(gid).setdefault("giveaways", {})
        entry = data.get(str(interaction.message.id))
        if entry is None or entry.get("done"):
            return await interaction.response.send_message(
                "⚠️ この抽選は終わっています。", ephemeral=True)
        uid = interaction.user.id
        entries = entry.setdefault("entries", [])
        if uid in entries:
            entries.remove(uid)
            msg = "参加を取り消しました。"
        else:
            entries.append(uid)
            msg = f"🎉 参加しました！（現在 {len(entries)} 人）"
        save_data()
        await interaction.response.send_message(msg, ephemeral=True)


async def _draw_giveaway(gid, msg_id):
    data = guild_data(gid).setdefault("giveaways", {})
    entry = data.get(str(msg_id))
    if entry is None or entry.get("done"):
        return
    entry["done"] = True
    save_data()
    channel = bot.get_channel(int(entry["channel_id"]))
    if channel is None:
        return
    entries = entry.get("entries", [])
    winners = []
    if entries:
        winners = random.sample(entries, min(int(entry["winners"]), len(entries)))
    if winners:
        text = (f"🎉 **抽選結果: {entry['prize']}**\n当選者: "
                + " ".join(f"<@{w}>" for w in winners))
    else:
        text = f"🎉 **抽選結果: {entry['prize']}**\n参加者がいなかったため当選者なしです。"
    try:
        await channel.send(text)
    except Exception:
        pass
    for w in winners:
        try:
            user = await bot.fetch_user(w)
            await user.send(f"🎉 おめでとうございます！「{entry['prize']}」に"
                            f"当選しました！（サーバー: {channel.guild.name}）")
        except Exception:
            pass


@_GE.command(name="抽選開始", description="抽選を開始する（管理者用）")
@discord.app_commands.describe(景品="景品", 当選人数="当選人数", 時間="何時間後まで受付")
async def cmd_giveaway(interaction, 景品: str, 当選人数: int = 1, 時間: int = 24):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    if not feature_enabled(interaction.guild.id, "giveaway"):
        return await interaction.response.send_message(
            "⚠️ 抽選は無効です。", ephemeral=True)
    ends = jst_now() + timedelta(hours=max(1, int(時間)))
    embed = discord.Embed(title="🎉 抽選", color=discord.Color.magenta())
    embed.add_field(name="景品", value=景品, inline=False)
    embed.add_field(name="当選人数", value=f"{int(当選人数)} 人", inline=True)
    embed.add_field(name="締切", value=ends.strftime("%m-%d %H:%M"), inline=True)
    embed.set_footer(text="下のセレクトから参加してね")
    msg = await interaction.channel.send(embed=embed, view=GiveawayView())
    data = guild_data(interaction.guild.id).setdefault("giveaways", {})
    data[str(msg.id)] = {"prize": 景品, "winners": int(当選人数),
                         "ends_at": ends.isoformat(), "entries": [],
                         "channel_id": interaction.channel.id, "done": False}
    save_data()
    await interaction.response.send_message("🎉 抽選を開始しました。",
                                            ephemeral=True)


@_GE.command(name="抽選発表", description="抽選を今すぐ発表する（管理者用）")
@discord.app_commands.describe(メッセージid="抽選メッセージのID")
async def cmd_giveaway_draw(interaction, メッセージid: str):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 管理者だけが使えます。", ephemeral=True)
    await _draw_giveaway(interaction.guild.id, メッセージid.strip())
    await interaction.response.send_message("🎉 発表しました。", ephemeral=True)


# ---------------------------------------------------------------- 投票 / アンケート
def _poll_embed(state):
    counts = [0] * len(state["options"])
    for idx in state["votes"].values():
        if isinstance(idx, list):
            for i in idx:
                counts[i] += 1
        else:
            counts[idx] += 1
    total = sum(counts) or 1
    lines = []
    for i, opt in enumerate(state["options"]):
        pct = counts[i] * 100 // total
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"**{opt}** — {counts[i]} 票\n{bar} {pct}%")
    embed = discord.Embed(title=state["title"], color=discord.Color.blue(),
                          description="\n".join(lines))
    embed.set_footer(text=f"合計 {sum(counts)} 票")
    return embed


class _PollBase(discord.ui.View):
    MULTI = False
    CUSTOM_ID = "mega_poll:vote"

    def __init__(self, state=None):
        super().__init__(timeout=None)
        options = []
        if state:
            options = [discord.SelectOption(label=o[:100], value=str(i))
                       for i, o in enumerate(state["options"][:25])]
        if not options:
            options = [discord.SelectOption(label="選択肢", value="0")]
        sel = discord.ui.Select(
            custom_id=self.CUSTOM_ID, placeholder="選んで投票",
            min_values=1, max_values=(len(options) if self.MULTI else 1),
            options=options)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        gid = interaction.guild.id
        kind = "polls" if not self.MULTI else "surveys"
        state = guild_data(gid).setdefault(kind, {}).get(
            str(interaction.message.id))
        if state is None:
            return await interaction.response.send_message(
                "⚠️ データが見つかりません。", ephemeral=True)
        values = sel_values(interaction, self.children[0])
        picked = [int(v) for v in values]
        state["votes"][str(interaction.user.id)] = (
            picked if self.MULTI else picked[0])
        save_data()
        await interaction.response.edit_message(
            embed=_poll_embed(state), view=self.__class__(state))


class PollView(_PollBase):
    MULTI = False
    CUSTOM_ID = "mega_poll:vote"


class SurveyView(_PollBase):
    MULTI = True
    CUSTOM_ID = "mega_survey:vote"


class _PollModal(discord.ui.Modal):
    def __init__(self, multi):
        super().__init__(title="🗳️ 投票を作成" if not multi else "📋 アンケートを作成")
        self.multi = multi
        self.title_input = discord.ui.TextInput(label="質問", max_length=100)
        self.options_input = discord.ui.TextInput(
            label="選択肢（1行に1つ・最大10）", style=discord.TextStyle.paragraph,
            max_length=1000)
        self.add_item(self.title_input)
        self.add_item(self.options_input)

    async def on_submit(self, interaction):
        options = [ln.strip()[:100] for ln in
                   str(self.options_input.value).splitlines() if ln.strip()][:10]
        if len(options) < 2:
            return await interaction.response.send_message(
                "⚠️ 選択肢は2つ以上入れてね。", ephemeral=True)
        state = {"title": str(self.title_input.value)[:100],
                 "options": options, "votes": {}}
        view = SurveyView(state) if self.multi else PollView(state)
        msg = await interaction.channel.send(embed=_poll_embed(state), view=view)
        kind = "surveys" if self.multi else "polls"
        guild_data(interaction.guild.id).setdefault(kind, {})[str(msg.id)] = state
        save_data()
        await interaction.response.send_message("作成しました。", ephemeral=True)


register_feature("poll", CAT, "投票", "🗳️", "セレクト式の投票を作る。",
                 help_text="/投票作成 でモーダルが開きます。")
register_feature("survey", CAT, "アンケート", "📋",
                 "複数選択できるアンケートを作る。",
                 help_text="/アンケート作成 でモーダルが開きます。")


@_GE.command(name="投票作成", description="投票を作成する")
async def cmd_poll(interaction):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "poll"):
        return await interaction.response.send_message(
            "⚠️ 投票は無効です。", ephemeral=True)
    await interaction.response.send_modal(_PollModal(False))


@_GE.command(name="アンケート作成", description="アンケートを作成する")
async def cmd_survey(interaction):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "survey"):
        return await interaction.response.send_message(
            "⚠️ アンケートは無効です。", ephemeral=True)
    await interaction.response.send_modal(_PollModal(True))


# ---------------------------------------------------------------- 募集
register_feature(
    "recruit", CAT, "参加者募集", "🙋", "メンバー募集の投稿を作る。",
    settings=[
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "🙋 参加者募集"},
        {"key": "panel_text", "label": "パネルの説明文", "type": "text",
         "style": "long", "default": "セレクトから新しい募集を作れます。"},
    ])


def build_recruit_embed(gid):
    from core import feature_cfg
    cfg = feature_cfg(gid, "recruit")
    return discord.Embed(title=cfg.get("panel_title") or "🙋 参加者募集",
                         description=cfg.get("panel_text") or "",
                         color=discord.Color.teal())


class RecruitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_recruit:act", placeholder="🙋 募集の操作",
            options=[
                discord.SelectOption(label="🙋 参加する", value="join"),
                discord.SelectOption(label="🚪 やめる", value="leave"),
                discord.SelectOption(label="🔒 締め切る（作成者・管理者）",
                                     value="close"),
            ])
        sel.callback = self._cb
        self.add_item(sel)

    def _embed(self, state):
        members = state["members"]
        embed = discord.Embed(
            title=f"🙋 {state['title']}",
            description=(f"参加者 {len(members)} / {state['max']} 人\n"
                         + ("、".join(f"<@{m}>" for m in members) or "まだいません")),
            color=discord.Color.teal())
        if state.get("closed"):
            embed.title = f"🔒 {state['title']}（締切）"
        return embed

    async def _cb(self, interaction):
        gid = interaction.guild.id
        state = guild_data(gid).setdefault("recruits", {}).get(
            str(interaction.message.id))
        if state is None:
            return await interaction.response.send_message(
                "⚠️ 募集データが見つかりません。", ephemeral=True)
        action = sel_values(interaction, self.children[0])[0]
        uid = interaction.user.id
        if action == "close":
            if uid != state["owner"] and not is_privileged(interaction.user):
                return await interaction.response.send_message(
                    "⚠️ 締め切れるのは作成者と管理者だけです。", ephemeral=True)
            state["closed"] = True
        elif state.get("closed"):
            return await interaction.response.send_message(
                "⚠️ この募集は締め切られています。", ephemeral=True)
        elif action == "join":
            if uid not in state["members"]:
                state["members"].append(uid)
            if len(state["members"]) >= int(state["max"]):
                state["closed"] = True
        elif action == "leave":
            if uid in state["members"]:
                state["members"].remove(uid)
        save_data()
        await interaction.response.edit_message(embed=self._embed(state),
                                                view=self)


class _RecruitModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🙋 募集を作成")
        self.title_input = discord.ui.TextInput(label="募集タイトル",
                                                max_length=100)
        self.max_input = discord.ui.TextInput(label="定員（数字）", max_length=3,
                                              default="4")
        self.add_item(self.title_input)
        self.add_item(self.max_input)

    async def on_submit(self, interaction):
        try:
            max_n = max(1, min(99, int(str(self.max_input.value).strip())))
        except ValueError:
            max_n = 4
        state = {"title": str(self.title_input.value)[:100], "max": max_n,
                 "members": [interaction.user.id],
                 "owner": interaction.user.id, "closed": False}
        view = RecruitView()
        msg = await interaction.channel.send(embed=view._embed(state), view=view)
        guild_data(interaction.guild.id).setdefault(
            "recruits", {})[str(msg.id)] = state
        save_data()
        await interaction.response.send_message("🙋 募集を作成しました。",
                                                ephemeral=True)


class RecruitPanelView(discord.ui.View):
    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_recruit:new", placeholder="🙋 募集を作る",
            options=[discord.SelectOption(label="🙋 新しい募集を作る",
                                          value="new")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.guild is None or not feature_enabled(
                interaction.guild.id, "recruit"):
            return await interaction.response.send_message(
                "⚠️ 募集は無効です。", ephemeral=True)
        await interaction.response.send_modal(_RecruitModal())


register_panel_refresher(_make_refresher(
    "recruit_panel", build_recruit_embed, lambda gid: RecruitPanelView(gid)))


@_GK.command(name="募集パネル設置", description="参加者募集パネルを設置する（管理者用）")
async def cmd_recruit_panel(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    await _install_panel(interaction, "recruit_panel",
                         build_recruit_embed(interaction.guild.id),
                         RecruitPanelView(interaction.guild.id))
    await interaction.response.send_message("🙋 募集パネルを設置しました。",
                                            ephemeral=True)


# ---------------------------------------------------------------- 出欠確認
register_feature(
    "attendance", CAT, "出欠確認", "📅", "イベントの出欠を集計する。",
    settings=[
        {"key": "panel_title", "label": "パネルのタイトル", "type": "text",
         "default": "📅 出欠確認"},
        {"key": "panel_text", "label": "パネルの説明文", "type": "text",
         "style": "long", "default": "セレクトから出欠確認を作れます。"},
    ])


def build_attendance_embed(gid):
    from core import feature_cfg
    cfg = feature_cfg(gid, "attendance")
    return discord.Embed(title=cfg.get("panel_title") or "📅 出欠確認",
                         description=cfg.get("panel_text") or "",
                         color=discord.Color.blue())


class AttendanceView(discord.ui.View):
    CHOICES = [("yes", "⭕ 出席"), ("maybe", "△ 未定"), ("no", "❌ 欠席")]

    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_attendance:vote", placeholder="📅 出欠を選ぶ",
            options=[discord.SelectOption(label=label, value=value)
                     for value, label in self.CHOICES])
        sel.callback = self._cb
        self.add_item(sel)

    def _embed(self, state):
        embed = discord.Embed(title=f"📅 {state['title']}",
                              description=state.get("when", ""),
                              color=discord.Color.blue())
        answers = state["answers"]
        for value, label in self.CHOICES:
            people = [f"<@{uid}>" for uid, v in answers.items() if v == value]
            embed.add_field(name=f"{label}（{len(people)}）",
                            value="、".join(people) or "なし", inline=False)
        return embed

    async def _cb(self, interaction):
        state = guild_data(interaction.guild.id).setdefault(
            "attendances", {}).get(str(interaction.message.id))
        if state is None:
            return await interaction.response.send_message(
                "⚠️ データが見つかりません。", ephemeral=True)
        state["answers"][str(interaction.user.id)] = sel_values(
            interaction, self.children[0])[0]
        save_data()
        await interaction.response.edit_message(embed=self._embed(state),
                                                view=self)


class _AttendanceModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="📅 出欠確認を作成")
        self.title_input = discord.ui.TextInput(label="イベント名",
                                                max_length=100)
        self.when_input = discord.ui.TextInput(label="日時など", max_length=100,
                                               required=False)
        self.add_item(self.title_input)
        self.add_item(self.when_input)

    async def on_submit(self, interaction):
        state = {"title": str(self.title_input.value)[:100],
                 "when": str(self.when_input.value or ""), "answers": {}}
        view = AttendanceView()
        msg = await interaction.channel.send(embed=view._embed(state), view=view)
        guild_data(interaction.guild.id).setdefault(
            "attendances", {})[str(msg.id)] = state
        save_data()
        await interaction.response.send_message("📅 出欠確認を作成しました。",
                                                ephemeral=True)


class AttendancePanelView(discord.ui.View):
    def __init__(self, guild_id=None):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="mega_attendance:new", placeholder="📅 出欠確認を作る",
            options=[discord.SelectOption(label="📅 新しい出欠確認を作る",
                                          value="new")])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.guild is None or not feature_enabled(
                interaction.guild.id, "attendance"):
            return await interaction.response.send_message(
                "⚠️ 出欠確認は無効です。", ephemeral=True)
        await interaction.response.send_modal(_AttendanceModal())


register_panel_refresher(_make_refresher(
    "attendance_panel", build_attendance_embed,
    lambda gid: AttendancePanelView(gid)))


@_GK.command(name="出欠パネル設置", description="出欠確認パネルを設置する（管理者用）")
async def cmd_attendance_panel(interaction):
    if interaction.guild is None or not is_privileged(interaction.user):
        return await interaction.response.send_message(
            "⚠️ 設置は管理者だけが使えます。", ephemeral=True)
    await _install_panel(interaction, "attendance_panel",
                         build_attendance_embed(interaction.guild.id),
                         AttendancePanelView(interaction.guild.id))
    await interaction.response.send_message("📅 出欠パネルを設置しました。",
                                            ephemeral=True)


# ---------------------------------------------------------------- 順番 / チーム分け
register_feature("shuffle", CAT, "順番決め", "🔀",
                 "名前の順番をランダムに決める。")
register_feature("team", CAT, "チーム分け", "👥",
                 "名前をランダムにチーム分けする。")


def _names(text):
    return [n.strip() for n in text.replace("、", " ").replace(",", " ")
            .replace("\n", " ").split(" ") if n.strip()]


@_GE.command(name="順番決め", description="順番をランダムに決める")
@discord.app_commands.describe(名前="名前を空白区切りで")
async def cmd_shuffle(interaction, 名前: str):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "shuffle"):
        return await interaction.response.send_message(
            "⚠️ 順番決めは無効です。", ephemeral=True)
    names = _names(名前)
    if len(names) < 2:
        return await interaction.response.send_message(
            "⚠️ 名前を2つ以上入れてね。", ephemeral=True)
    random.shuffle(names)
    await interaction.response.send_message(
        "🔀 順番が決まりました！\n"
        + "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1)))


@_GE.command(name="チーム分け", description="ランダムにチーム分けする")
@discord.app_commands.describe(名前="名前を空白区切りで", チーム数="チームの数")
async def cmd_team(interaction, 名前: str, チーム数: int = 2):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "team"):
        return await interaction.response.send_message(
            "⚠️ チーム分けは無効です。", ephemeral=True)
    names = _names(名前)
    n = max(2, min(10, int(チーム数)))
    if len(names) < n:
        return await interaction.response.send_message(
            "⚠️ 人数がチーム数より少ないです。", ephemeral=True)
    random.shuffle(names)
    teams = [[] for _ in range(n)]
    for i, name in enumerate(names):
        teams[i % n].append(name)
    embed = discord.Embed(title="👥 チーム分け結果", color=discord.Color.teal())
    for i, team in enumerate(teams, 1):
        embed.add_field(name=f"チーム {i}", value="、".join(team), inline=False)
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------- カウントダウン
register_feature("countdown", CAT, "カウントダウン", "⏰",
                 "指定日時にチャンネルへお知らせする。")


@_GE.command(name="カウントダウン", description="指定日時にお知らせを予約する")
@discord.app_commands.describe(タイトル="お知らせ内容", 日時="YYYY-MM-DD HH:MM")
async def cmd_countdown(interaction, タイトル: str, 日時: str):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "countdown"):
        return await interaction.response.send_message(
            "⚠️ カウントダウンは無効です。", ephemeral=True)
    dt = _parse_dt(日時)
    if dt is None or dt <= jst_now():
        return await interaction.response.send_message(
            "⚠️ 日時は未来で「2026-12-31 20:00」の形で入れてね。",
            ephemeral=True)
    items = guild_data(interaction.guild.id).setdefault("countdowns", [])
    items.append({"title": タイトル[:100], "at": dt.isoformat(),
                  "channel_id": interaction.channel.id})
    save_data()
    await interaction.response.send_message(
        f"⏰ {dt.strftime('%Y-%m-%d %H:%M')} に「{タイトル}」をお知らせします。",
        ephemeral=True)


@tasks.loop(seconds=30)
async def _events_loop():
    from datetime import datetime
    for gid_str in list(guild_data_all()):
        gid = int(gid_str)
        data = guild_data(gid)
        changed = False
        for msg_id, entry in list(data.get("giveaways", {}).items()):
            if entry.get("done"):
                continue
            try:
                ends = datetime.fromisoformat(entry["ends_at"])
            except Exception:
                continue
            if ends <= jst_now():
                await _draw_giveaway(gid, msg_id)
                changed = True
        items = data.get("countdowns", [])
        keep = []
        for item in items:
            try:
                at = datetime.fromisoformat(item["at"])
            except Exception:
                continue
            if at <= jst_now():
                channel = bot.get_channel(int(item["channel_id"]))
                if channel is not None:
                    try:
                        await channel.send(f"⏰ **{item['title']}**")
                    except Exception:
                        pass
                changed = True
            else:
                keep.append(item)
        if len(keep) != len(items):
            data["countdowns"] = keep
            changed = True
        if changed:
            save_data()


def guild_data_all():
    from core import data_store
    return data_store.data.keys()


@bot.listen("on_ready")
async def _start_events_loop():
    if not _events_loop.is_running():
        _events_loop.start()
