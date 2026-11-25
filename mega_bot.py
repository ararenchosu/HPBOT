# 超高機能BOT 起動ファイル
# 機能モジュールはここに import を足すだけで有効になる。
import discord

import core
from core import FEATURES, TOKEN, bot

import hub  # noqa: F401  （/設定・/ヘルプ・エレベーターパネル）
import joinleave  # noqa: F401  （入退室通知）
import gate  # noqa: F401  （認証ゲート）
import tickets  # noqa: F401  （チケット）

bot.add_view(hub.ElevatorPanelView())  # 常時設置パネルを再起動後も有効に
bot.add_view(gate.GatePanelView())
bot.add_view(tickets.TicketPanelView())
bot.add_view(tickets.TicketManageView())


@bot.tree.command(name="ボット情報", description="このBOTの情報を表示する")
async def cmd_botinfo(interaction):
    enabled = 0
    if interaction.guild is not None:
        from core import feature_cfg
        enabled = sum(1 for k in FEATURES if feature_cfg(interaction.guild.id, k).get("enabled"))
    embed = discord.Embed(title="🤖 ボット情報", color=discord.Color.blurple())
    embed.add_field(name="稼働サーバー数", value=f"{len(bot.guilds)} 件", inline=True)
    embed.add_field(name="コマンド数", value=f"{len(bot.tree.get_commands())} 件", inline=True)
    embed.add_field(name="機能数", value=f"{len(FEATURES)} 件", inline=True)
    if interaction.guild is not None:
        embed.add_field(name="このサーバーで有効な機能", value=f"{enabled} 件", inline=True)
    embed.set_footer(text="設定は /設定（管理者用）、説明は /ヘルプ から")
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(".env に MEGA_DISCORD_TOKEN を設定してね")
    bot.run(TOKEN)
