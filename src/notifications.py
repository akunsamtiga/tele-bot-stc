"""
Notification System
- Real-time listeners via Supabase Realtime
- Deposit detection via balance polling
- Notification dispatcher ke Telegram
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Callable, Coroutine

from telegram import Bot
from telegram.constants import ParseMode

from config import (
    NOTIFICATION_CHANNEL_ID, DEPOSIT_CHECK_INTERVAL,
    MIN_DEPOSIT_AMOUNT, logger
)
from database import db
from stockity_api import StockityAPI, StockityAPIError
from models import DepositEvent, NotificationEvent, UserBalance


class NotificationService:
    """Service untuk mengelola semua notifikasi bot."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._deposit_callbacks: List[Callable[[DepositEvent], Coroutine]] = []
        self._user_callbacks: List[Callable[[NotificationEvent], Coroutine]] = []

    # ============================================================
    # CALLBACK REGISTRATION
    # ============================================================

    def on_deposit(self, callback: Callable[[DepositEvent], Coroutine]):
        """Register callback untuk event deposit."""
        self._deposit_callbacks.append(callback)

    def on_new_user(self, callback: Callable[[NotificationEvent], Coroutine]):
        """Register callback untuk event user baru."""
        self._user_callbacks.append(callback)

    # ============================================================
    # LIFECYCLE
    # ============================================================

    async def start(self):
        """Mulai semua notification services."""
        self._running = True
        logger.info("Starting NotificationService...")

        # Task 1: Deposit detection (polling)
        task_deposit = asyncio.create_task(
            self._deposit_detection_loop(),
            name="deposit_detection"
        )
        self._tasks.append(task_deposit)

        # Task 2: Realtime subscription untuk whitelist_users
        task_whitelist = asyncio.create_task(
            self._whitelist_realtime_loop(),
            name="whitelist_realtime"
        )
        self._tasks.append(task_whitelist)

        logger.info("NotificationService started with %d tasks", len(self._tasks))

    async def stop(self):
        """Hentikan semua notification services."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("NotificationService stopped")

    # ============================================================
    # DEPOSIT DETECTION (Polling)
    # ============================================================

    async def _deposit_detection_loop(self):
        """
        Loop untuk mendeteksi deposit dengan membandingkan balance.
        Interval: DEPOSIT_CHECK_INTERVAL detik (default 5 menit).
        """
        logger.info(
            "Deposit detection loop started (interval=%ds, min_amount=%s)",
            DEPOSIT_CHECK_INTERVAL, MIN_DEPOSIT_AMOUNT
        )

        # Tunggu sebentar saat startup
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._check_all_balances()
            except Exception as e:
                logger.error("Error in deposit detection loop: %s", e)

            # Sleep dengan cancellable interval
            for _ in range(DEPOSIT_CHECK_INTERVAL):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _check_all_balances(self):
        """Cek balance semua user aktif dan deteksi perubahan (deposit)."""
        sessions = await db.list_sessions(active_only=True, limit=500)
        logger.debug("Checking balances for %d active sessions", len(sessions))

        for session in sessions:
            try:
                await self._check_single_balance(session)
            except Exception as e:
                logger.warning(
                    "Failed to check balance for %s: %s",
                    session.user_id, e
                )
            # Small delay antara user untuk tidak overload
            await asyncio.sleep(0.5)

    async def _check_single_balance(self, session):
        """Cek balance single user dan deteksi deposit."""
        # Ambil balance terakhir dari database
        last_balance_record = await db.get_last_balance(session.user_id)

        # Ambil balance terkini dari Stockity API
        try:
            current_balance = await StockityAPI.get_user_balance_by_session(session)
        except StockityAPIError:
            # Session mungkin expired, skip
            return

        # Jika belum ada record sebelumnya, simpan sebagai baseline
        if not last_balance_record:
            await db.save_balance_snapshot(
                user_id=session.user_id,
                email=session.email,
                real_balance=current_balance.real_balance,
                demo_balance=current_balance.demo_balance,
                currency=current_balance.currency,
            )
            return

        # Hitung perubahan balance real
        previous_real = float(last_balance_record.get("real_balance", 0))
        current_real = current_balance.real_balance
        diff = current_real - previous_real

        # Simpan snapshot terbaru
        await db.save_balance_snapshot(
            user_id=session.user_id,
            email=session.email,
            real_balance=current_balance.real_balance,
            demo_balance=current_balance.demo_balance,
            currency=current_balance.currency,
        )

        # Deteksi deposit: balance naik lebih dari threshold
        if diff >= MIN_DEPOSIT_AMOUNT:
            event = DepositEvent(
                user_id=session.user_id,
                email=session.email,
                amount=diff,
                currency=current_balance.currency,
                previous_balance=previous_real,
                new_balance=current_real,
                detected_at=datetime.utcnow(),
            )

            # Simpan ke database
            await db.save_deposit_event(event)

            # Trigger callbacks
            for callback in self._deposit_callbacks:
                try:
                    await callback(event)
                except Exception as e:
                    logger.error("Deposit callback error: %s", e)

    # ============================================================
    # REALTIME: WHITELIST USERS
    # ============================================================

    async def _whitelist_realtime_loop(self):
        """
        Loop untuk listen perubahan pada tabel whitelist_users.
        Menggunakan polling karena Supabase Realtime Python support terbatas.
        """
        logger.info("Whitelist realtime loop started")

        # Track last known users untuk deteksi baru
        self._known_whitelist_ids: set = set()

        # Initial load
        initial_users = await db.list_whitelist_users(limit=1000)
        self._known_whitelist_ids = {u.id for u in initial_users if u.id}

        logger.info("Initial whitelist: %d users tracked", len(self._known_whitelist_ids))

        # Polling interval: 30 detik
        poll_interval = 30

        while self._running:
            try:
                await self._poll_whitelist_changes()
            except Exception as e:
                logger.error("Error in whitelist realtime loop: %s", e)

            for _ in range(poll_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _poll_whitelist_changes(self):
        """Poll whitelist users untuk deteksi user baru."""
        # Ambil user yang ditambahkan dalam 1 jam terakhir
        recent_users = await db.list_whitelist_users(limit=100)
        current_ids = {u.id for u in recent_users if u.id}

        # Deteksi user baru (ada di current tapi tidak di known)
        new_ids = current_ids - self._known_whitelist_ids

        for user in recent_users:
            if user.id in new_ids:
                # User baru terdeteksi!
                added_by = user.added_by or "system"
                is_self_register = added_by == "system"

                event = NotificationEvent(
                    event_type="new_user",
                    title="User Baru Terdaftar",
                    message=(
                        f"{'User baru telah mendaftar sendiri'
                         if is_self_register else
                         f'User baru ditambahkan oleh admin {added_by}'}"
                    ),
                    user_id=user.user_id,
                    email=user.email,
                    metadata={
                        "name": user.name,
                        "added_by": added_by,
                        "is_self_register": is_self_register,
                        "added_at": user.added_at,
                    },
                )

                # Trigger callbacks
                for callback in self._user_callbacks:
                    try:
                        await callback(event)
                    except Exception as e:
                        logger.error("New user callback error: %s", e)

        # Update known set
        self._known_whitelist_ids = current_ids

    # ============================================================
    # DIRECT NOTIFICATIONS
    # ============================================================

    async def send_to_admins(self, message: str, parse_mode=ParseMode.HTML):
        """Kirim pesan ke semua admin bot."""
        admins = await db.list_bot_admins()
        for admin in admins:
            if admin.is_active:
                try:
                    await self.bot.send_message(
                        chat_id=admin.chat_id,
                        text=message,
                        parse_mode=parse_mode,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to send to admin %d: %s", admin.chat_id, e
                    )

    async def send_to_channel(self, message: str, parse_mode=ParseMode.HTML):
        """Kirim pesan ke notification channel jika dikonfigurasi."""
        if NOTIFICATION_CHANNEL_ID:
            try:
                await self.bot.send_message(
                    chat_id=NOTIFICATION_CHANNEL_ID,
                    text=message,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.warning("Failed to send to channel: %s", e)

    async def send_deposit_notification(self, event: DepositEvent):
        """Kirim notifikasi deposit ke semua admin."""
        message = (
            f"💰 <b>DEPOSIT TERDETEKSI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> <code>{event.email}</code>\n"
            f"🆔 <b>ID:</b> <code>{event.user_id}</code>\n"
            f"💵 <b>Jumlah:</b> <code>{event.amount_formatted}</code>\n"
            f"📊 <b>Balance Sebelum:</b> <code>{event.previous_balance:,.2f}</code>\n"
            f"📊 <b>Balance Sesudah:</b> <code>{event.new_balance:,.2f}</code>\n"
            f"🕐 <b>Waktu:</b> {event.detected_at.strftime('%d %b %Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        await self.send_to_admins(message)
        await self.send_to_channel(message)

    async def send_new_user_notification(self, event: NotificationEvent):
        """Kirim notifikasi user baru ke semua admin."""
        metadata = event.metadata or {}
        is_self = metadata.get("is_self_register", True)
        added_by = metadata.get("added_by", "system")

        message = (
            f"🆕 <b>USER BARU {'TERDAFTAR' if is_self else 'DITAMBAHKAN'}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 <b>Email:</b> <code>{event.email or '-'}</code>\n"
            f"🆔 <b>User ID:</b> <code>{event.user_id or '-'}</code>\n"
            f"👤 <b>Nama:</b> {metadata.get('name') or '-'}\n"
            f"🏷️ <b>Sumber:</b> {'Registrasi mandiri' if is_self else f'Ditambahkan oleh {added_by}'}\n"
            f"🕐 <b>Waktu:</b> {event.created_at.strftime('%d %b %Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        await self.send_to_admins(message)
        await self.send_to_channel(message)

    async def send_login_notification(self, user_id: str, email: str):
        """Kirim notifikasi user login."""
        message = (
            f"🔔 <b>USER LOGIN</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User <code>{email}</code> baru saja login\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🕐 Waktu: {datetime.utcnow().strftime('%d %b %Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        await self.send_to_admins(message)


# Singleton akan diinisialisasi di main.py setelah bot dibuat
notification_service: Optional[NotificationService] = None
