import discord
from discord.ext import commands
import random
from collections import Counter # For score tallying
import os
import dotenv
import traceback # For detailed error logging
import logging # For better logging than print
import time # For timing operations
import aiohttp # For diagnostic HTTP test

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(funcName)s]: %(message)s')


# Load environment variables (if you're using a .env file for the token)
dotenv.load_dotenv()

# Initialize intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Ensure this is enabled in your bot's dashboard
intents.members = True # IMPORTANT: Enable the members intent in your bot's dashboard

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Constants ---
STEP_AWAITING_GENDER = -1
STEP_AWAITING_REALM = -2
STEP_QUIZ_START = 0


# --- Data Structures ---
questions = [
    {
        "question": "What time of day do you feel most alive?",
        "options": ["Dawn", "Midday", "Twilight", "Midnight"],
        "scores": ["Aos Sí", "Leprechaun", "Pooka", "Banshee"]
    },
    {
        "question": "What would you guard with your life?",
        "options": ["Gold or treasure", "A sacred secret", "The heart of a loved one", "An ancient forest"],
        "scores": ["Leprechaun", "Pooka", "Banshee", "Aos Sí"]
    },
    {
        "question": "Pick your fairy home:",
        "options": ["Hollow tree", "Ocean cove", "Foggy moor", "Pub"],
        "scores": ["Aos Sí", "Selkie", "Banshee", "Clurichaun"]
    }
]
prefixes = ["Pooka", "Fae", "Briar", "Niamh", "Siobhan", "Gloam", "Donn", "Cael", "Aos Sí", "Selkie", "Banshee", "Clurichaun", "Leprechaun"]
suffixes = ["of the Glens", "Shadowstep", "Mistwhisper", "Nightwail", "Goldhand", "Ó Faery", "Gleannán", "Fogdrift"]
fairy_lore = {
    "Leprechaun": "Clever and a notorious trickster, you guard your treasures well and possess a sharp wit. You might be a master craftsman in your spare time!",
    "Pooka": "Wild, unpredictable, and most alive in the shadows of the night. You are a shapeshifter, embodying mystery and a touch of delightful chaos.",
    "Banshee": "Deeply sensitive and intuitive, your emotions run strong. You might have a powerful voice or presence that can herald great change.",
    "Clurichaun": "A lover of good times, fine drink, and a bit of mischief! You know how to liven up any gathering and have a knack for finding the best cellars.",
    "Aos Sí": "Noble, elegant, and possessing an ancient soul. You are one of the 'people of the mounds,' carrying an air of old magic and timeless grace.",
    "Selkie": "Dreamy, romantic, and irresistibly drawn to the vast, mysterious sea. You have a dual nature, comfortable both in water and on land, with a gentle heart.",
    "Changeling": "Quiet, mysterious, with an otherworldly charm that captivates those around you. You often feel like you belong to a different realm.",
    "Dullahan": "A grim and powerful figure, often a silent observer who commands respect, and perhaps a little fear. You carry an aura of significant, unspoken power.",
}
user_sessions = {}

# --- UI Views ---

