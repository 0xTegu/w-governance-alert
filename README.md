# Wormhole Governance Discord Bot

A Discord bot that monitors Wormhole governance proposals and sends alerts to a designated channel when new proposals are created.

## Features

- 🔍 Monitors Wormhole governance proposals in real-time
- 📢 Sends automatic alerts for new proposals
- 📊 Shows proposal status, voting stats, and time remaining
- 🎨 Color-coded embeds based on proposal status
- 📈 Progress bars for vote visualization
- 🔗 Direct links to view proposals on Tally
- 🎯 Commands to list active proposals and check specific proposals
- 👤 Optional Tally API integration for additional proposal details (proposer info, creation date)
- 💾 Database tracking to prevent re-announcing proposals on restart
- 🔄 Live mode toggle for different announcement behaviors

## Requirements

- Python 3.8+
- Discord Bot Token
- Discord Server with appropriate permissions
- (Optional) Tally API Key for enhanced features

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd w-governance-alert
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your configuration:
```bash
cp .env.example .env
```

4. Edit `.env` with your values:
```
# Discord Bot Configuration (Required)
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_GUILD_ID=your_discord_guild_id_here
PROPOSALS_CHANNEL_ID=your_channel_id_here

# Tally API Configuration (Optional)
# Get your API key from https://www.tally.xyz/user/settings
TALLY_API_KEY=your_tally_api_key_here

# LIVE_MODE Settings
LIVE_MODE=false  # Set to true to announce all active proposals on startup
```

## Bot Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot user and copy the token
3. Invite the bot to your server with appropriate permissions (Send Messages, Embed Links, Read Message History)
4. Create a channel for governance alerts and copy its ID

## Tally API Integration (Optional)

The bot can fetch additional proposal details from Tally API:
- Proposer name and profile link
- Proposal creation date
- Organization details

To enable this feature:
1. Sign in to Tally at https://www.tally.xyz
2. Go to your user settings
3. Generate an API key
4. Add it to your `.env` file

The bot will work without a Tally API key, but with limited features.

## LIVE_MODE Settings

- **`LIVE_MODE=false` (default)**: The bot tracks announced proposals in a SQLite database and only announces new proposals that haven't been announced before. This prevents re-announcing proposals when the bot restarts.

- **`LIVE_MODE=true`**: The bot announces all active proposals on startup, ignoring the database. Use this mode if you want to re-announce all active proposals every time the bot starts.

## Usage

Run the bot:
```bash
python tally_bot.py
```

The bot will:
- Check for new proposals every 5 minutes
- Send alerts to the configured channel when new active proposals are found
- Respond to commands in Discord

## Discord Commands

- `!proposals` - List all active governance proposals
- `!proposal <number>` - Get details about a specific proposal (use the number from the proposals list)
- `!db_stats` - Show database statistics (total announced proposals, today's count)
- `!clear_db` - Clear the announced proposals database (admin only, disabled in LIVE_MODE)

## Proposal Status Colors

- 🟢 Active/Voting - Green
- 🟡 Pending/Queued - Yellow  
- 🔴 Defeated/Canceled - Red
- ⚫ Other - Default

## Database

The bot uses a SQLite database (`announced_proposals.db`) to track which proposals have been announced. This database is automatically created on first run and is ignored by git.

The database stores:
- Proposal ID
- Announcement timestamp
- Proposal title
- Proposal status
- Tally ID

## Bot Architecture

- Uses `aiohttp` for async API requests
- Implements rate limiting for Tally API (1 request per 1.1 seconds)
- Caches announced proposals to avoid duplicates
- Gracefully handles missing Tally API key

## Troubleshooting

- **Bot not responding**: Check that the bot token is correct and the bot is invited to your server
- **No alerts**: Verify the channel ID is correct and the bot has permissions to send messages
- **Tally details missing**: Ensure your Tally API key is valid and properly set in `.env`
- **Rate limit errors**: The bot implements automatic rate limiting, but excessive requests may still cause issues

## Contributing

Feel free to submit issues and enhancement requests!
