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
import sqlite3

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', 0))
PROPOSALS_CHANNEL_ID = int(os.getenv('PROPOSALS_CHANNEL_ID', 0))
WORMHOLE_API_URL = 'https://w.wormhole.com/api/governance/proposals'
LIVE_MODE = os.getenv('LIVE_MODE', 'false').lower() == 'true'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store announced proposal IDs to avoid duplicates
announced_proposals = set()

# Database setup
DATABASE_FILE = 'announced_proposals.db'

def init_database():
    """Initialize the database for tracking announced proposals"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS announced_proposals (
            id TEXT PRIMARY KEY,
            announced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            title TEXT,
            status TEXT,
            tally_id TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def load_announced_proposals():
    """Load previously announced proposals from database"""
    if LIVE_MODE:
        print("LIVE_MODE is enabled - ignoring database")
        return set()
        
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM announced_proposals')
    proposals = {row[0] for row in cursor.fetchall()}
    
    conn.close()
    print(f"Loaded {len(proposals)} previously announced proposals from database")
    return proposals

def save_announced_proposal(proposal):
    """Save an announced proposal to the database"""
    if LIVE_MODE:
        return  # Don't save to database in live mode
        
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO announced_proposals (id, title, status, tally_id)
        VALUES (?, ?, ?, ?)
    ''', (proposal.id, proposal.title, proposal.status, proposal.tally_id))
    
    conn.commit()
    conn.close()

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
        # Use darker background color similar to Discord dark theme
        embed = discord.Embed(
            title=self.title,
            color=0x2b2d31,  # Discord dark gray
            url=self.tally_url
        )

        # Calculate voting ends time first (we'll need it for the header fields)
        if self.end_date:
            # Format the end date in MM/DD/YYYY HH:MM UTC
            time_str = self.end_date.strftime("%m/%d/%Y %H:%M UTC")
        else:
            time_str = "Unknown"

        # Add author, status, and voting ends as inline fields at the top
        embed.add_field(name="Author", value="Governor2 (Placeholder)", inline=True)
        embed.add_field(name="Voting Ends", value=time_str, inline=True)
        embed.add_field(name="Status", value=self.status.capitalize(), inline=True)

        # Add description section
        abstract = self.extract_abstract()
        embed.add_field(name="Description", value=abstract, inline=False)

        # Calculate voting percentages and abstain votes
        if self.total_votes > 0:
            for_percentage = (self.total_votes_for / self.total_votes) * 100
            against_percentage = (self.total_votes_against / self.total_votes) * 100
            # Calculate abstain votes
            abstain_votes = self.total_votes - self.total_votes_for - self.total_votes_against
            abstain_percentage = (abstain_votes / self.total_votes) * 100
        else:
            for_percentage = against_percentage = abstain_percentage = 0
            abstain_votes = 0

        # Create voting visualization with colored bars
        voting_viz = ""
        if self.total_votes > 0:
            # Green bar for FOR votes
            for_blocks = int(for_percentage / 10)  # Each block represents 10%
            for_empty = 10 - for_blocks
            voting_viz += "🟩" * for_blocks + "⬜" * for_empty
            # Use non-breaking space and en dash for cleaner formatting
            voting_viz += f"\u00A0\u00A0–\u00A0{for_percentage:5.1f}%\u00A0FOR\n"
            
            # Red bar for AGAINST votes
            against_blocks = int(against_percentage / 10)
            against_empty = 10 - against_blocks
            voting_viz += "🟥" * against_blocks + "⬜" * against_empty
            # Use non-breaking space and en dash for cleaner formatting
            voting_viz += f"\u00A0\u00A0–\u00A0{against_percentage:5.1f}%\u00A0AGAINST\n"
            
            # Yellow/orange bar for ABSTAIN votes
            abstain_blocks = int(abstain_percentage / 10)
            abstain_empty = 10 - abstain_blocks
            voting_viz += "🟨" * abstain_blocks + "⬜" * abstain_empty
            # Use non-breaking space and en dash for cleaner formatting
            voting_viz += f"\u00A0\u00A0–\u00A0{abstain_percentage:5.1f}%\u00A0ABSTAIN"
        else:
            voting_viz = "No votes recorded yet"

        # Add voting visualization as non-inline field for full width
        embed.add_field(name="Voting", value=voting_viz, inline=False)

        # Add proposal ID as footer
        embed.set_footer(text=f"Proposal ID: {self.id}")
        
        return embed

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'LIVE_MODE: {LIVE_MODE}')
    
    # Initialize database
    init_database()
    
    # Load previously announced proposals
    global announced_proposals
    announced_proposals = load_announced_proposals()
    
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
            save_announced_proposal(proposal)  # Save to database

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

@bot.command(name='clear_db')
@commands.has_permissions(administrator=True)
async def clear_database(ctx):
    """Clear the announced proposals database (admin only)"""
    if LIVE_MODE:
        await ctx.send("Database operations are disabled in LIVE_MODE")
        return
        
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM announced_proposals')
    conn.commit()
    conn.close()
    
    global announced_proposals
    announced_proposals = set()
    
    await ctx.send("Announced proposals database has been cleared.")

@bot.command(name='db_stats')
async def database_stats(ctx):
    """Show database statistics"""
    if LIVE_MODE:
        await ctx.send("Database is disabled in LIVE_MODE")
        return
        
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM announced_proposals')
    total_count = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT COUNT(*) FROM announced_proposals 
        WHERE date(announced_at) = date('now')
    ''')
    today_count = cursor.fetchone()[0]
    
    conn.close()
    
    embed = discord.Embed(
        title="Database Statistics",
        description=f"LIVE_MODE: {LIVE_MODE}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Announced", value=total_count, inline=True)
    embed.add_field(name="Announced Today", value=today_count, inline=True)
    embed.add_field(name="In Memory", value=len(announced_proposals), inline=True)
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