class GenderSelectionView(discord.ui.View):
    def __init__(self, original_interaction_user_id: int):
        super().__init__(timeout=180)
        self.original_interaction_user_id = original_interaction_user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction_user_id:
            await interaction.response.send_message("This is not your quiz selection.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Man", style=discord.ButtonStyle.primary, custom_id="gender_man")
    async def man_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Gender button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_gender_selection(interaction, "Man")

    @discord.ui.button(label="Woman", style=discord.ButtonStyle.primary, custom_id="gender_woman")
    async def woman_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Gender button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_gender_selection(interaction, "Woman")

    @discord.ui.button(label="Other/Prefer Not to Say", style=discord.ButtonStyle.secondary, custom_id="gender_other")
    async def other_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Gender button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_gender_selection(interaction, "Other")

    async def on_timeout(self):
        logging.info(f"User {self.original_interaction_user_id}")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            try:
                await self.message.edit(content="Gender selection timed out. Please use `!startquiz` to begin again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
            except Exception as e:
                logging.error(f"Error editing message on timeout for user {self.original_interaction_user_id}: {e}")
        
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step", 0) < STEP_QUIZ_START :
            user_sessions.pop(self.original_interaction_user_id, None)
            logging.info(f"Cleared pre-quiz session for {self.original_interaction_user_id} due to timeout.")


class RealmSelectionView(discord.ui.View):
    def __init__(self, original_interaction_user_id: int):
        super().__init__(timeout=180)
        self.original_interaction_user_id = original_interaction_user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction_user_id:
            await interaction.response.send_message("You cannot interact with someone else's quiz selection.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Fairy Folk", style=discord.ButtonStyle.green, custom_id="realm_Fairy_Folk")
    async def fairy_folk_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Realm button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_realm_selection(interaction, "Fairy Folk")

    @discord.ui.button(label="Celtic Gods", style=discord.ButtonStyle.blurple, custom_id="realm_Celtic_Gods")
    async def celtic_gods_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Realm button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_realm_selection(interaction, "Celtic Gods")

    @discord.ui.button(label="Druids", style=discord.ButtonStyle.grey, custom_id="realm_Druids")
    async def druids_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Realm button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_realm_selection(interaction, "Druids")

    @discord.ui.button(label="Warriors", style=discord.ButtonStyle.red, custom_id="realm_Warriors")
    async def warriors_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Realm button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_realm_selection(interaction, "Warriors")

    @discord.ui.button(label="Mythical Creatures", style=discord.ButtonStyle.blurple, custom_id="realm_Mythical_Creatures")
    async def mythical_creatures_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Realm button '{button.label}' clicked by {interaction.user} ({interaction.user.id})")
        await handle_realm_selection(interaction, "Mythical Creatures")

    async def on_timeout(self):
        logging.info(f"User {self.original_interaction_user_id}")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            try:
                await self.message.edit(content="Realm selection timed out. Please use `!startquiz` to begin again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
            except Exception as e:
                logging.error(f"Error editing message on timeout for user {self.original_interaction_user_id}: {e}")
        
        user_sessions.pop(self.original_interaction_user_id, None)
        logging.info(f"Session for {self.original_interaction_user_id} popped due to timeout.")

# --- Helper Functions / Interaction Handlers ---

async def handle_gender_selection(interaction: discord.Interaction, gender: str):
    user_id = interaction.user.id
    logging.info(f"User {user_id}, Gender {gender}")
    
    session = user_sessions.get(user_id)
    if not session : # Should have been created by startquiz_command
        logging.warning(f"Session for {user_id} not found! Re-initializing. This might indicate an issue in startquiz_command or unexpected flow.")
        user_sessions[user_id] = {"step": STEP_AWAITING_GENDER, "scores": []}
        session = user_sessions[user_id]
    
    deferred = False
    try:
        logging.info(f"Attempting interaction.response.defer() for interaction {interaction.id}")
        defer_start_time = time.monotonic()
        await interaction.response.defer(thinking=False, ephemeral=False)
        defer_duration = time.monotonic() - defer_start_time
        logging.info(f"interaction.response.defer() for {interaction.id} succeeded in {defer_duration:.3f}s")
        deferred = True

        session["gender"] = gender
        session["step"] = STEP_AWAITING_REALM
        
        realm_view = RealmSelectionView(user_id)
        await interaction.edit_original_response(
            content=f"You've chosen **{gender}**! Now, which mythic realm calls to you?",
            view=realm_view
        )
        realm_view.message = await interaction.original_response()
            
        logging.info(f"Gender selection processed for {user_id}, presenting realm selection.")

    except discord.NotFound as e:
        defer_duration = time.monotonic() - defer_start_time
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} after {defer_duration:.3f}s: {e}\n{traceback.format_exc()}")
        if not deferred and interaction.channel and not interaction.response.is_done():
            try:
                await interaction.channel.send(f"{interaction.user.mention}, a glitch occurred with your gender selection. Please try `!startquiz` again.", delete_after=10)
            except Exception as ch_e:
                logging.error(f"Failed to send channel error message: {ch_e}")
    except Exception as e:
        defer_duration = time.monotonic() - defer_start_time
        logging.error(f"Error for {interaction.id} after {defer_duration:.3f}s: {e}\n{traceback.format_exc()}")
        try:
            if deferred:
                await interaction.followup.send("An error occurred processing your gender selection. Try `!startquiz` again.", ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Try `!startquiz` again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in error handler: {ie}")


async def handle_realm_selection(interaction: discord.Interaction, realm: str):
    user_id = interaction.user.id
    logging.info(f"User {user_id}, Realm {realm}")
    
    # --- DIAGNOSTIC HTTP TEST START ---
    async with aiohttp.ClientSession() as http_session:
        test_url = "https://www.google.com" 
        logging.info(f"Attempting diagnostic GET to {test_url} for {interaction.id}")
        http_diag_start_time = time.monotonic()
        try:
            async with http_session.get(test_url, timeout=aiohttp.ClientTimeout(total=10.0)) as resp:
                await resp.text() 
                http_diag_duration = time.monotonic() - http_diag_start_time
                logging.info(f"Diagnostic GET for {interaction.id} to {test_url} status: {resp.status}, took {http_diag_duration:.3f}s")
        except Exception as http_e:
            http_diag_duration = time.monotonic() - http_diag_start_time
            logging.error(f"Diagnostic GET for {interaction.id} to {test_url} failed after {http_diag_duration:.3f}s: {http_e}")
    # --- DIAGNOSTIC HTTP TEST END ---

    session = user_sessions.get(user_id)
    if not session:
        logging.warning(f"No session found for {user_id}")
        try: 
            if not interaction.response.is_done():
                await interaction.response.send_message("Your session was not found. Please try `!startquiz` again.", ephemeral=True)
        except discord.NotFound: 
            logging.warning(f"Interaction {interaction.id} (user {user_id}) already gone when session not found.")
        except Exception as e_resp:
            logging.error(f"Error sending 'session not found' message for {user_id}: {e_resp}")
        return

    deferred = False
    defer_start_time = time.monotonic() # Initialize here in case defer() raises before assignment
    try:
        logging.info(f"Attempting interaction.response.defer() for interaction {interaction.id}")
        defer_start_time = time.monotonic()
        await interaction.response.defer(thinking=False, ephemeral=False)
        defer_duration = time.monotonic() - defer_start_time
        logging.info(f"interaction.response.defer() for {interaction.id} succeeded in {defer_duration:.3f}s")
        deferred = True

        session["realm"] = realm
        session["step"] = STEP_QUIZ_START
        
        await interaction.edit_original_response(
            content=f"You've chosen the realm of **{realm}**! Your adventure begins now...",
            view=None 
        )
        logging.info(f"Realm selection processed for {user_id}. Realm: {realm}. Starting questions.")
        await send_question(interaction.channel, user_id)

    except discord.NotFound as e:
        defer_duration = time.monotonic() - defer_start_time
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} after {defer_duration:.3f}s: {e}\n{traceback.format_exc()}")
        if not deferred and interaction.channel and not interaction.response.is_done():
            try:
                await interaction.channel.send(f"{interaction.user.mention}, a glitch occurred. Please try `!startquiz` again.", delete_after=10)
            except Exception as ch_e:
                 logging.error(f"Failed to send channel error message: {ch_e}")
    except Exception as e:
        defer_duration = time.monotonic() - defer_start_time
        logging.error(f"Error for {interaction.id} after {defer_duration:.3f}s: {e}\n{traceback.format_exc()}")
        try:
            if deferred:
                await interaction.followup.send("An error occurred. Please try `!startquiz` again.", ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Try `!startquiz` again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in error handler: {ie}")


async def send_question(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.get(author_id)
    if session is None:
        logging.warning(f"No session for user {author_id}")
        await channel.send("Oops! Couldn't find your quiz session. Please try `!startquiz` again.")
        return

    current_step = session.get("step")
    if not isinstance(current_step, int) or current_step < STEP_QUIZ_START:
        logging.warning(f"Invalid step {current_step} for user {author_id} (expected >= {STEP_QUIZ_START}).")
        await channel.send("There was an issue with your quiz progression. Please try `!startquiz` again.")
        user_sessions.pop(author_id, None)
        return

    if current_step >= len(questions):
        await show_result(channel, author_id)
        return

    q_data = questions[current_step]
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q_data["options"])])
    embed = discord.Embed(
        title=f"❓ Question {current_step + 1}/{len(questions)}",
        description=f"**{q_data['question']}**\n\n{options_text}",
        color=discord.Color.dark_purple()
    )
    embed.set_footer(text="Reply with the number of your chosen answer.")
    await channel.send(embed=embed)

