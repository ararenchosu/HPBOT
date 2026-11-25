# 機能群: エンタメ（おみくじ系/運勢/サイコロ/じゃんけん/数当て/診断など）
import random

import discord

from core import (bot, feature_enabled, jst_now, register_feature, save_data,
                  user_data,
                  command_group)

CAT = "entame"

_G = command_group("entame", "エンタメ", "エンタメ機能")


def _on(interaction, feature):
    return (interaction.guild is not None
            and feature_enabled(interaction.guild.id, feature))


async def _off(interaction, name):
    await interaction.response.send_message(
        f"⚠️ {name}は無効です。", ephemeral=True)


_FORTUNES = [("大吉", 5), ("中吉", 15), ("小吉", 20), ("吉", 25),
             ("末吉", 20), ("凶", 10), ("大凶", 5)]


def _draw_fortune(seed=None):
    rng = random.Random(seed) if seed else random
    total = sum(w for _, w in _FORTUNES)
    roll = rng.randint(1, total)
    for name, w in _FORTUNES:
        roll -= w
        if roll <= 0:
            return name
    return "吉"


def _omikuji_feature(key, name, label, comment_map):
    register_feature(key, CAT, name, "🎋", f"{label}を引く。")

    @_G.command(name=name, description=f"{label}を引く")
    async def _cmd(interaction):
        if not _on(interaction, key):
            return await _off(interaction, name)
        result = _draw_fortune()
        embed = discord.Embed(
            title=f"🎋 {label}", description=f"# {result}",
            color=discord.Color.pink())
        embed.set_footer(text=comment_map.get(result, ""))
        await interaction.response.send_message(embed=embed)


_omikuji_feature("omikuji", "おみくじ", "おみくじ", {
    "大吉": "最高の1日になりそう！", "中吉": "いいことありそう。",
    "小吉": "小さな幸せが見つかるかも。", "吉": "穏やかな1日。",
    "末吉": "焦らずいこう。", "凶": "今日は慎重に。", "大凶": "無理せず休もう。"})
_omikuji_feature("love", "恋みくじ", "恋みくじ", {
    "大吉": "恋の予感…！", "中吉": "一歩踏み出すチャンス。",
    "小吉": "小さな進展あり。", "吉": "自然体が一番。", "末吉": "焦りは禁物。",
    "凶": "今日は様子見。", "大凶": "自分磨きの日にしよう。"})
_omikuji_feature("money", "金運みくじ", "金運みくじ", {
    "大吉": "思わぬ臨時収入の予感！", "中吉": "お財布に優しい日。",
    "小吉": "小さな節約が効く。", "吉": "堅実にいこう。", "末吉": "衝動買いに注意。",
    "凶": "大きな買い物は延期。", "大凶": "財布の紐を固く。"})


register_feature("fortune", CAT, "今日の運勢", "🌟",
                 "今日の運勢を総合表示する（1日固定）。")


