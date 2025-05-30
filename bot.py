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
# Changed to ensure it's applied if the script is reloaded or run in certain environments.
# If you have a central logging setup, this might be redundant.
if not logging.getLogger().hasHandlers():
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
STEP_AWAITING_REALM = -2 # Gender selected, awaiting realm
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
        logging.info(f"Gender selection timed out for user {self.original_interaction_user_id}")
        if self.message:
            for item in self.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)): # Check item type before disabling
                    item.disabled = True
            try:
                await self.message.edit(content="Gender selection timed out. Please use `!startquiz` to begin again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
            except Exception as e:
                logging.error(f"Error editing message on timeout for user {self.original_interaction_user_id}: {e}")
        
        session = user_sessions.get(self.original_interaction_user_id)
        # Only clear session if it's still in gender selection phase specifically for this quiz structure
        if session and session.get("step") == STEP_AWAITING_GENDER :
            user_sessions.pop(self.original_interaction_user_id, None)
            logging.info(f"Cleared pre-quiz session for {self.original_interaction_user_id} (gender step) due to timeout.")


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
                await self.message.edit(content="Realm selection timed out. Please use `!startquiz` to begin again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}).")
            except Exception as e:
                logging.error(f"Error editing message on timeout for user {self.original_interaction_user_id}: {e}")
        
        # Pop session if it was awaiting realm or further along if this specific view times out
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step") == STEP_AWAITING_REALM:
             user_sessions.pop(self.original_interaction_user_id, None)
             logging.info(f"Session for {self.original_interaction_user_id} (realm step) popped due to timeout.")


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
            # Set the callback for THIS specific button instance
            button.callback = self.dynamic_button_callback 
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction_user_id:
            await interaction.response.send_message("This is not your quiz.", ephemeral=True)
            return False
        # Also check if the interaction is for the current question step to prevent old button clicks
        session = user_sessions.get(interaction.user.id)
        if not session or session.get("step") != self.question_index:
            logging.warning(f"Interaction check failed for user {interaction.user.id}: "
                            f"Session step {session.get('step') if session else 'None'} "
                            f"does not match QuizOptionsView Q index {self.question_index}.")
            await interaction.response.send_message("This question is no longer active or your session has changed.", ephemeral=True)
            return False
        return True

    async def dynamic_button_callback(self, interaction: discord.Interaction):
        # The button object itself is interaction.to_dict()['message']['components'][...]['components'][...]
        # or more easily, just use the custom_id from interaction.data
        button_custom_id = interaction.data['custom_id']
        
        # Find the label for logging, if needed (optional)
        clicked_button_label = "Unknown Option" 
        for child in self.children: # self.children are the items (buttons) in the view
            if isinstance(child, discord.ui.Button) and child.custom_id == button_custom_id:
                clicked_button_label = child.label
                break
        
        logging.info(f"Quiz option button '{clicked_button_label}' (ID: {button_custom_id}) clicked by {interaction.user} ({interaction.user.id})")
        
        try:
            # Extract the option index from the custom_id (e.g., "quiz_option_0" -> 0)
            option_index = int(button_custom_id.split('_')[-1])
        except (ValueError, IndexError):
            logging.error(f"Invalid custom_id format for quiz option: {button_custom_id}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("An internal error occurred with the button. Please try `!startquiz` again.", ephemeral=True)
                else:
                    await interaction.followup.send("An internal error occurred with the button. Please try `!startquiz` again.", ephemeral=True)
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
                await self.message.edit(content=f"Question {self.question_index + 1} timed out. Please use `!startquiz` to begin again.", view=self)
            except discord.NotFound:
                logging.warning(f"Failed to edit message on timeout (message not found for user {self.original_interaction_user_id}, Q{self.question_index+1}).")
            except Exception as e:
                logging.error(f"Error editing message on timeout for user {self.original_interaction_user_id}, Q{self.question_index+1}: {e}")
        
        session = user_sessions.get(self.original_interaction_user_id)
        if session and session.get("step") == self.question_index:
            user_sessions.pop(self.original_interaction_user_id, None)
            logging.info(f"Cleared quiz session for {self.original_interaction_user_id} (Q{self.question_index + 1}) due to timeout.")


# --- Helper Functions / Interaction Handlers ---

async def handle_gender_selection(interaction: discord.Interaction, gender: str):
    user_id = interaction.user.id
    logging.info(f"Processing gender selection for User {user_id}, Gender: {gender}, Interaction ID: {interaction.id}")
    
    session = user_sessions.get(user_id)
    if not session or session.get("step") != STEP_AWAITING_GENDER:
        logging.warning(f"Session issue for {user_id} in handle_gender_selection. Expected step {STEP_AWAITING_GENDER}, got {session.get('step') if session else 'None'}. Re-initializing or warning user.")
        # It's risky to re-initialize here if the interaction is old. Best to check if interaction is still valid.
        try:
            if not interaction.response.is_done():
                 await interaction.response.send_message("Your session is out of sync. Please try `!startquiz` again.", ephemeral=True)
            else: # if already deferred
                 await interaction.followup.send("Your session is out of sync. Please try `!startquiz` again.", ephemeral=True)
        except Exception as e_resp:
             logging.error(f"Error sending 'session out of sync' message: {e_resp}")
        return

    deferred = False
    defer_start_time = time.monotonic()
    try:
        logging.info(f"Attempting interaction.response.defer() for interaction {interaction.id}")
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
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} during gender selection after {op_duration:.3f}s: {e}", exc_info=True)
        # If defer failed and it's NotFound, the interaction is truly gone.
        # If defer succeeded, this NotFound would be on edit_original_response, which is also problematic.
        # No explicit message here as it's hard to respond to a "gone" interaction.
    except Exception as e:
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"Generic error for {interaction.id} during gender selection after {op_duration:.3f}s: {e}", exc_info=True)
        try:
            if deferred: # If defer succeeded, followup is the way.
                await interaction.followup.send("An error occurred processing your gender selection. Try `!startquiz` again.", ephemeral=True)
            elif not interaction.response.is_done(): # If defer failed but interaction still fresh.
                await interaction.response.send_message("An error occurred. Try `!startquiz` again.", ephemeral=True)
        except Exception as ie: # Catch errors during the error reporting itself.
            logging.error(f"Error sending followup/response in gender selection error handler: {ie}", exc_info=True)