async def show_result(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.pop(author_id, None)
    if not session or not session.get("scores"):
        logging.warning(f"No session or scores for user {author_id}")
        await channel.send("Hmm, it seems your fairy essence couldn't be determined this time. Try the quiz again!")
        return

    score_counts = Counter(session["scores"])
    if not score_counts:
        logging.warning(f"Empty score_counts for user {author_id}")
        await channel.send("Your answers didn't result in a fairy type. Please try the quiz again!")
        return

    result_fairy_type = score_counts.most_common(1)[0][0]
    chosen_prefix = result_fairy_type if result_fairy_type in prefixes else random.choice(prefixes)
    chosen_suffix = random.choice(suffixes)
    fairy_name = f"{chosen_prefix} {chosen_suffix}"
    lore_snippet = fairy_lore.get(result_fairy_type, "A mysterious and enchanting fairy, with tales yet to be widely told.")
    
    user = bot.get_user(author_id)
    display_name = user.display_name if user else "Mysterious Soul"
    avatar_url = user.avatar.url if user and user.avatar else None

    if isinstance(channel, discord.TextChannel) and channel.guild:
        member = channel.guild.get_member(author_id)
        if member:
            display_name = member.display_name
            avatar_url = member.display_avatar.url 

    embed = discord.Embed(title="✨ Your Inner Fairy Revealed! ✨", color=discord.Color.random())
    if avatar_url:
        embed.set_author(name=f"{display_name}'s Fairy Form", icon_url=avatar_url)
    else:
        embed.set_author(name=f"{display_name}'s Fairy Form")
    embed.add_field(name="Fairy Type", value=f"**{result_fairy_type}**", inline=False)
    embed.add_field(name="Your Fairy Name", value=f"**{fairy_name}**", inline=False)
    if 'gender' in session:
        embed.add_field(name="Gender Chosen", value=f"*{session['gender']}*", inline=True)
    if 'realm' in session:
        embed.add_field(name="Realm Chosen", value=f"*{session['realm']}*", inline=True)
    embed.add_field(name="About Your Kind", value=f"*{lore_snippet}*", inline=False)
    embed.set_footer(text="(An image of your fairy form remains shrouded in mist... for now!)")
    await channel.send(embed=embed)

# --- Bot Events ---

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name} ({bot.user.id})')
    logging.info('The fairy quiz bot is now online!')

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return

    author_id = message.author.id
    session = user_sessions.get(author_id)

    if session and isinstance(session.get("step"), int) and \
       STEP_QUIZ_START <= session["step"] < len(questions) and \
       message.content.strip().isdigit():
        
        choice_num = int(message.content.strip())
        current_question_data = questions[session["step"]]
        num_options = len(current_question_data["options"])
        
        if 1 <= choice_num <= num_options:
            choice_idx = choice_num - 1
            session["scores"].append(current_question_data["scores"][choice_idx])
            session["step"] += 1
            await send_question(message.channel, author_id)
        else:
            await message.channel.send(
                f"Oops, {message.author.mention}! That's not a valid choice. "
                f"Please enter a number between 1 and {num_options}."
            )
        return 
    await bot.process_commands(message)

