import discord
from discord.ext import commands
import os
import random
import sqlite3
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Validate environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GIVE_COMMAND_USER = int(os.getenv("GIVE_COMMAND_USER", "0"))  # User allowed to use /give command
AUTHORIZED_USERS = [int(user_id) for user_id in os.getenv("AUTHORIZED_USERS", "").split(",") if user_id]

if not DISCORD_BOT_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN environment variable is missing!")

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("discord_bot")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree  # Using the app command tree for slash commands

# Initialize database
def init_db():
    with sqlite3.connect("inventory.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item TEXT
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stolen_items (
            thief_id INTEGER,
            victim_id INTEGER,
            item TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()

init_db()  # Call this when the bot starts

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    if os.getenv("ENV") == "dev":  # Only sync in development
        await tree.sync(guild=None)
    logger.info(f'Logged in as {bot.user}')
    logger.info(f"Available commands: {[cmd.name for cmd in tree.get_commands()]}")

# Scavenge Loot Data
scavenge_loot = {
    "eden": ["Handgun", "Rifle Parts", "Box of Ammunition", "Combat Knife", "Damaged Decimator"],
    "saffron": ["Bag of Seeds", "Watering Can", "Sack of Fertilizer", "Farming Drone", "Rusty Hoe"],
    "eclipse": ["EMP Grenade", "Hacking Device", "Energy Shield", "Cloaking Device", "Nanobot Swarm"],  # Gadgets only
    "pumice": ["Ancient Relic", "Stone Tablet", "Enchanted Cloak", "Siver Crown", "Mystic Orb", "Calidus Pulmenti Fumo Sized Dragon"],  # Added the dragon
    "kahns": ["Turbocharger", "Prototype Engine", "Exotic Fuel Cell", "Reinforced Chassis", "Holographic Dashboard"]
}

# Secret Items
secret_items = [
    "Settler's Delightful Cheese Egg Recipe",
    "Settler's Cheesy Eggsandvich Recipe",
    "Deorbited satellite remains",
    "Settler's Apparatus 4 codeline"  # Exclusive to Pumice Castle
]

# Tell Command (Authorized Users Only)
@bot.tree.command(name="tell", description="Make the bot say something.")
async def tell(ctx: discord.Interaction, message: str):
    """
    Make the bot send a message to the channel. Only authorized users can use this command.
    """
    try:
        if ctx.user.id not in AUTHORIZED_USERS:
            await ctx.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        await ctx.channel.send(message)
        await ctx.response.send_message("Message sent!", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in tell command: {e}")
        await ctx.response.send_message("An error occurred while sending the message.", ephemeral=True)

# Slots Command
@bot.tree.command(name="slots", description="Spin the slot machine!")
async def slots(ctx: discord.Interaction):
    """
    Simulates a slot machine spin and displays the result.
    """
    try:
        symbols = ["🍒", "🍋", "🔔", "⭐", "💎"]
        result = [random.choice(symbols) for _ in range(3)]
        outcome = " | ".join(result)
        if result[0] == result[1] == result[2]:
            message = "JACKPOT! 🎉 You won!"
        else:
            message = "Better luck next time!"

        await ctx.response.send_message(f"🎰 {outcome} 🎰\n{message}", ephemeral=False)
    except Exception as e:
        logger.error(f"Error in slots command: {e}")
        await ctx.response.send_message("An error occurred while processing your request. Please try again later.", ephemeral=True)

# Scavenge Command
@bot.tree.command(name="scavenge", description="Search an area for useful items.")
async def scavenge(ctx: discord.Interaction, location: str):
    """
    Search a location for items and store them in the user's inventory.
    In Eclipse, there's a chance to trigger a theft attempt.
    """
    try:
        location_map = {
            "eden": "Eden-227",
            "saffron": "Saffron Fields",
            "eclipse": "Eclipse-Industrial-Systems",
            "pumice": "Pumice Castle",
            "kahns": "Kahns Garage of Wonders"
        }

        location_key = location.lower()
        if location_key not in scavenge_loot:
            await ctx.response.send_message("Invalid location! Choose from: eden, saffron, eclipse, pumice, kahns.", ephemeral=True)
            return

        # Check if the user finds a secret item
        if random.randint(1, 20) == 1:  # 1 in 20 chance to find a secret item
            if location_key == "pumice":
                found_item = "Settler's Apparatus 4 codeline"
            else:
                found_item = random.choice(secret_items)  # Other secret items
            message = "You got a secret item!"
        else:
            found_item = random.choice(scavenge_loot[location_key])
            message = f"You scavenge {location_map[location_key]} and find a **{found_item}**!"

        # Store item in database
        with sqlite3.connect("inventory.db") as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO inventory (user_id, item) VALUES (?, ?)", (ctx.user.id, found_item))
            conn.commit()

        # Check if the location is Eclipse and trigger a theft attempt
        if location_key == "eclipse":
            # Randomly select a target user (excluding the scavenger)
            guild = ctx.guild
            members = [member for member in guild.members if not member.bot and member.id != ctx.user.id]
            if members:  # Ensure there are valid targets
                target = random.choice(members)
                await handle_theft(ctx.user, target)  # Handle the theft attempt

        await ctx.response.send_message(message, ephemeral=False)
    except Exception as e:
        logger.error(f"Error in scavenge command: {e}")
        await ctx.response.send_message("An error occurred while processing your request. Please try again later.", ephemeral=True)

# Trade Command (Prevent trading Settler's Apparatus 4 codeline)
@bot.tree.command(name="trade", description="Trade an item with another player.")
async def trade(ctx: discord.Interaction, user: discord.User, item: str):
    """
    Trade an item with another player.
    """
    try:
        if user.id == ctx.user.id:
            await ctx.response.send_message("You can't trade with yourself!", ephemeral=True)
            return

        # Check if the item is "Settler's Apparatus 4 codeline"
        if item == "Settler's Apparatus 4 codeline":
            await ctx.response.send_message("You cannot trade **Settler's Apparatus 4 codeline**!", ephemeral=True)
            return

        with sqlite3.connect("inventory.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item FROM inventory WHERE user_id = ? AND item = ?", (ctx.user.id, item))
            item_data = cursor.fetchone()

            if not item_data:
                await ctx.response.send_message("You don't have that item!", ephemeral=True)
                return

            cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (ctx.user.id, item))
            cursor.execute("INSERT INTO inventory (user_id, item) VALUES (?, ?)", (user.id, item))
            conn.commit()

        await ctx.response.send_message(f"Trade successful! You gave **{item}** to {user.display_name}.", ephemeral=False)
    except Exception as e:
        logger.error(f"Error in trade command: {e}")
        await ctx.response.send_message("An error occurred during the trade. Please try again later.", ephemeral=True)

# Use Command (For gadgets and the dragon)
@bot.tree.command(name="use", description="Use a gadget or the dragon from your inventory.")
async def use(ctx: discord.Interaction, item: str, target: discord.User = None):
    """
    Use a gadget or the dragon from your inventory.
    If using the dragon, specify the user to retrieve a stolen item from.
    """
    try:
        # Check if the item is in the user's inventory
        with sqlite3.connect("inventory.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item FROM inventory WHERE user_id = ? AND item = ?", (ctx.user.id, item))
            if not cursor.fetchone():
                await ctx.response.send_message(f"You don't have **{item}** in your inventory!", ephemeral=True)
                return

            # Handle the dragon separately
            if item == "Calidus Pulmenti Fumo Sized Dragon":
                if not target:
                    await ctx.response.send_message(
                        "You must specify a user to retrieve a stolen item from! Use `/use Calidus Pulmenti Fumo Sized Dragon @User`.",
                        ephemeral=True
                    )
                    return

                # Check if the target has any items stolen from the user
                cursor.execute("""
                    SELECT item FROM stolen_items
                    WHERE victim_id = ? AND thief_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (ctx.user.id, target.id))
                stolen_item_data = cursor.fetchone()

                if stolen_item_data:
                    stolen_item = stolen_item_data[0]

                    # Return the stolen item to the user
                    cursor.execute("INSERT INTO inventory (user_id, item) VALUES (?, ?)", (ctx.user.id, stolen_item))
                    # Remove the stolen item from the thief's inventory
                    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (target.id, stolen_item))
                    # Remove the stolen item record
                    cursor.execute("DELETE FROM stolen_items WHERE victim_id = ? AND thief_id = ? AND item = ?", (ctx.user.id, target.id, stolen_item))
                    conn.commit()

                    await ctx.response.send_message(
                        f"Your **Calidus Pulmenti Fumo Sized Dragon** retrieved **{stolen_item}** from {target.display_name}!",
                        ephemeral=False
                    )
                else:
                    await ctx.response.send_message(
                        f"No items were stolen from you by {target.display_name}!",
                        ephemeral=True
                    )
            else:
                # Handle other gadgets
                if item not in scavenge_loot["eclipse"]:
                    await ctx.response.send_message(f"**{item}** is not a gadget and cannot be used!", ephemeral=True)
                    return

                if not target:
                    await ctx.response.send_message(
                        f"You must specify a target user to use **{item}**! Use `/use {item} @User`.",
                        ephemeral=True
                    )
                    return

                # Example: EMP Grenade disables the target's protective gadgets
                if item == "EMP Grenade":
                    # Remove all protective gadgets from the target's inventory
                    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item IN ('Energy Shield', 'Cloaking Device')", (target.id,))
                    conn.commit()
                    await ctx.response.send_message(
                        f"You used **{item}** on {target.display_name}, disabling their protective gadgets!",
                        ephemeral=False
                    )
                # Example: Hacking Device steals a random item
                elif item == "Hacking Device":
                    await handle_theft(ctx.user, target)  # Trigger a theft attempt
                    await ctx.response.send_message(
                        f"You used **{item}** on {target.display_name}!",
                        ephemeral=False
                    )
                else:
                    await ctx.response.send_message(
                        f"You used **{item}** on {target.display_name}!",
                        ephemeral=False
                    )

            # Remove the item from the user's inventory
            cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (ctx.user.id, item))
            conn.commit()
    except Exception as e:
        logger.error(f"Error in use command: {e}")
        await ctx.response.send_message("An error occurred while processing your request. Please try again later.", ephemeral=True)

# Function to handle theft attempts
async def handle_theft(attacker: discord.User, target: discord.User):
    """
    Handle a theft attempt. If the target has a protective gadget, it will be consumed automatically.
    """
    with sqlite3.connect("inventory.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item FROM inventory WHERE user_id = ? AND item IN ('Energy Shield', 'Cloaking Device')", (target.id,))
        protective_gadget = cursor.fetchone()

        if protective_gadget:
            # Consume the protective gadget
            cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (target.id, protective_gadget[0]))
            conn.commit()
            await attacker.send(f"Your theft attempt was blocked by {target.display_name}'s **{protective_gadget[0]}**! The **{protective_gadget[0]}** has been consumed.")
            await target.send(f"Your **{protective_gadget[0]}** blocked a theft attempt from {attacker.display_name}! The **{protective_gadget[0]}** has been consumed.")
        else:
            # Attempt to steal an item
            cursor.execute("SELECT item FROM inventory WHERE user_id = ? ORDER BY RANDOM() LIMIT 1", (target.id,))
            stolen_item = cursor.fetchone()

            if stolen_item:
                # Log the stolen item
                cursor.execute("INSERT INTO stolen_items (thief_id, victim_id, item) VALUES (?, ?, ?)", (attacker.id, target.id, stolen_item[0]))
                # Remove the item from the target's inventory
                cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (target.id, stolen_item[0]))
                # Add the item to the attacker's inventory
                cursor.execute("INSERT INTO inventory (user_id, item) VALUES (?, ?)", (attacker.id, stolen_item[0]))
                conn.commit()
                await attacker.send(f"You stole **{stolen_item[0]}** from {target.display_name}!")
                await target.send(f"**{stolen_item[0]}** was stolen from you by {attacker.display_name}!")
            else:
                await attacker.send(f"You tried to steal from {target.display_name}, but they have no items to steal!")

# Give Command
@bot.tree.command(name="give", description="Give an item to another player.")
async def give(ctx: discord.Interaction, user: discord.User, item: str):
    """
    Give an item to another player. Only the specified user can use this command.
    """
    try:
        # Check if the user is allowed to use the /give command
        if ctx.user.id != GIVE_COMMAND_USER:
            await ctx.response.send_message("You don't have permission to use this command!", ephemeral=True)
            return

        # Check if the item is "Settler's Apparatus 4 codeline"
        if item == "Settler's Apparatus 4 codeline":
            await ctx.response.send_message("You cannot give **Settler's Apparatus 4 codeline**!", ephemeral=True)
            return

        # Store item in the target user's inventory
        with sqlite3.connect("inventory.db") as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO inventory (user_id, item) VALUES (?, ?)", (user.id, item))
            conn.commit()

        await ctx.response.send_message(f"Gave **{item}** to {user.display_name}!", ephemeral=False)
    except Exception as e:
        logger.error(f"Error in give command: {e}")
        await ctx.response.send_message("An error occurred while processing your request. Please try again later.", ephemeral=True)

# Inventory Pagination View
class InventoryView(discord.ui.View):
    def __init__(self, items, timeout=60):
        super().__init__(timeout=timeout)
        self.items = items
        self.page = 0
        self.max_pages = (len(items) - 1) // 5 + 1

    def get_page_content(self):
        page_items = self.items[self.page * 5:(self.page + 1) * 5]
        content = f"**Your Inventory (Page {self.page + 1}/{self.max_pages}):**\n"
        content += "\n".join([f"- {item[0]}" for item in page_items])
        return content

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, disabled=True)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            # Enable next button if it was disabled
            self.next_button.disabled = False
            # Disable prev button if we're on the first page
            if self.page == 0:
                button.disabled = True
            await interaction.response.edit_message(content=self.get_page_content(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages - 1:
            self.page += 1
            # Enable prev button if it was disabled
            self.previous_button.disabled = False
            # Disable next button if we're on the last page
            if self.page == self.max_pages - 1:
                button.disabled = True
            await interaction.response.edit_message(content=self.get_page_content(), view=self)

# Inventory Command
@bot.tree.command(name="inv", description="View your inventory.")
async def inv(ctx: discord.Interaction):
    """
    Display the user's inventory with pagination.
    """
    try:
        with sqlite3.connect("inventory.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item FROM inventory WHERE user_id = ?", (ctx.user.id,))
            items = cursor.fetchall()

        if not items:
            await ctx.response.send_message("Your inventory is empty.", ephemeral=True)
        else:
            view = InventoryView(items)
            await ctx.response.send_message(content=view.get_page_content(), view=view, ephemeral=False)
    except Exception as e:
        logger.error(f"Error in inv command: {e}")
        await ctx.response.send_message("An error occurred while fetching your inventory. Please try again later.", ephemeral=True)

# Run the bot
bot.run(DISCORD_BOT_TOKEN)