@_G.command(name="今日の運勢", description="今日の運勢を見る")
async def cmd_fortune(interaction):
    if not _on(interaction, "fortune"):
        return await _off(interaction, "今日の運勢")
    seed = f"{interaction.user.id}:{jst_now().date().isoformat()}"
    rng = random.Random(seed)

    def stars():
        return "★" * rng.randint(1, 5) + "☆" * 0

    embed = discord.Embed(title=f"🌟 {interaction.user.display_name} の今日の運勢",
                          color=discord.Color.gold())
    embed.add_field(name="総合運", value="★" * rng.randint(1, 5), inline=True)
    embed.add_field(name="恋愛運", value="★" * rng.randint(1, 5), inline=True)
    embed.add_field(name="金運", value="★" * rng.randint(1, 5), inline=True)
    embed.add_field(name="ラッキーアイテム",
                    value=rng.choice(["青いハンカチ", "新しい靴下", "温かいお茶",
                                      "お気に入りの曲", "小さな花", "笑顔"]),
                    inline=False)
    embed.add_field(name="ラッキーカラー",
                    value=rng.choice(["赤", "青", "黄色", "緑", "紫", "白", "黒"]),
                    inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


register_feature("dice", CAT, "サイコロ", "🎲", "サイコロを振る。")


@_G.command(name="サイコロ", description="サイコロを振る")
@discord.app_commands.describe(面="サイコロの面数", 個数="振る個数")
async def cmd_dice(interaction, 面: int = 6, 個数: int = 1):
    if not _on(interaction, "dice"):
        return await _off(interaction, "サイコロ")
    sides = max(2, min(1000, int(面)))
    count = max(1, min(20, int(個数)))
    rolls = [random.randint(1, sides) for _ in range(count)]
    await interaction.response.send_message(
        f"🎲 {'、'.join(str(r) for r in rolls)}"
        + (f"（合計 {sum(rolls)}）" if count > 1 else ""))


register_feature("coinflip", CAT, "コイントス", "🪙", "コインを投げる。")


@_G.command(name="コイントス", description="コインを投げる")
async def cmd_coinflip(interaction):
    if not _on(interaction, "coinflip"):
        return await _off(interaction, "コイントス")
    await interaction.response.send_message(
        f"🪙 結果は… **{random.choice(['表', '裏'])}**！")


register_feature("janken", CAT, "じゃんけん", "✊", "BOTとじゃんけんする。")


class JankenView(discord.ui.View):
    HANDS = ["グー", "チョキ", "パー"]

    def __init__(self, gid, uid):
        super().__init__(timeout=120)
        self.gid = gid
        self.uid = uid
        sel = discord.ui.Select(
            placeholder="✊ 手を選ぶ",
            options=[discord.SelectOption(label=h, value=h) for h in self.HANDS])
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction):
        if interaction.user.id != self.uid:
            return
        mine = interaction.data["values"][0] if interaction.data else "グー"
        bot_hand = random.choice(self.HANDS)
        u = user_data(self.gid, self.uid)
        if mine == bot_hand:
            result = "あいこ！"
        elif (self.HANDS.index(mine) - self.HANDS.index(bot_hand)) % 3 == 2:
            result = "🎉 あなたの勝ち！"
            u["janken_wins"] = int(u.get("janken_wins") or 0) + 1
        else:
            result = "💦 BOTの勝ち…"
            u["janken_losses"] = int(u.get("janken_losses") or 0) + 1
        save_data()
        await interaction.response.edit_message(
            content=f"あなた: {mine} / BOT: {bot_hand}\n{result}"
                    f"（通算 {u.get('janken_wins', 0)} 勝 "
                    f"{u.get('janken_losses', 0)} 敗）",
            view=None)


@_G.command(name="じゃんけん", description="BOTとじゃんけんする")
async def cmd_janken(interaction):
    if not _on(interaction, "janken"):
        return await _off(interaction, "じゃんけん")
    await interaction.response.send_message(
        "✊ じゃんけん…", view=JankenView(interaction.guild.id,
                                          interaction.user.id),
        ephemeral=True)


register_feature("memberroulette", CAT, "メンバールーレット", "🎡",
                 "メンバーからランダムに1人選ぶ。")


@_G.command(name="メンバールーレット", description="メンバーをランダムに1人選ぶ")
async def cmd_memberroulette(interaction):
    if not _on(interaction, "memberroulette"):
        return await _off(interaction, "メンバールーレット")
    members = [m for m in interaction.guild.members if not m.bot]
    if not members:
        return await interaction.response.send_message(
            "⚠️ メンバーがいません。", ephemeral=True)
    pick = random.choice(members)
    await interaction.response.send_message(
        f"🎡 選ばれたのは… {pick.mention} さんです！")


register_feature("numberguess", CAT, "数当てゲーム", "🔢",
                 "1〜100の数字を当てるゲーム。",
                 help_text="/数当て開始 で開始、/数当て 数字 で回答。")

_guess_games = {}


@_G.command(name="数当て開始", description="数当てゲームを始める")
async def cmd_guess_start(interaction):
    if not _on(interaction, "numberguess"):
        return await _off(interaction, "数当てゲーム")
    _guess_games[(interaction.guild.id, interaction.user.id)] = {
        "answer": random.randint(1, 100), "tries": 0}
    await interaction.response.send_message(
        "🔢 1〜100の数字を決めました！ /数当て 数字 で当ててみてね。",
        ephemeral=True)


