"""
Command Handlers untuk Bot Telegram Admin.
Semua perintah bot didefinisikan di sini.
"""

import asyncio
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import logger, SUPER_ADMIN_CHAT_IDS
from database import db
from stockity_api import StockityAPI, StockityAPIError
from models import UserBalance, UserProfile, BotAdmin

# ============================================================
# HELPERS
# ============================================================

async def check_admin(update: Update) -> bool:
    """Cek apakah user adalah admin bot."""
    chat_id = update.effective_user.id
    is_admin = await db.is_bot_admin(chat_id)
    if not is_admin:
        await update.message.reply_text(
            "⛔ <b>Akses Ditolak</b>\n"
            "Anda tidak memiliki izin untuk mengakses bot ini.",
            parse_mode=ParseMode.HTML,
        )
    return is_admin


async def check_super_admin(update: Update) -> bool:
    """Cek apakah user adalah super admin bot."""
    chat_id = update.effective_user.id
    is_sadmin = await db.is_super_admin(chat_id)
    if not is_sadmin:
        await update.message.reply_text(
            "⛔ <b>Akses Ditolak</b>\n"
            "Hanya super admin yang bisa menggunakan perintah ini.",
            parse_mode=ParseMode.HTML,
        )
    return is_sadmin


def format_user_detail(user_id: str, email: str, balance: UserBalance,
                       profile: UserProfile, whitelist) -> str:
    """Format detail user untuk ditampilkan."""
    status = "🟢 Aktif" if whitelist and whitelist.is_active else "🔴 Nonaktif"
    last_login = whitelist.last_login_formatted if whitelist else "-"

    text = (
        f"📋 <b>DETAIL USER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Nama:</b> {profile.full_name}\n"
        f"📧 <b>Email:</b> <code>{email}</code>\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📱 <b>Telepon:</b> {profile.phone or '-'}\n"
        f"🌍 <b>Negara:</b> {profile.country or '-'}\n"
        f"🎂 <b>Ulang Tahun:</b> {profile.birthday or '-'}\n"
        f"📅 <b>Terdaftar:</b> {profile.registered_at_formatted}\n"
        f"✅ <b>Email Terverifikasi:</b> {'Ya' if profile.email_verified else 'Tidak'}\n"
        f"✅ <b>Dokumen Terverifikasi:</b> {'Ya' if profile.docs_verified else 'Tidak'}\n"
        f"🔒 <b>Data Terkunci:</b> {'Ya' if profile.personal_data_locked else 'Tidak'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>SALDO AKUN REAL</b>\n"
        f"   <b>Real:</b> <code>{balance.real_balance_formatted}</code>\n"
        f"   <b>Demo:</b> <code>{balance.demo_balance_formatted}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ <b>Status Whitelist:</b> {status}\n"
        f"🕐 <b>Login Terakhir:</b> {last_login}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return text


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /start - inisialisasi admin."""
    user = update.effective_user
    chat_id = user.id

    # Cek apakah sudah terdaftar sebagai admin
    existing = await db.get_bot_admin(chat_id)

    if existing:
        await update.message.reply_text(
            f"👋 <b>Selamat datang kembali, {existing.display_name}!</b>\n\n"
            f"Anda terdaftar sebagai <b>{'Super Admin' if existing.role == 'super_admin' else 'Admin'}</b>.\n"
            f"Gunakan /help untuk melihat daftar perintah.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Auto-register super admin jika:
    # 1. SUPER_ADMIN_CHAT_IDS dikonfigurasi dan chat_id ada di daftar
    # 2. Atau belum ada admin sama sekali
    admin_count = await db.count_bot_admins()

    is_preconfigured = chat_id in SUPER_ADMIN_CHAT_IDS
    is_first_admin = admin_count == 0

    if is_preconfigured or is_first_admin:
        new_admin = BotAdmin(
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            role="super_admin",
            is_active=True,
            created_by=chat_id if is_first_admin else None,
        )
        await db.add_bot_admin(new_admin)

        await update.message.reply_text(
            f"🎉 <b>Selamat datang, Super Admin!</b>\n\n"
            f"Anda telah terdaftar sebagai super admin pertama.\n"
            f"Nama: {new_admin.display_name}\n"
            f"Chat ID: <code>{chat_id}</code>\n\n"
            f"Gunakan /help untuk melihat daftar perintah.",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Super admin registered: {chat_id} ({user.username})")
    else:
        await update.message.reply_text(
            "⛕ <b>Akses Ditolak</b>\n\n"
            "Anda belum terdaftar sebagai admin bot.\n"
            "Hubungi super admin untuk mendapatkan akses.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /help - daftar semua perintah."""
    if not await check_admin(update):
        return

    is_sadmin = await db.is_super_admin(update.effective_user.id)

    text = (
        f"📖 <b>DAFTAR PERINTAH BOT ADMIN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>🧑‍💼 Manajemen Admin:</b>\n"
        f"  /admins - Lihat daftar admin bot\n"
    )

    if is_sadmin:
        text += (
            f"  /addadmin [chat_id] - Tambah admin baru\n"
            f"  /removeadmin [chat_id] - Hapus admin\n"
            f"  /toggleadmin [chat_id] - Aktifkan/nonaktifkan admin\n"
        )

    text += (
        f"\n<b>👥 Manajemen User:</b>\n"
        f"  /users - Lihat daftar user (whitelist)\n"
        f"  /user [id/email] - Detail user lengkap\n"
        f"  /search [keyword] - Cari user\n"
        f"  /aktifkan [email] - Aktifkan user\n"
        f"  /nonaktifkan [email] - Nonaktifkan user\n"
        f"\n<b>💰 Saldo & Deposit:</b>\n"
        f"  /allsaldo - Semua saldo user aktif (live fetch)\n"
        f"  /saldo [user_id] - Cek saldo akun real by ID\n"
        f"  /saldobyemail [email] - Cek saldo by email\n"
        f"  /depositlog - Log deposit 24 jam terakhir\n"
        f"  /depositlog7 - Log deposit 7 hari terakhir\n"
        f"\n<b>📊 Statistik:</b>\n"
        f"  /stats - Statistik user\n"
        f"  /cekstatus [user_id] - Cek status lengkap user\n"
        f"\n<b>📢 Komunikasi:</b>\n"
        f"  /broadcast [pesan] - Kirim pesan ke semua admin\n"
        f"\n<b>⚙️ Utilitas:</b>\n"
        f"  /myid - Lihat chat ID Anda\n"
        f"  /ping - Cek bot status\n"
        f"  /help - Tampilkan bantuan ini\n"
        f"\n━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /ping - cek status bot."""
    if not await check_admin(update):
        return

    start = datetime.utcnow()
    # Cek koneksi Supabase
    stats = await db.get_user_statistics()
    elapsed = (datetime.utcnow() - start).total_seconds() * 1000

    await update.message.reply_text(
        f"🏓 <b>PONG!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Latency: <code>{elapsed:.1f}ms</code>\n"
        f"🗄️ Supabase: <code>Connected</code>\n"
        f"👥 Total Users: <code>{stats.total}</code>\n"
        f"📅 Server Time: <code>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML,
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /myid - lihat chat ID sendiri."""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 <b>Chat ID Anda:</b> <code>{user.id}</code>\n"
        f"👤 <b>Username:</b> @{user.username or 'tidak ada'}\n"
        f"📛 <b>Nama:</b> {user.first_name or ''} {user.last_name or ''}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN MANAGEMENT
# ============================================================

async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /admins - lihat daftar admin bot."""
    if not await check_admin(update):
        return

    admins = await db.list_bot_admins()

    if not admins:
        await update.message.reply_text("ℹ️ Belum ada admin bot yang terdaftar.")
        return

    lines = [f"👥 <b>DAFTAR ADMIN BOT ({len(admins)})</b>\n━━━━━━━━━━━━━━━━━━━━━"]
    for i, admin in enumerate(admins, 1):
        role_emoji = "👑" if admin.role == "super_admin" else "🧑‍💼"
        status = "🟢" if admin.is_active else "🔴"
        lines.append(
            f"\n{i}. {role_emoji} <b>{admin.display_name}</b>\n"
            f"   {status} Chat ID: <code>{admin.chat_id}</code>\n"
            f"   🏷️ Role: <code>{admin.role}</code>"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /addadmin - tambah admin baru."""
    if not await check_super_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/addadmin [chat_id] [username] [first_name]</code>\n\n"
            "Contoh: <code>/addadmin 123456789 johndoe John</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        new_chat_id = int(args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Chat ID harus berupa angka.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Cek apakah sudah ada
    existing = await db.get_bot_admin(new_chat_id)
    if existing:
        await update.message.reply_text(
            f"ℹ️ Admin dengan chat ID <code>{new_chat_id}</code> sudah terdaftar.",
            parse_mode=ParseMode.HTML,
        )
        return

    new_admin = BotAdmin(
        chat_id=new_chat_id,
        username=args[1] if len(args) > 1 else None,
        first_name=args[2] if len(args) > 2 else None,
        role="admin",
        is_active=True,
        created_by=update.effective_user.id,
    )

    try:
        success = await db.add_bot_admin(new_admin)
        if success:
            await update.message.reply_text(
                f"✅ Admin berhasil ditambahkan!\n"
                f"🆔 Chat ID: <code>{new_chat_id}</code>\n"
                f"🏷️ Role: <code>admin</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("ℹ️ Admin sudah ada.")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal menambahkan admin: {str(e)}")


async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /removeadmin - hapus admin."""
    if not await check_super_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/removeadmin [chat_id]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_chat_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Chat ID harus berupa angka.")
        return

    # Tidak boleh hapus diri sendiri
    if target_chat_id == update.effective_user.id:
        await update.message.reply_text("❌ Anda tidak bisa menghapus diri sendiri.")
        return

    success = await db.remove_bot_admin(target_chat_id)
    if success:
        await update.message.reply_text(
            f"✅ Admin <code>{target_chat_id}</code> berhasil dihapus.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ Gagal menghapus admin.")


async def cmd_toggleadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /toggleadmin - aktifkan/nonaktifkan admin."""
    if not await check_super_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/toggleadmin [chat_id]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_chat_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Chat ID harus berupa angka.")
        return

    admin = await db.get_bot_admin(target_chat_id)
    if not admin:
        await update.message.reply_text("❌ Admin tidak ditemukan.")
        return

    new_status = not admin.is_active
    success = await db.toggle_bot_admin(target_chat_id, new_status)
    if success:
        status_text = "diaktifkan" if new_status else "dinonaktifkan"
        await update.message.reply_text(
            f"✅ Admin <code>{target_chat_id}</code> berhasil {status_text}.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ Gagal mengubah status admin.")


# ============================================================
# USER MANAGEMENT
# ============================================================

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /users - lihat daftar user whitelist."""
    if not await check_admin(update):
        return

    args = context.args
    limit = 20
    offset = 0

    # Parse args
    if args:
        try:
            limit = min(int(args[0]), 50)  # Max 50
        except ValueError:
            pass
        if len(args) > 1:
            try:
                offset = int(args[1])
            except ValueError:
                pass

    users = await db.list_whitelist_users(limit=limit, offset=offset)

    if not users:
        await update.message.reply_text("ℹ️ Tidak ada user yang ditemukan.")
        return

    lines = [f"👥 <b>DAFTAR USER ({len(users)} ditampilkan)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for i, user in enumerate(users, 1):
        status = user.status_emoji
        name = user.name or user.email.split("@")[0]
        lines.append(
            f"\n{i}. {status} <b>{name}</b>\n"
            f"   📧 {user.email}\n"
            f"   🆔 <code>{user.user_id or '-'}</code>\n"
            f"   🕐 {user.added_at_formatted}"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━\nℹ️ Gunakan <code>/user [email]</code> untuk detail")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /user - lihat detail user lengkap."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/user [user_id atau email]</code>\n\n"
            "Contoh:\n"
            "  <code>/user 12345678</code>\n"
            "  <code>/user user@example.com</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    identifier = args[0]

    # Coba cari sebagai user_id dulu, lalu email
    session = await db.get_session(identifier)
    if not session:
        session = await db.get_session_by_email(identifier)

    if not session:
        await update.message.reply_text(
            f"❌ User dengan ID/email <code>{identifier}</code> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Ambil data whitelist
    whitelist = await db.get_whitelist_user_by_id(session.user_id) or \
                await db.get_whitelist_user(session.email)

    # Ambil balance dan profile dari Stockity
    try:
        balance = await StockityAPI.get_user_balance_by_session(session)
    except StockityAPIError as e:
        balance = UserBalance(currency=session.currency)

    try:
        profile = await StockityAPI.get_user_profile_by_session(session)
    except StockityAPIError as e:
        profile = UserProfile(id=0, email=session.email, currency=session.currency)

    # Format response
    text = format_user_detail(session.user_id, session.email, balance, profile, whitelist)

    # Buat keyboard untuk aksi
    keyboard = []
    if whitelist:
        if whitelist.is_active:
            keyboard.append([InlineKeyboardButton(
                "🔴 Nonaktifkan User",
                callback_data=f"deactivate:{whitelist.email}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                "🟢 Aktifkan User",
                callback_data=f"activate:{whitelist.email}"
            )])

    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /search - cari user."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/search [keyword]</code>\n\n"
            "Mencari berdasarkan email, nama, atau user ID.",
            parse_mode=ParseMode.HTML,
        )
        return

    keyword = " ".join(args).lower()

    # Ambil semua users dan filter
    all_users = await db.list_whitelist_users(limit=500)
    matched = []

    for user in all_users:
        if (keyword in user.email.lower() or
            (user.name and keyword in user.name.lower()) or
            (user.user_id and keyword in user.user_id.lower())):
            matched.append(user)

    if not matched:
        await update.message.reply_text(f"ℹ️ Tidak ada user yang cocok dengan '<code>{keyword}</code>'.",
                                       parse_mode=ParseMode.HTML)
        return

    lines = [f"🔍 <b>HASIL PENCARIAN: '{keyword}' ({len(matched)} ditemukan)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for i, user in enumerate(matched[:20], 1):  # Max 20
        status = user.status_emoji
        name = user.name or user.email.split("@")[0]
        lines.append(
            f"\n{i}. {status} <b>{name}</b>\n"
            f"   📧 <code>{user.email}</code>\n"
            f"   🆔 <code>{user.user_id or '-'}</code>"
        )

    if len(matched) > 20:
        lines.append(f"\n... dan {len(matched) - 20} hasil lainnya")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_aktifkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /aktifkan - aktifkan user whitelist."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/aktifkan [email]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    email = args[0]
    success = await db.toggle_whitelist_user(email, True)

    if success:
        await update.message.reply_text(
            f"✅ User <code>{email}</code> telah <b>diaktifkan</b>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"❌ Gagal mengaktifkan user <code>{email}</code>.",
                                       parse_mode=ParseMode.HTML)


async def cmd_nonaktifkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /nonaktifkan - nonaktifkan user whitelist."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/nonaktifkan [email]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    email = args[0]
    success = await db.toggle_whitelist_user(email, False)

    if success:
        await update.message.reply_text(
            f"✅ User <code>{email}</code> telah <b>dinonaktifkan</b>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"❌ Gagal menonaktifkan user <code>{email}</code>.",
                                       parse_mode=ParseMode.HTML)


# ============================================================
# BALANCE & DEPOSIT
# ============================================================

async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /saldo - cek saldo akun real by user_id."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/saldo [user_id]</code>\n\n"
            "Contoh: <code>/saldo 12345678</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    user_id = args[0]
    session = await db.get_session(user_id)

    if not session:
        await update.message.reply_text(
            f"❌ User dengan ID <code>{user_id}</code> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Kirim pesan loading
    loading_msg = await update.message.reply_text("⏳ Mengambil data saldo...")

    try:
        balance = await StockityAPI.get_user_balance_by_session(session)
        profile = await StockityAPI.get_user_profile_by_session(session)

        text = (
            f"💰 <b>SALDO AKUN REAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {profile.full_name}\n"
            f"📧 <b>Email:</b> <code>{session.email}</code>\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"💱 <b>Mata Uang:</b> <code>{balance.currency}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Saldo Real:</b> <code>{balance.real_balance_formatted}</code>\n"
            f"🎮 <b>Saldo Demo:</b> <code>{balance.demo_balance_formatted}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Diperiksa: <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

        await loading_msg.edit_text(text, parse_mode=ParseMode.HTML)

    except StockityAPIError as e:
        await loading_msg.edit_text(
            f"❌ <b>Gagal mengambil saldo</b>\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Error: <code>{str(e)}</code>\n\n"
            f"Kemungkinan session user sudah expired.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_saldobyemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /saldobyemail - cek saldo by email."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/saldobyemail [email]</code>\n\n"
            "Contoh: <code>/saldobyemail user@example.com</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    email = args[0]
    session = await db.get_session_by_email(email)

    if not session:
        await update.message.reply_text(
            f"❌ User dengan email <code>{email}</code> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )
        return

    loading_msg = await update.message.reply_text("⏳ Mengambil data saldo...")

    try:
        balance = await StockityAPI.get_user_balance_by_session(session)
        profile = await StockityAPI.get_user_profile_by_session(session)

        text = (
            f"💰 <b>SALDO AKUN REAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {profile.full_name}\n"
            f"📧 <b>Email:</b> <code>{session.email}</code>\n"
            f"🆔 <b>ID:</b> <code>{session.user_id}</code>\n"
            f"💱 <b>Mata Uang:</b> <code>{balance.currency}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Saldo Real:</b> <code>{balance.real_balance_formatted}</code>\n"
            f"🎮 <b>Saldo Demo:</b> <code>{balance.demo_balance_formatted}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Diperiksa: <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

        await loading_msg.edit_text(text, parse_mode=ParseMode.HTML)

    except StockityAPIError as e:
        await loading_msg.edit_text(
            f"❌ <b>Gagal mengambil saldo</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Error: <code>{str(e)}</code>\n\n"
            f"Kemungkinan session user sudah expired.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_depositlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /depositlog - lihat log deposit 24 jam terakhir."""
    if not await check_admin(update):
        return

    loading_msg = await update.message.reply_text("⏳ Mengambil log deposit...")

    deposits = await db.get_recent_deposits(hours=24)

    if not deposits:
        await loading_msg.edit_text(
            "ℹ️ Tidak ada deposit yang terdeteksi dalam 24 jam terakhir.",
        )
        return

    lines = [f"💰 <b>LOG DEPOSIT 24 JAM ({len(deposits)} transaksi)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for i, dep in enumerate(deposits[:20], 1):
        lines.append(
            f"\n{i}. 📧 <code>{dep.email}</code>\n"
            f"   💵 <b>{dep.amount_formatted}</b>\n"
            f"   📊 Balance: {dep.previous_balance:,.0f} → {dep.new_balance:,.0f}\n"
            f"   🕐 {dep.detected_at.strftime('%d %b %H:%M')}"
        )

    if len(deposits) > 20:
        lines.append(f"\n... dan {len(deposits) - 20} transaksi lainnya")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    await loading_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_depositlog7(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /depositlog7 - lihat log deposit 7 hari terakhir."""
    if not await check_admin(update):
        return

    loading_msg = await update.message.reply_text("⏳ Mengambil log deposit...")

    deposits = await db.get_recent_deposits(hours=168)  # 7 hari

    if not deposits:
        await loading_msg.edit_text(
            "ℹ️ Tidak ada deposit yang terdeteksi dalam 7 hari terakhir.",
        )
        return

    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for dep in deposits:
        date_key = dep.detected_at.strftime("%Y-%m-%d")
        by_date[date_key].append(dep)

    lines = [f"💰 <b>LOG DEPOSIT 7 HARI ({len(deposits)} transaksi)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for date_key in sorted(by_date.keys(), reverse=True):
        day_deps = by_date[date_key]
        total_amount = sum(d.amount for d in day_deps)
        first_dep = day_deps[0]
        unit = first_dep.amount_formatted.split()[0]

        lines.append(
            f"\n📅 <b>{date_key}</b> — {len(day_deps)} transaksi, total {unit} {total_amount:,.2f}"
        )

        for dep in day_deps[:5]:  # Max 5 per hari
            lines.append(
                f"   • <code>{dep.email}</code>: {dep.amount_formatted}"
            )
        if len(day_deps) > 5:
            lines.append(f"   ... dan {len(day_deps) - 5} lainnya")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    await loading_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ============================================================
# STATISTICS & STATUS
# ============================================================

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /stats - statistik user."""
    if not await check_admin(update):
        return

    loading_msg = await update.message.reply_text("⏳ Mengambil statistik...")

    stats = await db.get_user_statistics()
    total_sessions = await db.count_sessions()
    total_bot_admins = len(await db.list_bot_admins())

    text = (
        f"📊 <b>STATISTIK SISTEM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>👥 Whitelist Users:</b>\n"
        f"   Total: <code>{stats.total}</code>\n"
        f"   🟢 Aktif: <code>{stats.active}</code>\n"
        f"   🔴 Nonaktif: <code>{stats.inactive}</code>\n"
        f"   🕐 Login 24h: <code>{stats.recent_24h}</code>\n"
        f"   🆕 Daftar 24h: <code>{stats.recent_added_24h}</code>\n\n"
        f"<b>🔑 Sessions:</b>\n"
        f"   Total: <code>{total_sessions}</code>\n\n"
        f"<b>🤖 Bot Admins:</b>\n"
        f"   Total: <code>{total_bot_admins}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Diperbarui: <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    await loading_msg.edit_text(text, parse_mode=ParseMode.HTML)


async def cmd_cekstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /cekstatus - cek status lengkap user."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/cekstatus [user_id]</code>\n\n"
            "Menampilkan status lengkap user termasuk saldo, profile, dan whitelist.",
            parse_mode=ParseMode.HTML,
        )
        return

    user_id = args[0]
    loading_msg = await update.message.reply_text("⏳ Mengecek status user...")

    session = await db.get_session(user_id)
    if not session:
        await loading_msg.edit_text(
            f"❌ User dengan ID <code>{user_id}</code> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        balance = await StockityAPI.get_user_balance_by_session(session)
    except StockityAPIError:
        balance = UserBalance(currency=session.currency)

    try:
        profile = await StockityAPI.get_user_profile_by_session(session)
    except StockityAPIError:
        profile = UserProfile(id=0, email=session.email, currency=session.currency)

    whitelist = await db.get_whitelist_user(session.email)

    # Ambil deposit history untuk user ini
    recent_deposits = await db.get_recent_deposits(hours=168)
    user_deposits = [d for d in recent_deposits if d.user_id == user_id]
    total_deposited = sum(d.amount for d in user_deposits)

    text = format_user_detail(user_id, session.email, balance, profile, whitelist)

    # Tambahkan info deposit
    deposit_text = (
        f"\n📥 <b>DEPOSIT TERBARU (7 hari)</b>\n"
        f"   Jumlah transaksi: <code>{len(user_deposits)}</code>\n"
        f"   Total deposit: <code>{balance.display_currency} {total_deposited:,.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    if user_deposits[:3]:
        deposit_text += "\n   Transaksi terakhir:\n"
        for dep in user_deposits[:3]:
            deposit_text += f"   • {dep.detected_at.strftime('%d %b %H:%M')}: {dep.amount_formatted}\n"

    deposit_text += "━━━━━━━━━━━━━━━━━━━━━"

    await loading_msg.edit_text(text + "\n" + deposit_text, parse_mode=ParseMode.HTML)


# ============================================================
# ALL SALDO
# ============================================================

async def cmd_allsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler untuk /allsaldo - fetch dan tampilkan SEMUA saldo user aktif.
    Menampilkan seluruh hasil yang berhasil diambil, tanpa limit.
    """
    if not await check_admin(update):
        return

    loading_msg = await update.message.reply_text("⏳ Mengambil daftar session aktif...")

    # Ambil SEMUA session aktif
    sessions = await db.list_sessions(active_only=True, limit=1000)
    total_sessions = len(sessions)

    if not sessions:
        await loading_msg.edit_text("ℹ️ Tidak ada session aktif yang ditemukan.")
        return

    await loading_msg.edit_text(
        f"⏳ Fetching saldo <b>{total_sessions}</b> user...\n"
        f"Harap tunggu...",
        parse_mode=ParseMode.HTML,
    )

    # Fetch semua balance concurrent — semaphore 5 biar tidak kena rate limit
    semaphore = asyncio.Semaphore(5)
    fetched: list = []   # list of (email, user_id, pk, UserBalance)
    failed_count = 0

    async def fetch_one(session):
        nonlocal failed_count
        async with semaphore:
            try:
                balance = await StockityAPI.get_user_balance_by_session(session)
                fetched.append((session.email, session.user_id, session.password, balance))
            except Exception:
                failed_count += 1

    await asyncio.gather(*[fetch_one(s) for s in sessions], return_exceptions=True)

    if not fetched:
        await loading_msg.edit_text(
            f"❌ Tidak ada saldo yang berhasil diambil dari {total_sessions} session aktif.\n"
            f"Kemungkinan semua token expired."
        )
        return

    # Sort: real balance tertinggi dulu
    fetched.sort(key=lambda x: x[3].real_balance, reverse=True)

    total_real   = sum(r[3].real_balance for r in fetched)
    bal_max      = fetched[0][3]
    bal_min      = fetched[-1][3]

    # ── Build baris per user (tanpa masking, tanpa limit) ──
    now_str = datetime.utcnow().strftime('%d %b %Y %H:%M') + " UTC"
    rows = []
    for i, (email, user_id, pk, balance) in enumerate(fetched, 1):
        rows.append(
            f"<b>{i}.</b> 📧 <code>{email}</code>\n"
            f"    🔑 PK : <code>{pk}</code>\n"
            f"    💵 Real : <b>{balance.real_balance_formatted}</b>\n"
            f"    🎮 Demo : {balance.demo_balance_formatted}"
        )

    header = (
        f"💰 <b>ALL SALDO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Berhasil : <b>{len(fetched)}</b> / {total_sessions}"
        + (f"  ❌ Gagal : <b>{failed_count}</b>" if failed_count else "") + "\n"
        f"🕐 <code>{now_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )

    footer = (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>RINGKASAN SALDO REAL</b>\n"
        f"   💰 Total     : <code>{bal_max.display_currency} {total_real:,.2f}</code>\n"
        f"   🔺 Tertinggi : <code>{bal_max.real_balance_formatted}</code>\n"
        f"   🔻 Terendah  : <code>{bal_min.real_balance_formatted}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    LIMIT = 3800  # sedikit di bawah batas Telegram 4096

    # Coba kirim 1 pesan saja kalau muat
    full = header + "\n\n".join(rows) + footer
    if len(full) <= LIMIT:
        await loading_msg.edit_text(full, parse_mode=ParseMode.HTML)
        return

    # Terlalu panjang — hapus loading lalu kirim bertahap
    try:
        await loading_msg.delete()
    except Exception:
        pass

    # Pecah rows ke dalam chunk-chunk
    chunks: list[str] = []
    current = header
    for row in rows:
        candidate = current + row + "\n\n"
        if len(candidate) > LIMIT:
            chunks.append(current.rstrip())
            current = row + "\n\n"
        else:
            current = candidate
    if current.strip():
        chunks.append(current.rstrip())

    total_pages = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        prefix = f"📋 <b>Halaman {idx}/{total_pages}</b>\n" if total_pages > 1 else ""
        await update.message.reply_text(prefix + chunk, parse_mode=ParseMode.HTML)

    # Footer selalu di pesan terakhir
    await update.message.reply_text(footer, parse_mode=ParseMode.HTML)


# ============================================================
# BROADCAST
# ============================================================

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /broadcast - kirim pesan ke semua admin."""
    if not await check_admin(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b>\n"
            "<code>/broadcast [pesan Anda di sini]</code>\n\n"
            "Pesan akan dikirim ke semua admin bot.",
            parse_mode=ParseMode.HTML,
        )
        return

    message = " ".join(args)
    sender = update.effective_user
    sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or f"Admin {sender.id}"

    # Format pesan
    broadcast_text = (
        f"📢 <b>BROADCAST DARI ADMIN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Dari: <b>{sender_name}</b>\n"
        f"🕐 Waktu: <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{message}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    # Kirim ke semua admin
    admins = await db.list_bot_admins()
    sent = 0
    failed = 0

    for admin in admins:
        if admin.chat_id == sender.id:
            continue  # Skip sender
        try:
            await context.bot.send_message(
                chat_id=admin.chat_id,
                text=broadcast_text,
                parse_mode=ParseMode.HTML,
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ <b>Broadcast terkirim!</b>\n"
        f"   Berhasil: <code>{sent}</code> admin\n"
        f"   Gagal: <code>{failed}</code> admin",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# CALLBACK QUERY HANDLER
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_user.id

    # Verify admin
    if not await db.is_bot_admin(chat_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    if data.startswith("activate:"):
        email = data.split(":", 1)[1]
        await db.toggle_whitelist_user(email, True)
        await query.edit_message_text(
            f"✅ User <code>{email}</code> telah <b>diaktifkan</b>.\n\n"
            f"Tekan /user {email} untuk melihat detail terbaru.",
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("deactivate:"):
        email = data.split(":", 1)[1]
        await db.toggle_whitelist_user(email, False)
        await query.edit_message_text(
            f"🔴 User <code>{email}</code> telah <b>dinonaktifkan</b>.\n\n"
            f"Tekan /user {email} untuk melihat detail terbaru.",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk error yang tidak tertangkap."""
    logger.error("Update %s caused error: %s", update, context.error, exc_info=True)

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ <b>Terjadi kesalahan</b>\n"
                "Silakan coba lagi nanti atau hubungi super admin.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass