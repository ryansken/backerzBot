import json, os, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ChatMemberHandler, ContextTypes
)

# ===== EDIT THESE TWO LINES (keep the quotes) =====
BOT_TOKEN = "8029947533:AAEeoYMeOxm7OBL3j05UahDfp-FotFhu-84"
JOIN_LINK = "https://t.me/+HnzqYOSD66E3Y2M9"
ADMIN_ID = 5141258118

# ==================================================

DATA_FILE = "ref_data.json"

def load():
    if not os.path.exists(DATA_FILE):
        return {"group_id": None, "users": {}, "pending": {}, "confirmed": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save(d):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def handle_of(user) -> str:
    return f"@{user.username}" if user.username else f"{user.first_name or 'user'}"

# /start (supports deep-link ?start=<referrer_id>)
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load()
    u = update.effective_user
    d["users"].setdefault(str(u.id), {"username": u.username or "", "score": 0})
    d["users"][str(u.id)]["username"] = u.username or d["users"][str(u.id)]["username"]

    if ctx.args:
        referrer = ctx.args[0].strip()
        if referrer and referrer != str(u.id) and str(u.id) not in d["pending"]:
            d["users"].setdefault(referrer, {"username": "", "score": 0})
            d["pending"][str(u.id)] = referrer
            save(d)

    kb = [[InlineKeyboardButton("✅ I'm real — let me in", callback_data="verify")]]
    await update.message.reply_text(
        "Welcome to Backerz.\n\nIf someone sent you, their referral locks when you verify "
        "and then **join the group**.\nTap below to verify and get the invite link.",
        reply_markup=InlineKeyboardMarkup(kb),
        disable_web_page_preview=True
    )

# Verify button → send the single group invite link
async def on_verify(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Verified")
    await q.edit_message_text("Verified ✅\n\nJoin the group here:\n" + JOIN_LINK +
                              "\n\nAfter you join, referral will auto-confirm.")

# Give a user's personal deep-link
async def cmd_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    me = await ctx.bot.get_me()
    u = update.effective_user
    link = f"https://t.me/{me.username}?start={u.id}"
    await update.message.reply_text("Your personal referral link:\n" + link)

# Bind to THIS group (run once inside the group)
async def cmd_bind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        d = load()
        d["group_id"] = update.effective_chat.id
        save(d)
        msg = await update.message.reply_text(f"Group bound ✅ (id: {d['group_id']})")
        # Try to hide the setup chatter
        try:
            await ctx.bot.delete_message(update.effective_chat.id, msg.message_id)
            await ctx.bot.delete_message(update.effective_chat.id, update.message.message_id)
        except Exception:
            pass
    else:
        await update.message.reply_text("Run /bind inside your Backerz **group** (not DM).")

# When someone joins the bound group → confirm referral
def _is_join(cmu) -> bool:
    old = cmu.old_chat_member.status
    new = cmu.new_chat_member.status
    return (old in ("left", "kicked")) and (new in ("member", "administrator"))

async def on_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    print("chat_member:", cmu.chat.id, cmu.new_chat_member.user.id, cmu.old_chat_member.status, "->", cmu.new_chat_member.status, flush=True)

    if not cmu:
        return
    d = load()
    if d.get("group_id") != cmu.chat.id:
        return
    if not _is_join(cmu):
        return

    joined = cmu.new_chat_member.user
    referee_id = str(joined.id)
    referrer_id = d["pending"].pop(referee_id, None)
    if not referrer_id:
        return

    # award
    d["users"].setdefault(referrer_id, {"username": "", "score": 0})
    d["users"][referrer_id]["score"] = int(d["users"][referrer_id].get("score", 0)) + 1
    d["confirmed"].append({"referrer": int(referrer_id), "referee": int(referee_id), "ts": int(time.time())})
    save(d)

    # notify
    try:
        await ctx.bot.send_message(int(referrer_id),
            f"✅ Referral confirmed! {handle_of(joined)} joined.\nTotal: {d['users'][referrer_id]['score']}")
    except Exception:
        pass
    # admin log (clean usernames or clickable mentions, no raw IDs)
try:
    ref_chat = await ctx.bot.get_chat(int(referrer_id))
    joined_chat = joined  # already have user

    def mention(uid, chat):
        if getattr(chat, "username", None):
            return f"@{chat.username}"
        label = getattr(chat, "first_name", None) or "user"
        return f'<a href="tg://user?id={uid}">{label}</a>'

    await ctx.bot.send_message(
        ADMIN_ID,
        f"Ref confirmed: {mention(joined.id, joined_chat)} via {mention(int(referrer_id), ref_chat)} — total {d['users'][referrer_id]['score']}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
except Exception:
    pass




# Show your score
async def cmd_my(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load()
    u = update.effective_user
    score = int(d["users"].get(str(u.id), {}).get("score", 0))
    await update.message.reply_text(f"Your score: {score}")

# Leaderboard
async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = load()
    items = [(int(uid), rec.get("username",""), int(rec.get("score",0))) for uid, rec in d["users"].items()]
    items.sort(key=lambda x: (-x[2], x[0]))
    top = [x for x in items if x[2] > 0][:10]
    if not top:
        await update.message.reply_text("No referrals yet.")
        return
    lines = []
    for i,(uid, uname, score) in enumerate(top, 1):
        handle = f"@{uname}" if uname else f"user {uid}"
        lines.append(f"{i}. {handle} — {score}")
    await update.message.reply_text("🏆 Leaderboard\n" + "\n".join(lines))

# ---- stable launcher ----
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_verify, pattern="^verify$"))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("bind", cmd_bind))
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("top", cmd_top))
    print("Bot running…")
    app.run_polling(allowed_updates=["message","chat_member","my_chat_member","callback_query"])


if __name__ == "__main__":
    main()

