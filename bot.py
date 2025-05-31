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
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(funcName)s]: %(message)s')

# Load environment variables
dotenv.load_dotenv()

# Initialize intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Constants ---
STEP_AWAITING_GENDER = -1
STEP_AWAITING_REALM = -2
STEP_QUIZ_START = 0

# --- Configuration ---
TOKEN = os.getenv('TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))  # Channel where the quiz will be conducted

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

class StartQuizView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label="Start Quiz", style=discord.ButtonStyle.green, custom_id="start_quiz_button")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        author_id = interaction.user.id
        logging.info(f"Quiz start button clicked by {interaction.user} ({author_id})")
        
        if author_id in user_sessions:
            session = user_sessions[author_id]
            current_step = session.get("step")
            if isinstance(current_step, int) and \
               (current_step == STEP_AWAITING_GENDER or \
                current_step == STEP_AWAITING_REALM or \
                (STEP_QUIZ_START <= current_step < len(questions))):
                step_desc = "selection phase"
                if current_step == STEP_AWAITING_GENDER: step_desc = "gender selection"
                elif current_step == STEP_AWAITING_REALM: step_desc = "realm selection"
                elif current_step >= STEP_QUIZ_START: step_desc = f"question {current_step + 1}"
                
                await interaction.response.send_message(
                    f"You already have a quiz in progress (at {step_desc}). "
                    "Please complete it or wait for it to time out.",
                    ephemeral=True
                )
                return
            else: 
                user_sessions.pop(author_id, None)

        # Initialize session
        user_sessions[author_id] = {"step": STEP_AWAITING_GENDER, "scores": []}
        
        # Send gender selection
        gender_view = GenderSelectionView(author_id)
        await interaction.response.send_message(
            f"Welcome, {interaction.user.mention}! To discover your inner fairy, first, let's set the stage...",
            view=gender_view,
            ephemeral=True
        )
        gender_view.message = await interaction.original_response()

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
        logging.info(f"Gender selection timed out for user {self.original_interaction_user_id}")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            try:
                await self.message.edit(content="Gender selection timed out. Please start the quiz again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
        
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step") == STEP_AWAITING_GENDER:
            user_sessions.pop(self.original_interaction_user_id, None)

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
        logging.info(f"Realm selection timed out for user {self.original_interaction_user_id}")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            try:
                await self.message.edit(content="Realm selection timed out. Please start the quiz again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
        
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step") == STEP_AWAITING_REALM:
            user_sessions.pop(self.original_interaction_user_id, None)

class QuizOptionsView(discord.ui.View):
    def __init__(self, original_interaction_user_id: int, question_index: int):
        super().__init__(timeout=180)
        self.original_interaction_user_id = original_interaction_user_id
        self.question_index = question_index
        self.message: discord.Message | None = None
        
        q_data = questions[question_index]
        for i, option_text in enumerate(q_data["options"]):
            button = discord.ui.Button(label=option_text, 
                                       style=discord.ButtonStyle.secondary, 
                                       custom_id=f"quiz_option_{i}")
            button.callback = self.dynamic_button_callback 
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction_user_id:
            await interaction.response.send_message("This is not your quiz.", ephemeral=True)
            return False
        session = user_sessions.get(interaction.user.id)
        if not session or session.get("step") != self.question_index:
            await interaction.response.send_message("This question is no longer active or your session has changed.", ephemeral=True)
            return False
        return True

    async def dynamic_button_callback(self, interaction: discord.Interaction):
        button_custom_id = interaction.data['custom_id']
        clicked_button_label = "Unknown Option" 
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == button_custom_id:
                clicked_button_label = child.label
                break
        
        logging.info(f"Quiz option button '{clicked_button_label}' (ID: {button_custom_id}) clicked by {interaction.user} ({interaction.user.id})")
        
        try:
            option_index = int(button_custom_id.split('_')[-1])
        except (ValueError, IndexError):
            logging.error(f"Invalid custom_id format for quiz option: {button_custom_id}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("An internal error occurred with the button. Please start the quiz again.", ephemeral=True)
            except Exception as e_resp:
                logging.error(f"Error sending message for invalid custom_id format: {e_resp}")
            return

        await handle_quiz_answer(interaction, option_index, self.question_index)

    async def on_timeout(self):
        logging.info(f"Quiz for user {self.original_interaction_user_id} (Q{self.question_index + 1}) timed out.")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            try:
                await self.message.edit(content=f"Question {self.question_index + 1} timed out. Please start the quiz again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}, Q{self.question_index+1}).")
        
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step") == self.question_index:
            user_sessions.pop(self.original_interaction_user_id, None)

# --- Helper Functions / Interaction Handlers ---

async def handle_gender_selection(interaction: discord.Interaction, gender: str):
    user_id = interaction.user.id
    logging.info(f"Processing gender selection for User {user_id}, Gender: {gender}, Interaction ID: {interaction.id}")
    
    session = user_sessions.get(user_id)
    if not session or session.get("step") != STEP_AWAITING_GENDER:
        try:
            if not interaction.response.is_done():
                 await interaction.response.send_message("Your session is out of sync. Please start the quiz again.", ephemeral=True)
        except Exception as e_resp:
             logging.error(f"Error sending 'session out of sync' message: {e_resp}")
        return

    deferred = False
    try:
        await interaction.response.defer(thinking=False, ephemeral=False)
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
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} during gender selection: {e}")
    except Exception as e:
        logging.error(f"Generic error for {interaction.id} during gender selection: {e}")
        try:
            if deferred:
                await interaction.followup.send("An error occurred processing your gender selection. Please start the quiz again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in gender selection error handler: {ie}")

async def handle_realm_selection(interaction: discord.Interaction, realm: str):
    user_id = interaction.user.id
    logging.info(f"Processing realm selection for User {user_id}, Realm: {realm}, Interaction ID: {interaction.id}")

    session = user_sessions.get(user_id)
    if not session or session.get("step") != STEP_AWAITING_REALM:
        try:
            if not interaction.response.is_done():
                 await interaction.response.send_message("Your session is out of sync. Please start the quiz again.", ephemeral=True)
        except Exception as e_resp:
             logging.error(f"Error sending 'session out of sync' message: {e_resp}")
        return

    deferred = False
    try:
        await interaction.response.defer(thinking=False, ephemeral=False)
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
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} during realm selection: {e}")
    except Exception as e:
        logging.error(f"Generic error for {interaction.id} during realm selection: {e}")
        try:
            if deferred:
                await interaction.followup.send("An error occurred. Please start the quiz again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in realm selection error handler: {ie}")

async def handle_quiz_answer(interaction: discord.Interaction, choice_index: int, question_index_answered: int):
    user_id = interaction.user.id
    logging.info(f"Processing quiz answer for User {user_id}, Q{question_index_answered + 1} with option index {choice_index}, Interaction ID: {interaction.id}")

    session = user_sessions.get(user_id)
    if not session or session.get("step") != question_index_answered:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("This question is no longer active or your session has an issue. Please start the quiz again.", ephemeral=True)
        except discord.NotFound:
            logging.warning(f"Interaction {interaction.id} (user {user_id}, Q{question_index_answered+1}) already gone when quiz answer state invalid.")
        return

    deferred = False
    try:
        await interaction.response.defer(thinking=False, ephemeral=False)
        deferred = True

        current_question_data = questions[question_index_answered]
        
        session["scores"].append(current_question_data["scores"][choice_index])
        session["step"] += 1

        await interaction.edit_original_response(
            content=f"✅ You chose: **{current_question_data['options'][choice_index]}** for \"{current_question_data['question']}\"",
            view=None 
        )
        
        await send_question(interaction.channel, user_id)

    except discord.NotFound as e:
        logging.error(f"NotFound for {interaction.id} during quiz answer: {e}")
    except Exception as e:
        logging.error(f"Error processing quiz answer for {interaction.id}: {e}")
        try:
            if deferred:
                await interaction.followup.send("An error occurred while processing your answer. Please start the quiz again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in quiz answer error handler: {ie}")

async def send_question(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.get(author_id)
    if session is None:
        logging.warning(f"No session for user {author_id} in send_question")
        await channel.send("Oops! Couldn't find your quiz session. Please start the quiz again.", ephemeral=True)
        return

    current_step = session.get("step")
    if not isinstance(current_step, int) or current_step < STEP_QUIZ_START:
        logging.warning(f"Invalid step {current_step} for user {author_id} in send_question")
        user_sessions.pop(author_id, None)
        await channel.send("There was an issue with your quiz progression. Please start the quiz again.", ephemeral=True)
        return

    if current_step >= len(questions):
        await show_result(channel, author_id)
        return

    q_data = questions[current_step]
    
    embed = discord.Embed(
        title=f"❓ Question {current_step + 1}/{len(questions)}",
        description=f"**{q_data['question']}**",
        color=discord.Color.dark_purple()
    )
    quiz_view = QuizOptionsView(author_id, current_step)
    
    try:
        message = await channel.send(embed=embed, view=quiz_view)
        quiz_view.message = message 
        logging.info(f"Question {current_step + 1} sent to {author_id} with interactive buttons.")
    except discord.Forbidden:
        logging.error(f"Lacking permissions to send question to user {author_id} in channel {channel.id}")
        user = bot.get_user(author_id)
        if user:
            try:
                await user.send("I tried to send you a quiz question, but I don't have permission in that channel. Please check and try again.")
            except discord.Forbidden:
                logging.error(f"Also unable to DM user {author_id} about send permission error.")
    except Exception as e:
        logging.error(f"Failed to send question {current_step + 1} to user {author_id}: {e}")

async def show_result(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.pop(author_id, None)
    if not session or "scores" not in session or not session["scores"]:
        logging.warning(f"No session or empty scores for user {author_id} when trying to show result.")
        await channel.send("Hmm, it seems your fairy essence couldn't be determined (no answers recorded). Try the quiz again!", ephemeral=True)
        return

    score_counts = Counter(session["scores"])
    if not score_counts:
        logging.warning(f"Empty score_counts for user {author_id} despite having scores list.")
        await channel.send("Your answers didn't result in a fairy type. Please try the quiz again!", ephemeral=True)
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
    
    try:
        await channel.send(embed=embed)
        logging.info(f"Result sent to user {author_id}. Fairy type: {result_fairy_type}")
    except discord.Forbidden:
        logging.error(f"Lacking permissions to send result to user {author_id} in channel {channel.id}")
        if user:
            try:
                await user.send("I couldn't send your quiz results in the channel. Here they are:", embed=embed)
            except discord.Forbidden:
                logging.error(f"Also unable to DM user {author_id} with quiz results.")

# --- Bot Events ---

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name} ({bot.user.id})')
    logging.info(f'discord.py version: {discord.__version__}')
    
    # Send the start button to the configured channel
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            # Clear any existing messages from the bot in this channel
            async for message in channel.history(limit=100):
                if message.author == bot.user:
                    try:
                        await message.delete()
                    except discord.Forbidden:
                        logging.warning(f"Couldn't delete old message {message.id} in channel {channel.id}")
                    except discord.NotFound:
                        pass
            
            # Send new start message with button
            embed = discord.Embed(
                title="Discover Your Inner Fairy!",
                description="Click the button below to begin your magical journey and discover which fairy creature you truly are!",
                color=discord.Color.green()
            )
            view = StartQuizView()
            await channel.send(embed=embed, view=view)
            logging.info(f"Successfully sent start quiz message to channel {channel.id}")
        except discord.Forbidden:
            logging.error(f"Bot lacks permissions to send messages in channel {channel.id}")
        except Exception as e:
            logging.error(f"Failed to send start quiz message to channel {channel.id}: {e}")
    else:
        logging.error(f"Configured channel {CHANNEL_ID} not found")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return
    await bot.process_commands(message)

# --- Main Execution ---
if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        logging.critical("FATAL ERROR: No valid bot token provided. Exiting.")
    else:
        try:
            bot.run(TOKEN, log_handler=None)
        except discord.LoginFailure:
            logging.critical("FATAL ERROR: Improper token has been passed. Login failed.")
        except Exception as e:
            logging.critical(f"FATAL ERROR: An unexpected error occurred while trying to run the bot: {e}")