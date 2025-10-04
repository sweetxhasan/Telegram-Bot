import os
import json
import requests
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import random
import html as html_escape
import uuid
import asyncio
from aiohttp import web

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8033779980:AAECGMj1LKfMoL6ucso9tFYgB7TyHXcXm6E")
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')
WEB_PORT = int(os.environ.get('PORT', 5000))
SCRAPINGBEE_API_URL = "https://app.scrapingbee.com/api/v1/"

# Data storage files - use absolute paths for Render
ADMIN_FILE = "data/admin_data.json"
API_KEYS_FILE = "data/api_keys.json"
REQUESTS_FILE = "data/requests_data.json"
USERS_FILE = "data/users_data.json"
API_REQUESTS_FILE = "data/api_requests_data.json"

# Create data directory if it doesn't exist
os.makedirs("data", exist_ok=True)

class BotDataManager:
    def __init__(self):
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        
        self.admin_data = self.load_data(ADMIN_FILE)
        self.api_keys = self.load_data(API_KEYS_FILE)
        self.requests_data = self.load_data(REQUESTS_FILE)
        self.users_data = self.load_data(USERS_FILE)
        self.api_requests = self.load_data(API_REQUESTS_FILE)
        
        # Initialize default data if files don't exist
        if not self.admin_data:
            self.admin_data = {"admin_id": None}
        if not self.api_keys:
            self.api_keys = {"keys": [], "next_id": 1}
        if not self.requests_data:
            self.requests_data = {"total_requests": 0, "today_requests": 0, "last_reset": str(date.today())}
        if not self.users_data:
            self.users_data = {"users": {}, "next_request_id": 1}
        if not self.api_requests:
            self.api_requests = {"requests": [], "next_id": 1}

    def load_data(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def save_data(self, data, filename):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving data to {filename}: {e}")
            return False

    def save_admin_data(self):
        return self.save_data(self.admin_data, ADMIN_FILE)

    def save_api_keys(self):
        return self.save_data(self.api_keys, API_KEYS_FILE)

    def save_requests_data(self):
        return self.save_data(self.requests_data, REQUESTS_FILE)

    def save_users_data(self):
        return self.save_data(self.users_data, USERS_FILE)

    def save_api_requests(self):
        return self.save_data(self.api_requests, API_REQUESTS_FILE)

    def reset_daily_requests_if_needed(self):
        today = str(date.today())
        if self.requests_data.get("last_reset") != today:
            self.requests_data["today_requests"] = 0
            self.requests_data["last_reset"] = today
            self.save_requests_data()

    def increment_requests(self):
        self.reset_daily_requests_if_needed()
        self.requests_data["total_requests"] += 1
        self.requests_data["today_requests"] += 1
        self.save_requests_data()

    def add_api_key(self, api_key):
        # Find the maximum existing ID to avoid duplication
        existing_ids = [key["id"] for key in self.api_keys["keys"]]
        new_id = max(existing_ids) + 1 if existing_ids else 1
        
        key_data = {
            "id": new_id,
            "key": api_key,
            "added_date": str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }
        self.api_keys["keys"].append(key_data)
        self.save_api_keys()
        return new_id

    def delete_api_key(self, api_id):
        self.api_keys["keys"] = [key for key in self.api_keys["keys"] if key["id"] != api_id]
        self.save_api_keys()

    def get_random_api_key(self):
        if not self.api_keys["keys"]:
            return None
        return random.choice(self.api_keys["keys"])["key"]

    def add_or_update_user(self, user_id, user_name, country="Unknown"):
        if str(user_id) not in self.users_data["users"]:
            self.users_data["users"][str(user_id)] = {
                "name": user_name,
                "join_date": str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "api_requests_count": 0,
                "country": country
            }
        else:
            # Update user name if changed
            self.users_data["users"][str(user_id)]["name"] = user_name
        self.save_users_data()

    def increment_user_requests(self, user_id):
        if str(user_id) in self.users_data["users"]:
            self.users_data["users"][str(user_id)]["api_requests_count"] += 1
            self.save_users_data()

    def get_users_count(self):
        return len(self.users_data["users"])

    def add_api_request(self, user_id, user_name, url, status, response_code=None):
        request_data = {
            "id": self.api_requests["next_id"],
            "user_id": user_id,
            "user_name": user_name,
            "url": url,
            "status": status,
            "response_code": response_code,
            "date": str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }
        self.api_requests["requests"].insert(0, request_data)  # Add to beginning for newest first
        self.api_requests["next_id"] += 1
        
        # Keep only last 1000 requests to prevent file from growing too large
        if len(self.api_requests["requests"]) > 1000:
            self.api_requests["requests"] = self.api_requests["requests"][:1000]
        
        self.save_api_requests()
        return request_data["id"]

# Initialize data manager
data_manager = BotDataManager()

# User states for conversation handling
USER_STATES = {}

# Global application instance
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    # Set first user as admin
    if data_manager.admin_data.get("admin_id") is None:
        data_manager.admin_data["admin_id"] = user_id
        data_manager.save_admin_data()
        await update.message.reply_text(
            "🎉 Congratulations! You are now the admin of this bot!"
        )
    
    # Add/update user data
    data_manager.add_or_update_user(user_id, user_name)
    
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    welcome_text = (
        "🤖 **Html Secure Code Downloader Bot**\n\n"
        "Bot থেকে যে যেকোনো ওয়েবসাইট এর Html code ডাউনলোড করা যায়!\n\n"
        "যেকোনো ওয়েবসাইটের HTML কোড সুরক্ষিতভাবে ডাউনলোড করুন।"
    )
    
    keyboard = []
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin_dashboard")])
    
    keyboard.append([InlineKeyboardButton("🚀 Start Code Download", callback_data="start_download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    if data == "start_download":
        USER_STATES[user_id] = "waiting_for_url"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌐 **Enter website/page URL:**\n\n"
            "Please send the URL of the website you want to download HTML code from.\n\n"
            "You can cancel this operation using the button below:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == "admin_dashboard" and is_admin:
        await show_admin_dashboard(query)
    
    elif data == "add_api_key" and is_admin:
        USER_STATES[user_id] = "waiting_for_api_key"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔑 **Add API Key**\n\n"
            "Please enter your ScrapingBee API key:\n\n"
            "You can cancel this operation using the button below:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == "api_key_list" and is_admin:
        await show_api_key_list(query)
    
    elif data == "delete_api_key" and is_admin:
        USER_STATES[user_id] = "waiting_for_api_id"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🗑️ **Delete API Key**\n\n"
            "Please enter the API ID you want to delete:\n\n"
            "You can cancel this operation using the button below:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == "user_list" and is_admin:
        await show_user_list(query)
    
    elif data == "api_requests_list" and is_admin:
        await show_api_requests_list(query)
    
    elif data == "back_to_main":
        await show_main_menu(update, context)
    
    elif data == "back_to_dashboard" and is_admin:
        await show_admin_dashboard(query)
    
    elif data == "new_download":
        USER_STATES[user_id] = "waiting_for_url"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌐 **Enter website/page URL:**\n\n"
            "Please send the URL of the website you want to download HTML code from.\n\n"
            "You can cancel this operation using the button below:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == "cancel_operation":
        USER_STATES.pop(user_id, None)
        if is_admin:
            await show_admin_dashboard(query)
        else:
            await show_main_menu(update, context)

async def show_admin_dashboard(query):
    data_manager.reset_daily_requests_if_needed()
    
    total_requests = data_manager.requests_data["total_requests"]
    today_requests = data_manager.requests_data["today_requests"]
    api_key_count = len(data_manager.api_keys["keys"])
    users_count = data_manager.get_users_count()
    
    dashboard_text = (
        "👑 **Admin Dashboard**\n\n"
        f"📊 **API Key Count:** `{api_key_count}`\n"
        f"📈 **Total Requests:** `{total_requests}`\n"
        f"📅 **Today's Requests:** `{today_requests}`\n"
        f"👥 **Bot Users:** `{users_count}`\n\n"
        "**Management Options:**"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add API Key", callback_data="add_api_key")],
        [InlineKeyboardButton("📋 API Key List", callback_data="api_key_list")],
        [InlineKeyboardButton("🗑️ Delete API Key", callback_data="delete_api_key")],
        [InlineKeyboardButton("👥 User List", callback_data="user_list")],
        [InlineKeyboardButton("📋 API Requests List", callback_data="api_requests_list")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(dashboard_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_api_key_list(query):
    api_keys = data_manager.api_keys["keys"]
    
    if not api_keys:
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❌ **No API Keys Found**\n\n"
            "No API keys have been added yet.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    key_list_text = "📋 **All API Key List**\n\n"
    for key_data in api_keys:
        key_list_text += f"#`{key_data['id']}` - `{key_data['key'][:20]}...` - {key_data['added_date']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(key_list_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_user_list(query):
    users = data_manager.users_data["users"]
    
    if not users:
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❌ **No Users Found**\n\n"
            "No users have used the bot yet.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    user_list_text = "👥 **User List**\n\n"
    for user_id, user_data in list(users.items())[:50]:  # Show first 50 users
        user_list_text += f"#`{user_id}` - {user_data['name']} - Requests: {user_data['api_requests_count']} - {user_data['join_date']} - {user_data.get('country', 'Unknown')}\n"
    
    if len(users) > 50:
        user_list_text += f"\n... and {len(users) - 50} more users"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(user_list_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_api_requests_list(query):
    requests = data_manager.api_requests["requests"]
    
    if not requests:
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❌ **No API Requests Found**\n\n"
            "No API requests have been made yet.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    requests_text = "📋 **API Requests List** (Newest First)\n\n"
    for req in requests[:20]:  # Show last 20 requests
        status_emoji = "✅" if req["status"] == "success" else "❌"
        requests_text += f"#{req['id']} {status_emoji} {req['status']} - {req['url'][:50]}... - {req['user_name']} - {req['date']}\n"
    
    if len(requests) > 20:
        requests_text += f"\n... and {len(requests) - 20} more requests"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(requests_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if user_id not in USER_STATES:
        # If no state, show main menu
        await show_main_menu(update, context)
        return
    
    state = USER_STATES[user_id]
    
    if state == "waiting_for_url":
        await handle_url_input(update, context, message_text)
    
    elif state == "waiting_for_api_key":
        await handle_api_key_input(update, context, message_text)
    
    elif state == "waiting_for_api_id":
        await handle_api_id_input(update, context, message_text)

async def handle_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    processing_msg = await update.message.reply_text("⏳ Fetching HTML code...")
    
    try:
        # Get random API key
        api_key = data_manager.get_random_api_key()
        if not api_key:
            await processing_msg.edit_text(
                "❌ **No API Key Available**\n\n"
                "Please add ScrapingBee API keys through the admin dashboard first.",
                parse_mode='Markdown'
            )
            USER_STATES.pop(user_id, None)
            # Show main menu after error
            await show_main_menu(update, context)
            return
        
        # Prepare API request parameters
        params = {
            'api_key': api_key,
            'url': url,
            'render_js': 'false'
        }
        
        # Make request to ScrapingBee API
        response = requests.get(SCRAPINGBEE_API_URL, params=params, timeout=30)
        
        if response.status_code == 200:
            data_manager.increment_requests()
            data_manager.increment_user_requests(user_id)
            
            html_content = response.text
            
            # Create filename
            domain = url.split('//')[-1].split('/')[0].replace('.', '-')
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{domain}-hasan-tool-{timestamp}.html"
            
            # Log successful API request
            data_manager.add_api_request(user_id, user_name, url, "success", response.status_code)
            
            # Send HTML file
            await update.message.reply_document(
                document=html_content.encode('utf-8'),
                filename=filename,
                caption=f"✅ **Successfully downloaded HTML code from:**\n`{url}`",
                parse_mode='Markdown'
            )
            
            # Show new download button
            keyboard = [
                [InlineKeyboardButton("🔄 New Code Download", callback_data="new_download")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "📄 **HTML file downloaded successfully!**\n\n"
                "Choose an option:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        else:
            # Log failed API request
            data_manager.add_api_request(user_id, user_name, url, "failed", response.status_code)
            
            error_msg = f"❌ **Error fetching HTML**\n\nStatus Code: {response.status_code}\nError: {response.text}"
            await processing_msg.edit_text(error_msg, parse_mode='Markdown')
            
            # Show menu after error
            keyboard = [
                [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Choose an option:", reply_markup=reply_markup)
            
    except Exception as e:
        # Log failed API request
        data_manager.add_api_request(user_id, user_name, url, "failed")
        
        error_msg = f"❌ **Error occurred:**\n\n{str(e)}"
        await processing_msg.edit_text(error_msg, parse_mode='Markdown')
        
        # Show menu after error
        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose an option:", reply_markup=reply_markup)
    
    finally:
        USER_STATES.pop(user_id, None)

async def handle_api_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE, api_key: str):
    user_id = update.effective_user.id
    
    # Basic API key validation
    if len(api_key) < 10:
        await update.message.reply_text("❌ Invalid API key format. Please enter a valid ScrapingBee API key.")
        return
    
    # Add API key
    new_id = data_manager.add_api_key(api_key.strip())
    
    await update.message.reply_text(
        f"✅ **API Key Added Successfully!**\n\n"
        f"API Key has been added with ID: `{new_id}`\n"
        "The API key is now ready for use.",
        parse_mode='Markdown'
    )
    
    USER_STATES.pop(user_id, None)
    # Return to admin dashboard
    await show_admin_dashboard_from_message(update)

async def handle_api_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE, api_id: str):
    user_id = update.effective_user.id
    
    try:
        api_id_int = int(api_id)
        
        # Check if API ID exists
        existing_ids = [key["id"] for key in data_manager.api_keys["keys"]]
        if api_id_int not in existing_ids:
            await update.message.reply_text("❌ API ID not found. Please check the ID and try again.")
            return
        
        # Delete API key
        data_manager.delete_api_key(api_id_int)
        
        await update.message.reply_text(
            f"✅ **API Key Deleted Successfully!**\n\n"
            f"API key with ID `{api_id_int}` has been deleted from the system.",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid API ID. Please enter a numeric ID.")
        return
    
    finally:
        USER_STATES.pop(user_id, None)
        # Return to admin dashboard
        await show_admin_dashboard_from_message(update)

async def show_admin_dashboard_from_message(update: Update):
    user_id = update.effective_user.id
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    if not is_admin:
        await show_main_menu(update, None)
        return
    
    data_manager.reset_daily_requests_if_needed()
    
    total_requests = data_manager.requests_data["total_requests"]
    today_requests = data_manager.requests_data["today_requests"]
    api_key_count = len(data_manager.api_keys["keys"])
    users_count = data_manager.get_users_count()
    
    dashboard_text = (
        "👑 **Admin Dashboard**\n\n"
        f"📊 **API Key Count:** `{api_key_count}`\n"
        f"📈 **Total Requests:** `{total_requests}`\n"
        f"📅 **Today's Requests:** `{today_requests}`\n"
        f"👥 **Bot Users:** `{users_count}`\n\n"
        "**Management Options:**"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add API Key", callback_data="add_api_key")],
        [InlineKeyboardButton("📋 API Key List", callback_data="api_key_list")],
        [InlineKeyboardButton("🗑️ Delete API Key", callback_data="delete_api_key")],
        [InlineKeyboardButton("👥 User List", callback_data="user_list")],
        [InlineKeyboardButton("📋 API Requests List", callback_data="api_requests_list")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(dashboard_text, reply_markup=reply_markup, parse_mode='Markdown')

async def health_check(request):
    return web.Response(text="Bot is running!")

async def set_webhook():
    """Set webhook for Telegram bot"""
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")

async def handle_webhook(request):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(text="Error", status=500)

async def start_bot():
    """Start the bot with webhook or polling"""
    global application
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    if WEBHOOK_URL:
        # Webhook mode for production
        await set_webhook()
        app = web.Application()
        app.router.add_get('/', health_check)
        app.router.add_post('/webhook', handle_webhook)
        return app
    else:
        # Polling mode for development
        await application.run_polling()
        return None

def main():
    # Start the bot
    if WEBHOOK_URL:
        # Production with webhook
        app = asyncio.run(start_bot())
        if app:
            web.run_app(app, host='0.0.0.0', port=WEB_PORT)
    else:
        # Development with polling
        asyncio.run(start_bot())

if __name__ == "__main__":
    main()
