# 機能群: VC（入退室通知/人数カウンター/一時VC/読み上げ）
import asyncio
import os
import re
import shutil
import tempfile
import time

import discord

from core import (BASE_DIR, bot, feature_cfg, feature_enabled,
                  register_feature,
                  command_group)

CAT = "vc"

_G = command_group("vc", "ボイス", "VC・読み上げ機能")


# ---------------------------------------------------------------- VC入退室通知
register_feature(
    "vcnotify", CAT, "VC入退室通知", "🔊",
    "ボイスチャンネルの入退室を通知する。",
    settings=[{"key": "channel_id", "label": "通知チャンネル",
               "type": "channel", "default": None}])


@bot.listen("on_voice_state_update")
async def _vc_notify(member, before, after):
    gid = member.guild.id
    try:
        if feature_enabled(gid, "vcnotify"):
            cfg = feature_cfg(gid, "vcnotify")
            cid = cfg.get("channel_id")
            channel = member.guild.get_channel(int(cid)) if cid else None
            if channel is not None:
                if before.channel is None and after.channel is not None:
                    await channel.send(
                        f"🔊 {member.mention} が {after.channel.mention} に"
                        "入室しました。")
                elif before.channel is not None and after.channel is None:
                    await channel.send(
                        f"🔇 {member.mention} が {before.channel.mention} から"
                        "退出しました。")
    except Exception:
        pass
    await _vccounter_update(member, before, after)
    await _tempvc_update(member, before, after)


# ---------------------------------------------------------------- VC人数カウンター
register_feature(
    "vccounter", CAT, "VC人数カウンター", "🔢",
    "VCチャンネル名に現在の人数を表示する。",
    settings=[{"key": "channel_id", "label": "対象VCチャンネル（名前が変わります）",
               "type": "channel", "default": None},
              {"key": "format", "label": "名前の形式（{count}=人数）",
               "type": "text", "default": "🔊 通話中: {count}人"}])

_counter_last = {}


async def _vccounter_update(member, before, after):
    gid = member.guild.id
    try:
        if not feature_enabled(gid, "vccounter"):
            return
        cfg = feature_cfg(gid, "vccounter")
        cid = cfg.get("channel_id")
        if not cid:
            return
        channel = member.guild.get_channel(int(cid))
        if channel is None:
            return
        if before.channel != channel and after.channel != channel:
            return
        now = time.monotonic()
        if now - _counter_last.get(gid, 0) < 300:
            return
        _counter_last[gid] = now
        name = (cfg.get("format") or "🔊 通話中: {count}人").replace(
            "{count}", str(len(channel.members)))
        if channel.name != name:
            await channel.edit(name=name[:100])
    except Exception:
        pass


# ---------------------------------------------------------------- 一時VC
register_feature(
    "tempvc", CAT, "一時VC", "🎙️",
    "ロビーVCに入ると自分専用VCが自動で作られる。",
    settings=[{"key": "lobby_id", "label": "ロビーVCチャンネル",
               "type": "channel", "default": None},
              {"key": "name", "label": "作られるVC名（{user}=名前）",
               "type": "text", "default": "🎙️ {user} の部屋"}])

_temp_channels = set()


async def _tempvc_update(member, before, after):
    gid = member.guild.id
    try:
        if not feature_enabled(gid, "tempvc"):
            return
        cfg = feature_cfg(gid, "tempvc")
        lobby_id = cfg.get("lobby_id")
        if (after.channel is not None and lobby_id
                and after.channel.id == int(lobby_id)):
            name = (cfg.get("name") or "🎙️ {user} の部屋").replace(
                "{user}", member.display_name)[:100]
            channel = await member.guild.create_voice_channel(
                name=name, category=after.channel.category)
            _temp_channels.add(channel.id)
            try:
                await member.move_to(channel)
            except Exception:
                pass
        for ch_id in list(_temp_channels):
            channel = member.guild.get_channel(ch_id)
            if channel is None:
                _temp_channels.discard(ch_id)
                continue
            if len(channel.members) == 0:
                _temp_channels.discard(ch_id)
                try:
                    await channel.delete()
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------- 読み上げ
register_feature(
    "tts", CAT, "読み上げ", "🗣️",
    "VCでテキストを読み上げる（edge-tts が必要）。",
    settings=[
        {"key": "channel_id", "label": "読み上げ対象テキストチャンネル",
         "type": "channel", "default": None},
        {"key": "voice", "label": "声", "type": "choice",
         "default": "ja-JP-NanamiNeural",
         "options": [("ja-JP-NanamiNeural", "七海（女性）"),
                     ("ja-JP-KeitaNeural", "圭太（男性）")]},
        {"key": "read_vc_chat", "label": "VC内チャットも読む", "type": "toggle",
         "default": True},
    ],
    help_text="/接続 でVCに入り、/切断 で出ます。対象チャンネルの発言を"
              "読み上げます。")