async def handle_realm_selection(interaction: discord.Interaction, realm: str):
    user_id = interaction.user.id
    logging.info(f"Processing realm selection for User {user_id}, Realm: {realm}, Interaction ID: {interaction.id}")
    
    # --- DIAGNOSTIC HTTP TEST START ---
    # This is for debugging network issues. Consider removing or making conditional for production.
    # async with aiohttp.ClientSession() as http_session:
    #     test_url = "https://www.google.com" 
    #     logging.info(f"Attempting diagnostic GET to {test_url} for {interaction.id}")
    #     http_diag_start_time = time.monotonic()
    #     try:
    #         async with http_session.get(test_url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp: # Reduced timeout
    #             await resp.text() 
    #             http_diag_duration = time.monotonic() - http_diag_start_time
    #             logging.info(f"Diagnostic GET for {interaction.id} to {test_url} status: {resp.status}, took {http_diag_duration:.3f}s")
    #     except Exception as http_e:
    #         http_diag_duration = time.monotonic() - http_diag_start_time
    #         logging.error(f"Diagnostic GET for {interaction.id} to {test_url} failed after {http_diag_duration:.3f}s: {http_e}")
    # --- DIAGNOSTIC HTTP TEST END ---

    session = user_sessions.get(user_id)
    if not session or session.get("step") != STEP_AWAITING_REALM:
        logging.warning(f"Session issue for {user_id} in handle_realm_selection. Expected step {STEP_AWAITING_REALM}, got {session.get('step') if session else 'None'}")
        try:
            if not interaction.response.is_done():
                 await interaction.response.send_message("Your session is out of sync. Please try `!startquiz` again.", ephemeral=True)
            else:
                 await interaction.followup.send("Your session is out of sync. Please try `!startquiz` again.", ephemeral=True)
        except Exception as e_resp:
             logging.error(f"Error sending 'session out of sync' message: {e_resp}")
        return

    deferred = False
    defer_start_time = time.monotonic()
    try:
        logging.info(f"Attempting interaction.response.defer() for interaction {interaction.id}")
        await interaction.response.defer(thinking=False, ephemeral=False)
        defer_duration = time.monotonic() - defer_start_time
        logging.info(f"interaction.response.defer() for {interaction.id} succeeded in {defer_duration:.3f}s")
        deferred = True

        session["realm"] = realm
        session["step"] = STEP_QUIZ_START
        
        # Edit the message to confirm realm selection and remove buttons
        await interaction.edit_original_response(
            content=f"You've chosen the realm of **{realm}**! Your adventure begins now...",
            view=None # Clear the view after selection
        )
            
        logging.info(f"Realm selection processed for {user_id}. Realm: {realm}. Starting questions.")
        await send_question(interaction.channel, user_id)

    except discord.NotFound as e:
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"NotFound (Unknown Interaction?) for {interaction.id} during realm selection after {op_duration:.3f}s: {e}", exc_info=True)
    except Exception as e:
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"Generic error for {interaction.id} during realm selection after {op_duration:.3f}s: {e}", exc_info=True)
        try:
            if deferred:
                await interaction.followup.send("An error occurred. Please try `!startquiz` again.", ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Try `!startquiz` again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in realm selection error handler: {ie}", exc_info=True)


async def handle_quiz_answer(interaction: discord.Interaction, choice_index: int, question_index_answered: int):
    user_id = interaction.user.id
    logging.info(f"Processing quiz answer for User {user_id}, Q{question_index_answered + 1} with option index {choice_index}, Interaction ID: {interaction.id}")

    session = user_sessions.get(user_id)
    # Crucial check: ensure the interaction corresponds to the user's current question step
    if not session or session.get("step") != question_index_answered:
        logging.warning(f"Invalid state for user {user_id} answering Q{question_index_answered + 1}. "
                        f"Session step: {session.get('step') if session else 'None'}. Expected: {question_index_answered}")
        try:
            # It's important to respond to the interaction, even if it's just to say it's invalid.
            if not interaction.response.is_done():
                await interaction.response.send_message("This question is no longer active or your session has an issue. Please use `!startquiz` to restart.", ephemeral=True)
            # No followup here as this interaction might be for an old, already responded-to message
        except discord.NotFound:
            logging.warning(f"Interaction {interaction.id} (user {user_id}, Q{question_index_answered+1}) already gone when quiz answer state invalid.")
        except Exception as e:
            logging.error(f"Error informing user about invalid quiz answer state: {e}")
        return

    deferred = False
    defer_start_time = time.monotonic()
    try:
        logging.info(f"Attempting interaction.response.defer() for interaction {interaction.id} (quiz answer)")
        await interaction.response.defer(thinking=False, ephemeral=False)
        defer_duration = time.monotonic() - defer_start_time
        logging.info(f"interaction.response.defer() for {interaction.id} succeeded in {defer_duration:.3f}s (quiz answer)")
        deferred = True

        current_question_data = questions[question_index_answered]
        
        session["scores"].append(current_question_data["scores"][choice_index])
        session["step"] += 1

        # Edit the original message to confirm the choice and remove buttons
        await interaction.edit_original_response(
            content=f"✅ You chose: **{current_question_data['options'][choice_index]}** for \"{current_question_data['question']}\"",
            view=None 
        )
        
        await send_question(interaction.channel, user_id)

    except discord.NotFound as e:
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"NotFound for {interaction.id} during quiz answer after {op_duration:.3f}s: {e}", exc_info=True)
    except Exception as e:
        op_duration = time.monotonic() - defer_start_time
        logging.error(f"Error processing quiz answer for {interaction.id} after {op_duration:.3f}s: {e}", exc_info=True)
        try:
            if deferred:
                await interaction.followup.send("An error occurred while processing your answer. Try `!startquiz` again.", ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Try `!startquiz` again.", ephemeral=True)
        except Exception as ie:
            logging.error(f"Error sending followup/response in quiz answer error handler: {ie}", exc_info=True)


async def send_question(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.get(author_id)
    if session is None:
        logging.warning(f"No session for user {author_id} in send_question")
        await channel.send("Oops! Couldn't find your quiz session. Please try `!startquiz` again.")
        return

    current_step = session.get("step")
    # Check if current_step is valid for asking a question (i.e., non-negative and within bounds)
    if not isinstance(current_step, int) or current_step < STEP_QUIZ_START:
        logging.warning(f"Invalid step {current_step} for user {author_id} in send_question (expected >= {STEP_QUIZ_START}). Quiz flow might be broken.")
        # Avoid popping session here unless certain, could be a transient issue or result is next
        if current_step < STEP_QUIZ_START: # Only if it's a pre-quiz step, indicating definite error
             user_sessions.pop(author_id, None)
             await channel.send("There was an issue with your quiz progression. Please try `!startquiz` again.")
        return

    if current_step >= len(questions):
        logging.info(f"Quiz completed for user {author_id}. Showing results.")
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
        # Try to DM the user about the error if channel send failed
        user = bot.get_user(author_id)
        if user:
            try:
                await user.send("I tried to send you a quiz question, but I don't have permission in that channel. Please check and try again, or use `!startquiz` in a channel where I can send messages.")
            except discord.Forbidden:
                logging.error(f"Also unable to DM user {author_id} about send permission error.")
    except Exception as e:
        logging.error(f"Failed to send question {current_step + 1} to user {author_id}: {e}", exc_info=True)


async def show_result(channel: discord.abc.Messageable, author_id: int):
    session = user_sessions.pop(author_id, None) # Important: Result shown, session consumed.
    if not session or "scores" not in session or not session["scores"]:
        logging.warning(f"No session or empty scores for user {author_id} when trying to show result.")
        await channel.send("Hmm, it seems your fairy essence couldn't be determined (no answers recorded). Try the quiz again!")
        return

    score_counts = Counter(session["scores"])
    if not score_counts: # Should be caught by above, but defensive.
        logging.warning(f"Empty score_counts for user {author_id} despite having scores list.")
        await channel.send("Your answers didn't result in a fairy type. Please try the quiz again!")
        return

    result_fairy_type = score_counts.most_common(1)[0][0]
    chosen_prefix = result_fairy_type if result_fairy_type in prefixes else random.choice(prefixes)
    chosen_suffix = random.choice(suffixes)
    fairy_name = f"{chosen_prefix} {chosen_suffix}"
    lore_snippet = fairy_lore.get(result_fairy_type, "A mysterious and enchanting fairy, with tales yet to be widely told.")
    
    user = bot.get_user(author_id) # Fetch user object once
    display_name = user.display_name if user else "Mysterious Soul"
    avatar_url = user.avatar.url if user and user.avatar else None

    # If in a guild context, try to get member-specific display name and avatar
    if isinstance(channel, discord.TextChannel) and channel.guild:
        member = channel.guild.get_member(author_id)
        if member: # Member might be None if they left
            display_name = member.display_name # Guild-specific display name
            avatar_url = member.display_avatar.url # Guild-specific avatar if set, else global

    embed = discord.Embed(title="✨ Your Inner Fairy Revealed! ✨", color=discord.Color.random())
    if avatar_url:
        embed.set_author(name=f"{display_name}'s Fairy Form", icon_url=avatar_url)
    else:
        embed.set_author(name=f"{display_name}'s Fairy Form") # No icon if no avatar_url
    embed.add_field(name="Fairy Type", value=f"**{result_fairy_type}**", inline=False)
    embed.add_field(name="Your Fairy Name", value=f"**{fairy_name}**", inline=False)
    if 'gender' in session: # Check if gender key exists
        embed.add_field(name="Gender Chosen", value=f"*{session['gender']}*", inline=True)
    if 'realm' in session: # Check if realm key exists
        embed.add_field(name="Realm Chosen", value=f"*{session['realm']}*", inline=True)
    embed.add_field(name="About Your Kind", value=f"*{lore_snippet}*", inline=False)
    embed.set_footer(text="(An image of your fairy form remains shrouded in mist... for now!)")
    
    try:
        await channel.send(embed=embed)
        logging.info(f"Result sent to user {author_id}. Fairy type: {result_fairy_type}")
    except discord.Forbidden:
        logging.error(f"Lacking permissions to send result to user {author_id} in channel {channel.id}")
    except Exception as e:
        logging.error(f"Failed to send result to user {author_id}: {e}", exc_info=True)


# --- Bot Events ---

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name} ({bot.user.id})')
    logging.info(f'discord.py version: {discord.__version__}')
    logging.info('The fairy quiz bot is now online!')

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot: # Ignore bot's own messages and other bots
        return
    # This bot primarily uses slash commands or prefixed commands for initiation.
    # If you had other on_message logic, it would go here.
    # For now, just ensure commands are processed.
    await bot.process_commands(message)

# --- Bot Commands ---

@bot.command(name='startquiz', help='Begin your journey to discover your inner fairy!')
async def startquiz_command(ctx: commands.Context):
    author_id = ctx.author.id
    logging.info(f"!startquiz initiated by {ctx.author} ({author_id}) in channel {ctx.channel.id}")

    if author_id in user_sessions:
        session = user_sessions[author_id]
        current_step = session.get("step")
        # Check if quiz is actively in progress (selection phase or question phase)
        if isinstance(current_step, int) and \
           (current_step == STEP_AWAITING_GENDER or \
            current_step == STEP_AWAITING_REALM or \
            (STEP_QUIZ_START <= current_step < len(questions))):
            step_desc = "selection phase"
            if current_step == STEP_AWAITING_GENDER: step_desc = "gender selection"
            elif current_step == STEP_AWAITING_REALM: step_desc = "realm selection"
            elif current_step >= STEP_QUIZ_START: step_desc = f"question {current_step + 1}"
            
            await ctx.send(
                f"{ctx.author.mention}, you already have a quiz in progress (at {step_desc}). "
                "Please complete it or wait for it to time out."
            )
            logging.info(f"Blocked !startquiz for {ctx.author}: quiz already in progress at step {current_step} ({step_desc}).")
            return
        else: 
            # Session exists but is in a completed or invalid state, clear it before starting anew
            logging.info(f"Clearing old/invalid session for {ctx.author} (step: {current_step}) before starting new quiz.")
            user_sessions.pop(author_id, None)

    # Initialize session for the user starting the quiz
    user_sessions[author_id] = {"step": STEP_AWAITING_GENDER, "scores": []} # Initial step
    logging.info(f"New quiz session initialized for {author_id} at step {STEP_AWAITING_GENDER}")

    gender_view = GenderSelectionView(author_id)
    try:
        initial_message = await ctx.send(
            f"Welcome, {ctx.author.mention}! To discover your inner fairy, first, let's set the stage...",
            view=gender_view
        )
        gender_view.message = initial_message 
        logging.info(f"GenderSelectionView sent to {ctx.author}")
    except discord.Forbidden:
        logging.error(f"Bot lacks permission to send messages in {ctx.channel.name} ({ctx.guild.name if ctx.guild else 'DM'})")
        user_sessions.pop(author_id, None) # Clean up session if send failed
        try:
            await ctx.author.send("I couldn't send a message in the channel where you used `!startquiz`. Please check my permissions or try in a different channel.")
        except discord.Forbidden:
            logging.error(f"Bot also lacks permission to DM {ctx.author} about the channel permission issue.")
    except Exception as e:
        logging.error(f"Failed to send GenderSelectionView to {ctx.author}: {e}", exc_info=True)
        user_sessions.pop(author_id, None) # Clean up session
        try:
            await ctx.send("Sorry, something went wrong while trying to start the quiz. Please try again later.", ephemeral=True) # ephemeral might fail in DMs
        except Exception as e_ephemeral:
            logging.error(f"Error sending ephemeral error message to context: {e_ephemeral}")


# Optional: A command to check bot's network connectivity (similar to the diagnostic)
@bot.command(name="pingnet", help="Tests basic network connectivity to Google.", hidden=True)
@commands.is_owner() # Restrict to bot owner
async def pingnet_command(ctx: commands.Context):
    async with aiohttp.ClientSession() as http_session:
        test_url = "https://www.google.com"
        logging.info(f"Attempting diagnostic GET to {test_url} by owner request.")
        http_diag_start_time = time.monotonic()
        try:
            async with http_session.get(test_url, timeout=aiohttp.ClientTimeout(total=10.0)) as resp:
                await resp.text(encoding='utf-8') # Specify encoding
                http_diag_duration = time.monotonic() - http_diag_start_time
                status_msg = f"Diagnostic GET to {test_url} status: {resp.status}, took {http_diag_duration:.3f}s"
                logging.info(status_msg)
                await ctx.send(status_msg)
        except Exception as http_e:
            http_diag_duration = time.monotonic() - http_diag_start_time
            error_msg = f"Diagnostic GET to {test_url} failed after {http_diag_duration:.3f}s: {http_e}"
            logging.error(error_msg, exc_info=True)
            await ctx.send(error_msg)

# --- Main Execution ---
if __name__ == "__main__":
    TOKEN = os.getenv('TOKEN') 
    if TOKEN is None:
        logging.warning("TOKEN environment variable not found. Using hardcoded fallback for DEV ONLY.")
        # IMPORTANT: Replace with your actual token for testing if needed AND if you understand the risks.
        # It's best to set the TOKEN environment variable.
        TOKEN = "YOUR_BOT_TOKEN_HERE" # Replace this if you must test without .env

    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE": # Added check for placeholder
        logging.critical("FATAL ERROR: No valid bot token provided in TOKEN environment variable or hardcoded. Exiting.")
    else:
        try:
            bot.run(TOKEN, log_handler=None) # Using custom logging, so disable default handler
        except discord.LoginFailure:
            logging.critical("FATAL ERROR: Improper token has been passed. Login failed.")
        except discord.HTTPException as e:
            if e.status == 429: 
                logging.critical("FATAL ERROR: Too many requests (429). You might be rate-limited by Discord.")
            else:
                logging.critical(f"FATAL ERROR: An HTTP error occurred: {e.status} {e.text if e.text else 'No further text.'}")
            logging.critical(traceback.format_exc())
        except Exception as e:
            logging.critical(f"FATAL ERROR: An unexpected error occurred while trying to run the bot: {e}")
            logging.critical(traceback.format_exc())