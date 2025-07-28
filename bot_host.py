import os
import logging
import subprocess
from uuid import uuid4
from typing import Dict
from telegram import Update, ParseMode
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    MessageHandler,
    Filters,
    ConversationHandler
)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
EDIT_VAR, ADD_VAR, DEL_VAR = range(3)

# --- Main Bot Class ---
class BotHostingService:
    def __init__(self, token: str):
        """Initialize the bot hosting service"""
        self.updater = Updater(token=token, use_context=True)
        self.active_bots: Dict[str, dict] = {}  # Track running bots
        self._setup_handlers()
        
    def _setup_handlers(self):
        """Configure all command handlers"""
        handlers = [
            CommandHandler("start", self._cmd_start),
            CommandHandler("help", self._cmd_help),
            
            # Bot hosting commands
            CommandHandler("host", self._cmd_host),
            CommandHandler("stop", self._cmd_stop),
            CommandHandler("list", self._cmd_list),
            
            # Environment variable management
            CommandHandler("vars", self._cmd_vars_menu),
            CommandHandler("show_vars", self._cmd_show_vars),
            MessageHandler(Filters.document, self._handle_env_file),
            
            # Variable editing conversation
            ConversationHandler(
                entry_points=[
                    CommandHandler("edit_var", self._cmd_edit_var_start),
                    CommandHandler("add_var", self._cmd_add_var_start),
                    CommandHandler("del_var", self._cmd_del_var_start)
                ],
                states={
                    EDIT_VAR: [MessageHandler(Filters.text & ~Filters.command, self._cmd_edit_var_complete)],
                    ADD_VAR: [MessageHandler(Filters.text & ~Filters.command, self._cmd_add_var_complete)],
                    DEL_VAR: [MessageHandler(Filters.text & ~Filters.command, self._cmd_del_var_complete)]
                },
                fallbacks=[CommandHandler("cancel", self._cmd_cancel)]
            )
        ]
        
        for handler in handlers:
            self.updater.dispatcher.add_handler(handler)

    # --- Core Methods ---
    def run(self):
        """Start the bot"""
        self.updater.start_polling()
        logger.info("Bot Hosting Service is running...")
        self.updater.idle()

    # --- Command Handlers ---
    def _cmd_start(self, update: Update, context: CallbackContext):
        """Welcome message"""
        help_text = (
            "🤖 *Bot Hosting Service*\n\n"
            "_Host and manage Telegram bots from GitHub repositories_\n\n"
            "📋 Main Commands:\n"
            "/host - Deploy a bot from GitHub\n"
            "/stop - Stop a running bot\n"
            "/list - Show all active bots\n"
            "/vars - Environment variables menu\n\n"
            "🛠️ Need help? Type /help"
        )
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    def _cmd_help(self, update: Update, context: CallbackContext):
        """Detailed help menu"""
        help_text = (
            "📚 *Help Menu*\n\n"
            "🔹 *Bot Hosting*:\n"
            "/host <repo_url> - Deploy bot from GitHub\n"
            "/stop <bot_id> - Stop a running bot\n"
            "/list - Show active bots\n\n"
            "🔹 *Environment Variables*:\n"
            "/vars - Variables management menu\n"
            "/show_vars - View all variables\n\n"
            "🔹 *File Upload*:\n"
            "Send .env file to bulk update variables\n\n"
            "⚙️ Create persistent variables by saving to file"
        )
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    # --- Bot Management ---
    def _cmd_host(self, update: Update, context: CallbackContext):
        """Host a new bot from GitHub"""
        if not context.args:
            update.message.reply_text("❌ Please provide GitHub URL")
            return

        repo_url = context.args[0]
        bot_id = str(uuid4())[:6]  # Short ID
        
        try:
            # Clone and setup
            repo_dir = f"bot_{bot_id}"
            update.message.reply_text(f"⬇️ Cloning {repo_url}...")
            subprocess.run(["git", "clone", repo_url, repo_dir], check=True)
            
            # Install requirements
            req_file = os.path.join(repo_dir, "requirements.txt")
            if os.path.exists(req_file):
                update.message.reply_text("🔧 Installing dependencies...")
                subprocess.run(["pip", "install", "-r", req_file], check=True, cwd=repo_dir)
            
            # Start the bot
            main_file = self._find_main_file(repo_dir)
            process = subprocess.Popen(
                ["python", main_file],
                cwd=repo_dir,
                env=os.environ.copy()
            )
            
            self.active_bots[bot_id] = {
                "process": process,
                "repo": repo_url,
                "dir": repo_dir
            }
            
            update.message.reply_text(
                f"✅ Bot deployed!\n\n"
                f"🆔 ID: `{bot_id}`\n"
                f"📂 Dir: `{repo_dir}`",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            update.message.reply_text(f"❌ Error: {str(e)}")

    def _cmd_stop(self, update: Update, context: CallbackContext):
        """Stop a running bot"""
        if not context.args:
            update.message.reply_text("❌ Provide bot ID (/list to see IDs)")
            return
            
        bot_id = context.args[0]
        if bot_id not in self.active_bots:
            update.message.reply_text("❌ Bot not found")
            return
            
        try:
            self.active_bots[bot_id]["process"].terminate()
            del self.active_bots[bot_id]
            update.message.reply_text(f"🛑 Bot {bot_id} stopped")
        except Exception as e:
            update.message.reply_text(f"❌ Failed: {str(e)}")

    def _cmd_list(self, update: Update, context: CallbackContext):
        """List all hosted bots"""
        if not self.active_bots:
            update.message.reply_text("No active bots")
            return
            
        msg = "🤖 *Active Bots*\n\n"
        for bot_id, info in self.active_bots.items():
            status = "✅ Running" if info["process"].poll() is None else "❌ Stopped"
            msg += (
                f"🆔 *{bot_id}*\n"
                f"📦 Repo: {info['repo']}\n"
                f"📌 Status: {status}\n\n"
            )
        update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    # --- Environment Variable Management ---
    def _cmd_vars_menu(self, update: Update, context: CallbackContext):
        """Environment variables menu"""
        help_text = (
            "⚙️ *Variable Management*\n\n"
            "/show_vars - View all variables\n"
            "/edit_var - Modify existing variable\n"
            "/add_var - Add new variable\n"
            "/del_var - Delete variable\n\n"
            "📁 You can also upload .env file"
        )
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        
    def _cmd_show_vars(self, update: Update, context: CallbackContext):
        """Display current environment variables"""
        vars_list = "\n".join(
            f"➤ `{k}`=`{v}`"
            for k, v in os.environ.items()
            if not k.startswith("RENDER_")
        )
        update.message.reply_text(
            f"📋 *Environment Variables*\n\n{vars_list}",
            parse_mode=ParseMode.MARKDOWN
        )

    def _handle_env_file(self, update: Update, context: CallbackContext):
        """Handle .env file uploads"""
        if not update.message.document.file_name.endswith(".env"):
            update.message.reply_text("Please upload a .env file")
            return
            
        try:
            file = context.bot.get_file(update.message.document.file_id)
            file.download("temp.env")
            
            with open("temp.env") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        os.environ[key] = value
            
            update.message.reply_text("✅ Variables updated from file")
        except Exception as e:
            update.message.reply_text(f"❌ Error: {str(e)}")

    # --- Variable Editing Conversation ---
    def _cmd_edit_var_start(self, update: Update, context: CallbackContext) -> int:
        """Start variable editing process"""
        update.message.reply_text(
            "✏️ Enter variable to edit in format:\n"
            "VAR_NAME=new_value\n\n"
            "Current variables:\n" +
            "\n".join(f"`{k}`" for k in os.environ.keys())
        )
        return EDIT_VAR

    def _cmd_edit_var_complete(self, update: Update, context: CallbackContext) -> int:
        """Complete variable edit"""
        try:
            var, value = update.message.text.split("=", 1)
            if var in os.environ:
                os.environ[var] = value
                update.message.reply_text(f"✅ Updated `{var}`")
                self._save_persistent_vars()
            else:
                update.message.reply_text(f"❌ Variable `{var}` not found")
        except ValueError:
            update.message.reply_text("Invalid format. Use: VAR_NAME=new_value")
        return ConversationHandler.END

    # [Similar _cmd_add_var_start, _cmd_add_var_complete, 
    #  _cmd_del_var_start, _cmd_del_var_complete methods...]

    def _cmd_cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel current operation"""
        update.message.reply_text("🚫 Operation cancelled")
        return ConversationHandler.END

    # --- Helper Methods ---
    def _find_main_file(self, directory: str) -> str:
        """Find main python file in directory"""
        py_files = [f for f in os.listdir(directory) if f.endswith(".py")]
        if not py_files:
            raise ValueError("No Python files found in repository")
        return sorted(py_files)[0]  # Simple heuristic: pick first sorted file

    def _save_persistent_vars(self, filename: str = "persistent.env"):
        """Save variables to file for persistence"""
        with open(filename, "w") as f:
            for k, v in os.environ.items():
                if not k.startswith("RENDER_"):
                    f.write(f"{k}={v}\n")

# --- Main Execution ---
if __name__ == "__main__":
    token = os.getenv("TELEGRAM_HOST_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_HOST_TOKEN environment variable required")
    
    service = BotHostingService(token)
    service.run()
