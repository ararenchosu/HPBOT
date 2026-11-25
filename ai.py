# 機能群: AI（AIチャット/AI要約/翻訳）
import asyncio
import json
import urllib.parse
import urllib.request

import discord

from core import bot, feature_cfg, feature_enabled, register_feature, command_group

CAT = "ai"

_G = command_group("ai", "ai", "AI機能")


def _post_json(url, payload, api_key):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "curl"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


async def _chat(gid, messages):
    cfg = feature_cfg(gid, "aichat")
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return None
    payload = {"model": cfg.get("model") or "gpt-4o-mini",
               "messages": messages}
    data = await asyncio.to_thread(
        _post_json, "https://api.openai.com/v1/chat/completions",
        payload, api_key)
    return data["choices"][0]["message"]["content"]


register_feature(
    "aichat", CAT, "AIチャット", "🤖",
    "AIに質問できる（OpenAI APIキーが必要）。",
    settings=[
        {"key": "api_key", "label": "OpenAI APIキー", "type": "text",
         "default": ""},
        {"key": "model", "label": "モデル名", "type": "text",
         "default": "gpt-4o-mini"},
        {"key": "system", "label": "システムプロンプト", "type": "text",
         "style": "long",
         "default": "あなたは親切なアシスタントです。日本語で簡潔に答えてください。"},
    ])


@_G.command(name="aiに質問", description="AIに質問する")
@discord.app_commands.describe(質問="聞きたいこと")
async def cmd_aichat(interaction, 質問: str):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "aichat"):
        return await interaction.response.send_message(
            "⚠️ AIチャットは無効です。", ephemeral=True)
    cfg = feature_cfg(interaction.guild.id, "aichat")
    if not (cfg.get("api_key") or "").strip():
        return await interaction.response.send_message(
            "⚠️ APIキーが未設定です（管理者が /設定 で設定）。", ephemeral=True)
    await interaction.response.defer()
    try:
        answer = await _chat(interaction.guild.id, [
            {"role": "system", "content": cfg.get("system") or ""},
            {"role": "user", "content": 質問[:2000]}])
    except Exception:
        return await interaction.followup.send(
            "⚠️ AIへの問い合わせに失敗しました。")
    await interaction.followup.send(
        f"🤖 **Q: {質問[:100]}**\n{answer[:1800]}")


register_feature("aisummary", CAT, "AI要約", "📝",
                 "チャンネルの直近の会話をAIが要約する（AIチャットのキーを使用）。")


@_G.command(name="要約", description="このチャンネルの会話を要約する")
@discord.app_commands.describe(件数="さかのぼる件数（最大100）")
async def cmd_summary(interaction, 件数: int = 50):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "aisummary"):
        return await interaction.response.send_message(
            "⚠️ AI要約は無効です。", ephemeral=True)
    cfg = feature_cfg(interaction.guild.id, "aichat")
    if not (cfg.get("api_key") or "").strip():
        return await interaction.response.send_message(
            "⚠️ AIチャットのAPIキーが未設定です。", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        lines = []
        async for msg in interaction.channel.history(
                limit=max(10, min(100, int(件数)))):
            if not msg.author.bot and msg.content:
                lines.append(f"{msg.author.display_name}: {msg.content[:200]}")
        lines.reverse()
        if not lines:
            return await interaction.followup.send(
                "⚠️ 要約できる発言がありません。", ephemeral=True)
        answer = await _chat(interaction.guild.id, [
            {"role": "system",
             "content": "次の会話ログを日本語で簡潔に要約してください。"},
            {"role": "user", "content": "\n".join(lines)[:8000]}])
        await interaction.followup.send(
            f"📝 **要約**\n{answer[:1800]}", ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "⚠️ 要約に失敗しました。", ephemeral=True)


register_feature("translate", CAT, "翻訳", "🌐",
                 "テキストを翻訳する（無料API使用）。")

_LANGS = {"英語": "en", "日本語": "ja", "韓国語": "ko", "中国語": "zh-CN"}


@_G.command(name="翻訳", description="テキストを翻訳する")
@discord.app_commands.describe(テキスト="翻訳したい文", 言語="翻訳先の言語")
@discord.app_commands.choices(言語=[
    discord.app_commands.Choice(name=k, value=k) for k in _LANGS])
async def cmd_translate(interaction, テキスト: str, 言語: str = "英語"):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "translate"):
        return await interaction.response.send_message(
            "⚠️ 翻訳は無効です。", ephemeral=True)
    target = _LANGS.get(言語, "en")
    source = "en" if target == "ja" else "ja"
    await interaction.response.defer(ephemeral=True)
    try:
        url = ("https://api.mymemory.translated.net/get?q="
               + urllib.parse.quote(テキスト[:500])
               + f"&langpair={source}|{target}")
        data = await asyncio.to_thread(_get_json, url)
        translated = data["responseData"]["translatedText"]
        await interaction.followup.send(
            f"🌐 {translated[:1900]}", ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "⚠️ 翻訳に失敗しました。", ephemeral=True)
