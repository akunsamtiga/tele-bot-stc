"""
Command Handlers untuk Bot Telegram Admin.
Semua perintah bot didefinisikan di sini.
Mode: PUBLIC — semua user Telegram bisa akses tanpa registrasi admin.
"""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import logger, SUPER_ADMIN_CHAT_IDS
from database import db
from stockity_api import StockityAPI, StockityAPIError
from models import UserBalance, UserProfile, BotAdmin, ISO_TO_UNIT

# ============================================================
# HELPERS (dipertahankan, tidak dipakai sebagai guard)
# ============================================================

async def check_admin(update: Update) -> bool:
    """Cek apakah user adalah admin bot (tidak dipakai sebagai guard di mode publik)."""
    chat_id = update.effective_user.id
    return await db.is_bot_admin(chat_id)


async def check_super_admin(update: Update) -> bool:
    """Cek apakah user adalah super admin (tidak dipakai sebagai guard di mode publik)."""
    chat_id = update.effective_user.id
    return await db.is_super_admin(chat_id)


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
    """Handler untuk /start — menyambut semua user."""
    user = update.effective_user
    name = user.first_name or "pengguna"

    await update.message.reply_text(
        f"👋 <b>Selamat datang, {name}!</b>\n\n"
        f"🤖 Ini adalah <b>Stockity Admin Bot</b> — bot monitoring dan manajemen"
        f" sistem trading.\n\n"
        f"📖 Gunakan /help untuk melihat daftar perintah yang tersedia.\n"
        f"🆔 Chat ID kamu: <code>{user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /help — daftar semua perintah."""
    text = (
        f"📖 <b>DAFTAR PERINTAH BOT ADMIN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>🧑‍💼 Manajemen Admin:</b>\n"
        f"  /admins — Lihat daftar admin bot\n"
        f"  /addadmin [chat_id] — Tambah admin baru\n"
        f"  /removeadmin [chat_id] — Hapus admin\n"
        f"  /toggleadmin [chat_id] — Aktifkan/nonaktifkan admin\n"
        f"\n<b>👥 Manajemen User:</b>\n"
        f"  /users — Lihat daftar user (whitelist)\n"
        f"  /user [id/email] — Detail user lengkap\n"
        f"  /search [keyword] — Cari user\n"
        f"  /aktifkan [email] — Aktifkan user\n"
        f"  /nonaktifkan [email] — Nonaktifkan user\n"
        f"\n<b>💰 Saldo & Deposit:</b>\n"
        f"  /saldo [user_id] — Cek saldo akun real by ID\n"
        f"  /saldobyemail [email] — Cek saldo by email\n"
        f"  /allsaldo — Statistik saldo real SEMUA user\n"
        f"  /depositlog — Log deposit 24 jam terakhir\n"
        f"  /depositlog7 — Log deposit 7 hari terakhir\n"
        f"  /statsdeposit — Statistik deposit semua user\n"
        f"\n<b>📊 Statistik:</b>\n"
        f"  /stats — Statistik user\n"
        f"  /cekstatus [user_id] — Cek status lengkap user\n"
        f"\n<b>📢 Komunikasi:</b>\n"
        f"  /broadcast [pesan] — Kirim pesan ke semua admin\n"
        f"\n<b>⚙️ Utilitas:</b>\n"
        f"  /myid — Lihat chat ID kamu\n"
        f"  /ping — Cek status bot\n"
        f"  /help — Tampilkan bantuan ini\n"
        f"\n━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /ping — cek status bot."""
    start = datetime.utcnow()
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
    """Handler untuk /myid — lihat chat ID sendiri."""
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
    """Handler untuk /admins — lihat daftar admin bot."""
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
    """Handler untuk /addadmin — tambah admin baru."""
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
        await update.message.reply_text("❌ Chat ID harus berupa angka.", parse_mode=ParseMode.HTML)
        return

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
    """Handler untuk /removeadmin — hapus admin."""
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
    """Handler untuk /toggleadmin — aktifkan/nonaktifkan admin."""
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
    """Handler untuk /users — lihat daftar user whitelist."""
    args = context.args
    limit = 20
    offset = 0

    if args:
        try:
            limit = min(int(args[0]), 50)
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
    """Handler untuk /user — lihat detail user lengkap."""
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

    session = await db.get_session(identifier)
    if not session:
        session = await db.get_session_by_email(identifier)

    if not session:
        await update.message.reply_text(
            f"❌ User dengan ID/email <code>{identifier}</code> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )
        return

    whitelist = await db.get_whitelist_user_by_id(session.user_id) or \
                await db.get_whitelist_user(session.email)

    try:
        balance = await StockityAPI.get_user_balance_by_session(session)
    except StockityAPIError:
        balance = UserBalance(currency=session.currency)

    try:
        profile = await StockityAPI.get_user_profile_by_session(session)
    except StockityAPIError:
        profile = UserProfile(id=0, email=session.email, currency=session.currency)

    text = format_user_detail(session.user_id, session.email, balance, profile, whitelist)

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
    """Handler untuk /search — cari user."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ <b>Penggunaan:</b> <code>/search [keyword]</code>\n\n"
            "Mencari berdasarkan email, nama, atau user ID.",
            parse_mode=ParseMode.HTML,
        )
        return

    keyword = " ".join(args).lower()

    all_users = await db.list_whitelist_users(limit=500)
    matched = [
        user for user in all_users
        if (keyword in user.email.lower() or
            (user.name and keyword in user.name.lower()) or
            (user.user_id and keyword in user.user_id.lower()))
    ]

    if not matched:
        await update.message.reply_text(
            f"ℹ️ Tidak ada user yang cocok dengan '<code>{keyword}</code>'.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"🔍 <b>HASIL PENCARIAN: '{keyword}' ({len(matched)} ditemukan)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for i, user in enumerate(matched[:20], 1):
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
    """Handler untuk /aktifkan — aktifkan user whitelist."""
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
        await update.message.reply_text(
            f"❌ Gagal mengaktifkan user <code>{email}</code>.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_nonaktifkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /nonaktifkan — nonaktifkan user whitelist."""
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
        await update.message.reply_text(
            f"❌ Gagal menonaktifkan user <code>{email}</code>.",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# BALANCE & DEPOSIT
# ============================================================

async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /saldo — cek saldo akun real by user_id."""
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
    """Handler untuk /saldobyemail — cek saldo by email."""
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
    """Handler untuk /depositlog — lihat log deposit 24 jam terakhir."""
    loading_msg = await update.message.reply_text("⏳ Mengambil log deposit...")

    deposits = await db.get_recent_deposits(hours=24)

    if not deposits:
        await loading_msg.edit_text("ℹ️ Tidak ada deposit yang terdeteksi dalam 24 jam terakhir.")
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
    """Handler untuk /depositlog7 — lihat log deposit 7 hari terakhir."""
    loading_msg = await update.message.reply_text("⏳ Mengambil log deposit...")

    deposits = await db.get_recent_deposits(hours=168)

    if not deposits:
        await loading_msg.edit_text("ℹ️ Tidak ada deposit yang terdeteksi dalam 7 hari terakhir.")
        return

    from collections import defaultdict
    by_date = defaultdict(list)
    for dep in deposits:
        by_date[dep.detected_at.strftime("%Y-%m-%d")].append(dep)

    lines = [f"💰 <b>LOG DEPOSIT 7 HARI ({len(deposits)} transaksi)</b>\n━━━━━━━━━━━━━━━━━━━━━"]

    for date_key in sorted(by_date.keys(), reverse=True):
        day_deps = by_date[date_key]
        total_amount = sum(d.amount for d in day_deps)
        first_dep = day_deps[0]
        unit = first_dep.amount_formatted.split()[0]

        lines.append(
            f"\n📅 <b>{date_key}</b> — {len(day_deps)} transaksi, total {unit} {total_amount:,.2f}"
        )

        for dep in day_deps[:5]:
            lines.append(f"   • <code>{dep.email}</code>: {dep.amount_formatted}")
        if len(day_deps) > 5:
            lines.append(f"   ... dan {len(day_deps) - 5} lainnya")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    await loading_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ============================================================
# STATISTICS & STATUS
# ============================================================

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /stats — statistik user."""
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
    """Handler untuk /cekstatus — cek status lengkap user."""
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

    recent_deposits = await db.get_recent_deposits(hours=168)
    user_deposits = [d for d in recent_deposits if d.user_id == user_id]
    total_deposited = sum(d.amount for d in user_deposits)

    text = format_user_detail(user_id, session.email, balance, profile, whitelist)

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
# BROADCAST
# ============================================================

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /broadcast — kirim pesan ke semua admin."""
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
    sender_name = (
        f"{sender.first_name or ''} {sender.last_name or ''}".strip()
        or f"User {sender.id}"
    )

    broadcast_text = (
        f"📢 <b>BROADCAST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Dari: <b>{sender_name}</b>\n"
        f"🆔 Chat ID: <code>{sender.id}</code>\n"
        f"🕐 Waktu: <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{message}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    admins = await db.list_bot_admins()
    sent = 0
    failed = 0

    for admin in admins:
        if admin.chat_id == sender.id:
            continue
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
# ALL SALDO — statistik saldo real semua user
# ============================================================

async def cmd_allsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /allsaldo — Ambil & rangkum saldo akun real seluruh user.

    Alur per user:
      1. Gunakan stockity_token yang tersimpan di session (fast path).
      2. Jika token expired → re-login menggunakan email + PK (password),
         lalu fetch ulang balance dengan token baru.
      3. Jika re-login pun gagal → catat sebagai 'gagal'.

    Proses berjalan concurrent (maks 5 paralel) dengan progress update
    setiap 5 user agar tidak trigger Telegram rate-limit.
    """
    loading_msg = await update.message.reply_text(
        "⏳ <b>Mengambil saldo semua user...</b>\n"
        "Proses ini memakan waktu beberapa menit — harap tunggu.",
        parse_mode=ParseMode.HTML,
    )

    sessions = await db.list_sessions(active_only=True, limit=500)
    if not sessions:
        await loading_msg.edit_text("ℹ️ Tidak ada session aktif yang ditemukan.")
        return

    total = len(sessions)
    results: list[tuple[str, float, str, bool]] = []  # (email, real_bal, currency, ok)

    # Semaphore: maks 5 request concurrent agar tidak overload Stockity
    sem = asyncio.Semaphore(5)

    async def fetch_one(session) -> tuple[str, float, str, bool]:
        """Fetch balance satu user — token lama dulu, lalu re-login jika perlu."""
        async with sem:
            # ── Strategy 1: gunakan token yang tersimpan ─────────────────────
            try:
                bal = await StockityAPI.get_user_balance_by_session(session)
                return (session.email, bal.real_balance, bal.currency, True)
            except StockityAPIError:
                pass

            # ── Strategy 2: re-login dengan email + PK ────────────────────────
            if session.password:
                try:
                    new_token = await StockityAPI.login(
                        session.email, session.password, session.device_id
                    )
                    if new_token:
                        from models import UserSession as _US
                        refreshed = _US(
                            user_id=session.user_id,
                            email=session.email,
                            password=session.password,
                            stockity_token=new_token,
                            device_id=session.device_id,
                            device_type=session.device_type,
                            user_agent=session.user_agent,
                            user_timezone=session.user_timezone,
                            currency=session.currency,
                            currency_iso=session.currency_iso,
                        )
                        bal = await StockityAPI.get_user_balance_by_session(refreshed)
                        return (session.email, bal.real_balance, bal.currency, True)
                except Exception:
                    pass

            return (session.email, 0.0, session.currency, False)

    # Proses berurutan dalam batch kecil supaya ada progress update
    CHUNK = 5
    last_edit = datetime.utcnow()

    for i in range(0, total, CHUNK):
        chunk = sessions[i : i + CHUNK]
        chunk_results = await asyncio.gather(*[fetch_one(s) for s in chunk])
        results.extend(chunk_results)

        done = min(i + CHUNK, total)
        # Update progress kalau belum selesai dan sudah > 5 detik sejak edit terakhir
        elapsed = (datetime.utcnow() - last_edit).total_seconds()
        if done < total and elapsed >= 5:
            try:
                await loading_msg.edit_text(
                    f"⏳ Mengambil saldo... <code>{done}/{total}</code>\n"
                    f"Harap tunggu...",
                    parse_mode=ParseMode.HTML,
                )
                last_edit = datetime.utcnow()
            except Exception:
                pass

    # ── Agregasi hasil ─────────────────────────────────────────────────────────
    ok_results    = [(e, b, c) for e, b, c, ok in results if ok]
    failed_count  = len(results) - len(ok_results)

    # Total per mata uang
    by_currency: dict[str, float] = defaultdict(float)
    for _, bal, curr in ok_results:
        by_currency[curr] += bal

    # Urut: tertinggi dulu
    sorted_results = sorted(ok_results, key=lambda x: x[1], reverse=True)

    # ── Format output ──────────────────────────────────────────────────────────
    def mask(email: str) -> str:
        """Mask email untuk tampilan agregat."""
        if "@" in email:
            local, domain = email.split("@", 1)
            return local[:3] + "***@" + domain
        return email[:5] + "***"

    lines: list[str] = [
        f"💰 <b>STATISTIK SALDO REAL — SEMUA USER</b>",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"👥 Total session aktif : <code>{total}</code>",
        f"✅ Berhasil diambil    : <code>{len(ok_results)}</code>",
        f"❌ Gagal (token/login) : <code>{failed_count}</code>",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"💵 <b>TOTAL SALDO REAL (per mata uang):</b>",
    ]

    if by_currency:
        for curr, total_bal in sorted(by_currency.items(), key=lambda x: x[1], reverse=True):
            unit = ISO_TO_UNIT.get(curr, curr)
            lines.append(f"   {curr}: <code>{unit} {total_bal:,.2f}</code>")
    else:
        lines.append("   (tidak ada data)")

    lines.append(f"\n📊 <b>TOP 10 SALDO TERTINGGI:</b>")
    if sorted_results:
        for rank, (email, bal, curr) in enumerate(sorted_results[:10], 1):
            unit = ISO_TO_UNIT.get(curr, curr)
            lines.append(
                f"   {rank}. <code>{mask(email)}</code>\n"
                f"       💵 <b>{unit} {bal:,.2f}</b> ({curr})"
            )
    else:
        lines.append("   (tidak ada data)")

    # Saldo terendah (non-nol) untuk gambaran
    nonzero = [(e, b, c) for e, b, c in sorted_results if b > 0]
    if len(nonzero) > 3:
        lines.append(f"\n📉 <b>SALDO TERENDAH (berisi):</b>")
        for email, bal, curr in nonzero[-3:]:
            unit = ISO_TO_UNIT.get(curr, curr)
            lines.append(
                f"   • <code>{mask(email)}</code>: {unit} {bal:,.2f}"
            )

    lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    await loading_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ============================================================
# STATS DEPOSIT — statistik deposit agregat semua user
# ============================================================

async def cmd_statsdeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /statsdeposit — Statistik deposit semua user dari deposit_events.

    Menampilkan:
    - Ringkasan per periode (24h / 7d / 30d): jumlah transaksi, user unik, total nilai
    - Top 10 depositor 30 hari terakhir
    - Rata-rata deposit per transaksi
    """
    loading_msg = await update.message.reply_text("⏳ Mengambil statistik deposit...")

    # Ambil data dari tiga periode sekaligus
    deps_24h, deps_7d, deps_30d = await asyncio.gather(
        db.get_recent_deposits(hours=24),
        db.get_recent_deposits(hours=168),
        db.get_recent_deposits(hours=720),
    )

    if not deps_30d:
        await loading_msg.edit_text(
            "ℹ️ Belum ada deposit yang terdeteksi dalam 30 hari terakhir.\n"
            "Pastikan background deposit-detection loop sudah berjalan."
        )
        return

    # ── Helper: aggregate per mata uang ───────────────────────────────────────
    def sum_by_currency(deps) -> dict[str, float]:
        acc: dict[str, float] = defaultdict(float)
        for d in deps:
            acc[d.currency] += d.amount
        return dict(acc)

    def format_currency_block(by_curr: dict[str, float]) -> str:
        if not by_curr:
            return "   —"
        lines = []
        for curr, total in sorted(by_curr.items(), key=lambda x: x[1], reverse=True):
            unit = ISO_TO_UNIT.get(curr, curr)
            lines.append(f"   {curr}: <code>{unit} {total:,.2f}</code>")
        return "\n".join(lines)

    # ── Per-user stats (periode 30 hari) ──────────────────────────────────────
    user_stats: dict[str, dict] = {}
    for dep in deps_30d:
        uid = dep.user_id
        if uid not in user_stats:
            user_stats[uid] = {
                "email": dep.email,
                "count": 0,
                "total": 0.0,
                "currency": dep.currency,
            }
        user_stats[uid]["count"] += 1
        user_stats[uid]["total"] += dep.amount

    unique_30d = len(user_stats)
    unique_7d  = len({d.user_id for d in deps_7d})
    unique_24h = len({d.user_id for d in deps_24h})

    # Top 10 berdasarkan total nilai
    top10 = sorted(user_stats.values(), key=lambda x: x["total"], reverse=True)[:10]

    # Rata-rata per transaksi (30d)
    avg_30d = (sum(d.amount for d in deps_30d) / len(deps_30d)) if deps_30d else 0.0
    # Gunakan currency terbanyak untuk rata-rata
    most_common_curr = max(sum_by_currency(deps_30d), key=sum_by_currency(deps_30d).get) if deps_30d else "IDR"
    avg_unit = ISO_TO_UNIT.get(most_common_curr, most_common_curr)

    def mask(email: str) -> str:
        if "@" in email:
            local, domain = email.split("@", 1)
            return local[:3] + "***@" + domain
        return email[:5] + "***"

    # ── Format output ──────────────────────────────────────────────────────────
    lines: list[str] = [
        f"📊 <b>STATISTIK DEPOSIT — SEMUA USER</b>",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"<b>📅 24 JAM TERAKHIR</b>",
        f"   Transaksi : <code>{len(deps_24h)}</code>  |  User unik: <code>{unique_24h}</code>",
        format_currency_block(sum_by_currency(deps_24h)),
        f"",
        f"<b>📅 7 HARI TERAKHIR</b>",
        f"   Transaksi : <code>{len(deps_7d)}</code>  |  User unik: <code>{unique_7d}</code>",
        format_currency_block(sum_by_currency(deps_7d)),
        f"",
        f"<b>📅 30 HARI TERAKHIR</b>",
        f"   Transaksi : <code>{len(deps_30d)}</code>  |  User unik: <code>{unique_30d}</code>",
        f"   Rata-rata / tx: <code>{avg_unit} {avg_30d:,.2f}</code>",
        format_currency_block(sum_by_currency(deps_30d)),
        f"",
        f"<b>🏆 TOP 10 DEPOSITOR (30 hari):</b>",
    ]

    for rank, u in enumerate(top10, 1):
        unit = ISO_TO_UNIT.get(u["currency"], u["currency"])
        lines.append(
            f"   {rank}. <code>{mask(u['email'])}</code>\n"
            f"       {u['count']} tx | <b>{unit} {u['total']:,.2f}</b>"
        )

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 <code>{datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC</code>",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    await loading_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ============================================================
# CALLBACK QUERY HANDLER
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data

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
                "Silakan coba lagi nanti.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass