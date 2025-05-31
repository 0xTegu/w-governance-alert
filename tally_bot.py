import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import aiohttp
import json
import requests
from datetime import datetime, timezone
import collections
import asyncio
import re

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', 0))
PROPOSALS_CHANNEL_ID = int(os.getenv('PROPOSALS_CHANNEL_ID', 0))
WORMHOLE_API_URL = 'https://w.wormhole.com/api/governance/proposals'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store announced proposal IDs to avoid duplicates
announced_proposals = set()

class WormholeProposal:
    def __init__(self, proposal_data):
        self.id = proposal_data.get('id')
        self.tally_id = proposal_data.get('tally_id')
        self.tally_url = proposal_data.get('tally_url')
        self.title = proposal_data.get('title', 'N/A')
        self.description = proposal_data.get('description', 'N/A')
        self.status = proposal_data.get('status', 'N/A')
        self.total_votes = proposal_data.get('total_votes', 0)
        self.total_votes_for = proposal_data.get('total_votes_for', 0)
        self.total_votes_against = proposal_data.get('total_votes_against', 0)
        self.end_timestamp = proposal_data.get('end_timestamp', 0)

    @property
    def end_date(self):
        if self.end_timestamp:
            return datetime.fromtimestamp(self.end_timestamp / 1000, tz=timezone.utc)
        return None

    @property
    def is_active(self):
        # Consider proposals as active if they are pending, voting, or queued
        return self.status in ['pending', 'voting', 'queued', 'active']

    def extract_abstract(self):
        """Extract abstract from description or return truncated description"""
        # Remove any HTML/markdown formatting
        clean_text = re.sub(r'<[^>]+>', '', self.description)  # Remove HTML tags
        clean_text = re.sub(r'\*{1,2}([^\*]+)\*{1,2}', r'\1', clean_text)  # Remove bold/italic
        clean_text = re.sub(r'#+\s*', '', clean_text)  # Remove headers
        clean_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean_text)  # Remove links
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)  # Remove multiple newlines
        clean_text = clean_text.strip()

        # Remove the title if it appears at the beginning of the description
        if clean_text.startswith(self.title):
            clean_text = clean_text[len(self.title):].strip()

        # Remove common header patterns at the beginning of lines
        header_patterns = [
            r'^(?:Abstract|ABSTRACT|Summary|SUMMARY|Description|DESCRIPTION|Title|TITLE|Overview|OVERVIEW):?\s*\n?',
            r'\n(?:Abstract|ABSTRACT|Summary|SUMMARY|Description|DESCRIPTION|Title|TITLE|Overview|OVERVIEW):?\s*\n?',
        ]

        for pattern in header_patterns:
            clean_text = re.sub(pattern, '\n', clean_text, flags=re.MULTILINE | re.IGNORECASE)

        # Clean up any resulting multiple newlines or spaces
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
        clean_text = re.sub(r'^\s+', '', clean_text)
        clean_text = clean_text.strip()

        # Try to find abstract section content (after removing headers)
        abstract_patterns = [
            # Look for content that might be in an abstract section
            r'(?:^|\n)(.*?)(?:\n(?:[A-Z][a-z]+\s*[A-Z][a-z]+:|#{1,3}|\*{2})|$)',
        ]

        for pattern in abstract_patterns:
            match = re.search(pattern, clean_text, re.DOTALL)
            if match:
                abstract = match.group(1).strip()
                if abstract and len(abstract) > 50:  # Make sure we have meaningful content
                    clean_text = abstract
                    break

        # Enforce 280 character limit with "..." ending
        if len(clean_text) > 280:
            return clean_text[:277] + "..."
        elif len(clean_text) == 280:
            return clean_text[:277] + "..."
        else:
            # If text is shorter than 280, still add "..." if it seems truncated
            if len(self.description) > len(clean_text):
                return clean_text + "..."
            return clean_text

    def create_embed(self):
        """Create a Discord embed for the proposal"""
        # Use purple/violet color similar to the image
        embed = discord.Embed(
            title=self.title,
            color=0x8B5CF6,  # Purple/violet color
            url=self.tally_url
        )

        # Add description (abstract only)
        abstract = self.extract_abstract()
        embed.add_field(name="Description", value=abstract, inline=False)

        # Add status and voting info in a grid-like format
        embed.add_field(name="Status", value=self.status.capitalize(), inline=True)
        embed.add_field(name="Votes For", value=f"{self.total_votes_for:,.2f}", inline=True)
        embed.add_field(name="Votes Against", value=f"{self.total_votes_against:,.2f}", inline=True)

        if self.end_date:
            now = datetime.now(timezone.utc)
            if self.end_date < now:
                # Calculate how long ago it ended
                time_diff = now - self.end_date
                hours_ago = int(time_diff.total_seconds() / 3600)
                if hours_ago < 24:
                    time_str = f"{hours_ago} hours ago"
                else:
                    days_ago = hours_ago // 24
                    time_str = f"{days_ago} days ago"
                embed.add_field(name="Voting Ends", value=time_str, inline=False)
            else:
                # Show relative time until voting ends
                embed.add_field(
                    name="Voting Ends",
                    value=f"<t:{int(self.end_timestamp / 1000)}:R>",
                    inline=False
                )

        embed.set_footer(text=f"Proposal ID: {self.id}")
        
        # Add Wormhole logo as thumbnail
        embed.set_thumbnail(url="https://wormhole.com/images/wormhole-logo.png")
        
        return embed

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    check_new_proposals.start()

async def fetch_wormhole_proposals():
    """Fetch proposals from Wormhole API"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(WORMHOLE_API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('proposals', [])
                else:
                    print(f"Error fetching proposals: {response.status}")
                    return []
        except Exception as e:
            print(f"Error fetching proposals: {e}")
            return []

@tasks.loop(minutes=5)
async def check_new_proposals():
    """Check for new proposals every 5 minutes"""
    channel = bot.get_channel(PROPOSALS_CHANNEL_ID)
    if not channel:
        print(f"Channel with ID {PROPOSALS_CHANNEL_ID} not found")
        return

    proposals = await fetch_wormhole_proposals()
    print(f"Found {len(proposals)} total proposals")

    new_proposals = []
    for proposal_data in proposals:
        proposal = WormholeProposal(proposal_data)

        # Only announce active proposals that haven't been announced yet
        if proposal.is_active and proposal.id not in announced_proposals:
            new_proposals.append(proposal)
            announced_proposals.add(proposal.id)

    if new_proposals:
        print(f"Found {len(new_proposals)} new active proposals to announce")
        for proposal in new_proposals:
            embed = proposal.create_embed()
            await channel.send(embed=embed)
            await asyncio.sleep(1)  # Small delay between messages
    else:
        print("No new active proposals found")

@bot.command(name='proposals')
async def list_proposals(ctx):
    """List all active proposals"""
    proposals = await fetch_wormhole_proposals()
    active_proposals = [WormholeProposal(p) for p in proposals if WormholeProposal(p).is_active]

    if not active_proposals:
        await ctx.send("No active proposals found.")
        return

    for proposal in active_proposals[:5]:
        embed = proposal.create_embed()
        await ctx.send(embed=embed)
        await asyncio.sleep(1)

    if len(active_proposals) > 5:
        await ctx.send(f"And {len(active_proposals) - 5} more active proposals...")

@bot.command(name='proposal')
async def get_proposal(ctx, proposal_id: str):
    """Get details of a specific proposal by ID"""
    proposals = await fetch_wormhole_proposals()

    for proposal_data in proposals:
        if proposal_data.get('id') == proposal_id:
            proposal = WormholeProposal(proposal_data)
            embed = proposal.create_embed()
            await ctx.send(embed=embed)
            return

    await ctx.send(f"Proposal with ID {proposal_id} not found.")

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