@_G.command(name="数当て", description="数字を当てる")
@discord.app_commands.describe(数字="予想する数字")
async def cmd_guess(interaction, 数字: int):
    if not _on(interaction, "numberguess"):
        return await _off(interaction, "数当てゲーム")
    key = (interaction.guild.id, interaction.user.id)
    game = _guess_games.get(key)
    if game is None:
        return await interaction.response.send_message(
            "⚠️ 先に /数当て開始 してね。", ephemeral=True)
    game["tries"] += 1
    guess = int(数字)
    if guess == game["answer"]:
        tries = game["tries"]
        del _guess_games[key]
        await interaction.response.send_message(
            f"🎉 正解！ {tries} 回で当てました！")
    elif guess < game["answer"]:
        await interaction.response.send_message("🔢 もっと大きいよ。",
                                                ephemeral=True)
    else:
        await interaction.response.send_message("🔢 もっと小さいよ。",
                                                ephemeral=True)


register_feature("emojislot", CAT, "絵文字スロット", "🍒",
                 "無料で遊べる絵文字スロット。")


@_G.command(name="絵文字スロット", description="絵文字スロットを回す")
async def cmd_emojislot(interaction):
    if not _on(interaction, "emojislot"):
        return await _off(interaction, "絵文字スロット")
    faces = [random.choice(["🍒", "🍋", "🔔", "⭐", "💎", "🍀"])
             for _ in range(3)]
    if faces[0] == faces[1] == faces[2]:
        msg = "🎉 大当たり！！"
    elif len(set(faces)) == 2:
        msg = "✨ 惜しい！2つ揃った！"
    else:
        msg = "💦 ハズレ"
    await interaction.response.send_message(
        f"🍒 {' | '.join(faces)}\n{msg}")


register_feature("eightball", CAT, "8ボール", "🎱",
                 "質問にランダムに答える魔法の8ボール。")

_BALL = ["間違いなくYes", "たぶんYes", "今は分からない", "たぶんNo",
         "絶対にNo", "兆しは良い", "もう一度聞いて", "期待していい",
         "雲行きが怪しい", "Yesと言える"]


@_G.command(name="8ボール", description="8ボールに聞く")
@discord.app_commands.describe(質問="Yes/Noで答えられる質問")
async def cmd_eightball(interaction, 質問: str):
    if not _on(interaction, "eightball"):
        return await _off(interaction, "8ボール")
    await interaction.response.send_message(
        f"🎱 Q: {質問}\nA: **{random.choice(_BALL)}**")


register_feature("shindan", CAT, "診断", "🔍",
                 "名前からランダムに診断する。")

_SHINDAN = [
    "{name}の今日のタイプは「{a}」！ {b}",
    "{name}は実は「{a}」の才能の持ち主。{b}",
    "{name}のラッキー行動は「{a}」。{b}",
]
_SHINDAN_A = ["天才クリエイター", "癒し系リーダー", "無敵の挑戦者",
              "影の立役者", "ムードメーカー", "戦略家"]
_SHINDAN_B = ["自信を持っていこう。", "周りが味方してくれる日。",
              "一歩踏み出すと運が開ける。", "休むことも大事。"]


@_G.command(name="診断", description="名前で診断する")
@discord.app_commands.describe(名前="診断したい名前")
async def cmd_shindan(interaction, 名前: str):
    if not _on(interaction, "shindan"):
        return await _off(interaction, "診断")
    rng = random.Random(f"shindan:{名前}:{jst_now().date().isoformat()}")
    text = rng.choice(_SHINDAN).format(
        name=名前, a=rng.choice(_SHINDAN_A), b=rng.choice(_SHINDAN_B))
    await interaction.response.send_message(f"🔍 {text}")


register_feature("aishou", CAT, "相性診断", "💕", "2人の相性を占う。")


@_G.command(name="相性診断", description="2人の相性を占う")
@discord.app_commands.describe(名前a="1人目", 名前b="2人目")
async def cmd_aishou(interaction, 名前a: str, 名前b: str):
    if not _on(interaction, "aishou"):
        return await _off(interaction, "相性診断")
    pair = ":".join(sorted([名前a, 名前b]))
    rng = random.Random(f"aishou:{pair}:{jst_now().date().isoformat()}")
    value = rng.randint(0, 100)
    comment = ("運命の相手かも！" if value >= 90 else
               "とても良い相性。" if value >= 70 else
               "仲良くなれそう。" if value >= 40 else
               "これから育てる相性。")
    await interaction.response.send_message(
        f"💕 {名前a} × {名前b} の相性は **{value}%**！ {comment}")