_tts_queues = {}


def _ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


async def _tts_worker(gid):
    queue = _tts_queues[gid]
    while True:
        text, voice_client = await queue.get()
        try:
            import edge_tts
            cfg = feature_cfg(gid, "tts")
            path = os.path.join(tempfile.gettempdir(), f"mega_tts_{gid}.mp3")
            communicate = edge_tts.Communicate(
                text, cfg.get("voice") or "ja-JP-NanamiNeural")
            await communicate.save(path)
            if voice_client and voice_client.is_connected():
                source = discord.FFmpegPCMAudio(path, executable=_ffmpeg())
                voice_client.play(source)
                while voice_client.is_playing():
                    await asyncio.sleep(0.3)
        except Exception:
            pass
        finally:
            queue.task_done()


def _clean_tts_text(content):
    text = re.sub(r"https?://\S+", "URL", content)
    text = re.sub(r"<@!?\d+>", "", text)
    text = re.sub(r"<#\d+>", "", text)
    text = re.sub(r"<a?:\w+:\d+>", "", text)
    return text.strip()[:200]


@bot.listen("on_message")
async def _tts_listener(message):
    if message.guild is None or message.author.bot:
        return
    gid = message.guild.id
    if not feature_enabled(gid, "tts"):
        return
    voice_client = message.guild.voice_client
    if voice_client is None or not voice_client.is_connected():
        return
    cfg = feature_cfg(gid, "tts")
    linked = cfg.get("channel_id")
    is_linked = linked and int(linked) == message.channel.id
    is_vc_chat = (cfg.get("read_vc_chat", True)
                  and voice_client.channel is not None
                  and message.channel.id == voice_client.channel.id)
    if not (is_linked or is_vc_chat):
        return
    text = _clean_tts_text(message.content or "")
    if not text:
        return
    queue = _tts_queues.setdefault(gid, asyncio.Queue())
    queue.put_nowait((f"{message.author.display_name}、{text}", voice_client))
    if not any(t.get_name() == f"tts-{gid}" for t in asyncio.all_tasks()):
        asyncio.create_task(_tts_worker(gid), name=f"tts-{gid}")


@_G.command(name="接続", description="VCに接続して読み上げを開始する")
async def cmd_tts_join(interaction):
    if interaction.guild is None or not feature_enabled(
            interaction.guild.id, "tts"):
        return await interaction.response.send_message(
            "⚠️ 読み上げは無効です。", ephemeral=True)
    voice = getattr(interaction.user, "voice", None)
    if voice is None or voice.channel is None:
        return await interaction.response.send_message(
            "⚠️ 先にVCへ入ってね。", ephemeral=True)
    try:
        if interaction.guild.voice_client is None:
            await voice.channel.connect()
        else:
            await interaction.guild.voice_client.move_to(voice.channel)
    except Exception:
        return await interaction.response.send_message(
            "⚠️ VCに接続できませんでした。", ephemeral=True)
    await interaction.response.send_message(
        f"🗣️ {voice.channel.mention} に接続しました。", ephemeral=True)


@_G.command(name="切断", description="VCから切断する")
async def cmd_tts_leave(interaction):
    if interaction.guild is None:
        return
    voice_client = interaction.guild.voice_client
    if voice_client is not None:
        await voice_client.disconnect()
    await interaction.response.send_message("🗣️ 切断しました。", ephemeral=True)
