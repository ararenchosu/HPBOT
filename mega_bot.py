# 超高機能BOT 起動ファイル
# 機能モジュールはここに import を足すだけで有効になる。
import discord

import core
from core import FEATURES, TOKEN, bot

import hub  # noqa: F401  （/設定・/ヘルプ・エレベーターパネル）
import joinleave  # noqa: F401  （入退室通知）
import gate  # noqa: F401  （認証ゲート）
import tickets  # noqa: F401  （チケット）
import moderation  # noqa: F401  （モデレーション）
import economy  # noqa: F401  （レベル・経済）
import social  # noqa: F401  （自己紹介・ロールパネル・通報など）
import events  # noqa: F401  （抽選・投票・募集など）
import automation  # noqa: F401  （自動化）
import tools  # noqa: F401  （便利ツール）
import fun  # noqa: F401  （エンタメ）
import vc  # noqa: F401  （VC・読み上げ）
import ai  # noqa: F401  （AI）
import stats  # noqa: F401  （分析）
import systemtools  # noqa: F401  （システム）

bot.add_view(hub.ElevatorPanelView())  # 常時設置パネルを再起動後も有効に
bot.add_view(gate.GatePanelView())
bot.add_view(tickets.TicketPanelView())
bot.add_view(tickets.TicketManageView())
bot.add_view(social.IntroPanelView())
bot.add_view(social.RolePanelView())
bot.add_view(social.ReportPanelView())
bot.add_view(social.SuggestionPanelView())
bot.add_view(social.QuestionPanelView())
bot.add_view(events.GiveawayView())
bot.add_view(events.PollView())
bot.add_view(events.SurveyView())
bot.add_view(events.RecruitView())
bot.add_view(events.RecruitPanelView())
bot.add_view(events.AttendanceView())
bot.add_view(events.AttendancePanelView())

for _group in core.all_command_groups():
    bot.tree.add_command(_group)


@bot.tree.command(name="ボット情報", description="このBOTの情報を表示する")
async def cmd_botinfo(interaction):
    enabled = 0
    if interaction.guild is not None:
        from core import feature_cfg
        enabled = sum(1 for k in FEATURES if feature_cfg(interaction.guild.id, k).get("enabled"))
    embed = discord.Embed(title="🤖 ボット情報", color=discord.Color.blurple())
    embed.add_field(name="稼働サーバー数", value=f"{len(bot.guilds)} 件", inline=True)
    embed.add_field(name="コマンド数", value=f"{core.total_command_count()} 件", inline=True)
    embed.add_field(name="機能数", value=f"{len(FEATURES)} 件", inline=True)
    if interaction.guild is not None:
        embed.add_field(name="このサーバーで有効な機能", value=f"{enabled} 件", inline=True)
    embed.set_footer(text="設定は /設定（管理者用）、説明は /ヘルプ から")
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(".env に MEGA_DISCORD_TOKEN を設定してね")
    bot.run(TOKEN)