# --- Bot Commands ---

@bot.command(name='startquiz', help='Begin your journey to discover your inner fairy!')
async def startquiz_command(ctx: commands.Context):
    author_id = ctx.author.id
    logging.info(f"User {author_id}")

    if author_id in user_sessions:
        session = user_sessions[author_id]
        current_step = session.get("step")
        if isinstance(current_step, int) and \
           (current_step < STEP_QUIZ_START or (STEP_QUIZ_START <= current_step < len(questions))):
            step_desc = "selection phase" if current_step < STEP_QUIZ_START else f"question {current_step + 1}"
            await ctx.send(
                f"{ctx.author.mention}, you already have a quiz in progress (at {step_desc}). "
                "Please complete it or wait for it to time out."
            )
            logging.info(f"Blocked for {ctx.author} - quiz already in progress at step {current_step}.")
            return
        else: 
            logging.info(f"Clearing old/invalid session for {ctx.author} (step: {current_step}).")
            user_sessions.pop(author_id, None)

    user_sessions[author_id] = {"step": STEP_AWAITING_GENDER, "scores": []}
    logging.info(f"Pre-quiz session initialized for {author_id} at step {STEP_AWAITING_GENDER}")

    gender_view = GenderSelectionView(author_id)
    try:
        initial_message = await ctx.send(
            f"Welcome, {ctx.author.mention}! To discover your inner fairy, first, let's set the stage...",
            view=gender_view
        )
        gender_view.message = initial_message 
        logging.info(f"GenderSelectionView sent to {ctx.author}")
    except discord.Forbidden:
        logging.error(f"Bot lacks permission in {ctx.channel} ({ctx.guild})")
        user_sessions.pop(author_id, None) 
        try:
            await ctx.author.send("I couldn't send a message in the channel. Check my permissions or try elsewhere.")
        except discord.Forbidden:
            logging.error(f"Bot also lacks permission to DM {ctx.author}.")
    except Exception as e:
        logging.error(f"Failed to send GenderSelectionView to {ctx.author}: {e}\n{traceback.format_exc()}")
        user_sessions.pop(author_id, None)
        try:
            await ctx.send("Sorry, something went wrong. Please try `!startquiz` again later.", ephemeral=True)
        except Exception as e_ephemeral:
             logging.error(f"Error sending ephemeral error to context: {e_ephemeral}")

# --- Main Execution ---
if __name__ == "__main__":
    TOKEN = os.getenv('TOKEN') 
    if TOKEN is None:
        logging.warning("TOKEN environment variable not found. Using hardcoded fallback for DEV ONLY.")
        TOKEN = "YOUR_BOT_TOKEN_HERE" #  <<< IMPORTANT: REPLACE WITH YOUR ACTUAL TOKEN FOR TESTING IF NEEDED

    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE": # Added check for placeholder
        logging.critical("FATAL ERROR: No valid bot token provided. Exiting.")
    else:
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            logging.critical("FATAL ERROR: Improper token has been passed. Login failed.")
        except discord.HTTPException as e:
            if e.status == 429: 
                logging.critical("FATAL ERROR: Too many requests (429). You might be rate-limited by Discord.")
            else:
                logging.critical(f"FATAL ERROR: An HTTP error occurred: {e.status} {e.text}")
            logging.critical(traceback.format_exc())
        except Exception as e:
            logging.critical(f"FATAL ERROR: An unexpected error occurred while trying to run the bot: {e}")
            logging.critical(traceback.format_exc())