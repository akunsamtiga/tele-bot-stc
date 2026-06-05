"""
Stockity API Client
Mirrors fungsionalitas dari backend NestJS (profile.service.ts).
Menggunakan curl binary untuk bypass Cloudflare (sama dengan backend).
"""

import asyncio
import json
import subprocess
from typing import Optional, Dict, Any, List

from config import STOCKITY_API_URL, DEFAULT_USER_AGENT, DEFAULT_TIMEZONE, logger
from models import UserBalance, UserProfile


class StockityAPIError(Exception):
    """Exception khusus untuk error Stockity API."""
    pass


class StockityAPI:
    """Client untuk API Stockity.id"""

    BASE_URL: str = STOCKITY_API_URL.rstrip("/")

    @staticmethod
    def _build_headers(
        auth_token: str,
        device_id: str,
        timezone: str = DEFAULT_TIMEZONE,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Build headers sama seperti backend NestJS."""
        headers = {
            "device-id": device_id,
            "device-type": "web",
            "user-timezone": timezone,
            "authorization-token": auth_token,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://stockity.id",
            "Referer": "https://stockity.id/",
        }
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    async def _curl_get(
        url: str, headers: Dict[str, str], timeout: int = 15
    ) -> Dict[str, Any]:
        """HTTP GET menggunakan curl binary (bypass Cloudflare)."""
        header_args = []
        for k, v in headers.items():
            header_args.extend(["-H", f"{k}: {v}"])

        cmd = [
            "curl", "-s", "-X", "GET", url,
            *header_args,
            "-H", "Content-Type: application/json",
            "--max-time", str(timeout),
            "-w", "\n__HTTP_STATUS__%{http_code}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
            stdout_str = stdout.decode("utf-8", errors="replace")

            parts = stdout_str.split("\n__HTTP_STATUS__")
            status_code = int(parts[1].strip() if len(parts) > 1 else "0")
            raw_body = parts[0].strip()

            if not raw_body or status_code == 0:
                raise StockityAPIError("Request timeout atau tidak ada response")

            if status_code >= 400:
                raise StockityAPIError(f"HTTP {status_code}: {raw_body[:300]}")

            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                raise StockityAPIError(f"Response bukan JSON (HTTP {status_code}): {raw_body[:300]}")

            return {"status": status_code, "data": parsed}

        except asyncio.TimeoutError:
            raise StockityAPIError("Request timeout")
        except FileNotFoundError:
            raise StockityAPIError("curl binary tidak ditemukan. Install curl: sudo apt install curl")
        except Exception as e:
            raise StockityAPIError(f"Request error: {str(e)}")

    @staticmethod
    async def _curl_post(
        url: str, body: dict, headers: Dict[str, str], timeout: int = 15
    ) -> Dict[str, Any]:
        """HTTP POST menggunakan curl binary (bypass Cloudflare). Digunakan untuk login."""
        header_args = []
        for k, v in headers.items():
            header_args.extend(["-H", f"{k}: {v}"])

        cmd = [
            "curl", "-s", "-X", "POST", url,
            *header_args,
            "-H", "Content-Type: application/json",
            "-d", json.dumps(body),
            "--max-time", str(timeout),
            "-w", "\n__HTTP_STATUS__%{http_code}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
            stdout_str = stdout.decode("utf-8", errors="replace")

            parts = stdout_str.split("\n__HTTP_STATUS__")
            status_code = int(parts[1].strip() if len(parts) > 1 else "0")
            raw_body = parts[0].strip()

            if not raw_body or status_code == 0:
                raise StockityAPIError("Request timeout atau tidak ada response")

            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                raise StockityAPIError(f"Response bukan JSON (HTTP {status_code}): {raw_body[:300]}")

            return {"status": status_code, "data": parsed}

        except asyncio.TimeoutError:
            raise StockityAPIError("Request timeout")
        except FileNotFoundError:
            raise StockityAPIError("curl binary tidak ditemukan")
        except StockityAPIError:
            raise
        except Exception as e:
            raise StockityAPIError(f"Request error: {str(e)}")

    @classmethod
    async def get_balance(
        cls, auth_token: str, device_id: str, timezone: str = DEFAULT_TIMEZONE
    ) -> UserBalance:
        """
        Ambil balance user dari Stockity API.
        Mirrors: ProfileService.getBalance()
        Endpoint: GET /bank/v1/read
        """
        url = f"{cls.BASE_URL}/bank/v1/read?locale=id"
        headers = cls._build_headers(auth_token, device_id, timezone, {
            "Cache-Control": "no-cache",
        })

        try:
            resp = await cls._curl_get(url, headers, timeout=10)
            api_data = resp["data"]

            # Extract data array
            data_list: List[Dict] = []
            if isinstance(api_data, dict):
                data_list = api_data.get("data", []) or []
            elif isinstance(api_data, list):
                data_list = api_data

            # Cari real dan demo account
            real = None
            demo = None
            for d in data_list:
                if isinstance(d, dict):
                    if d.get("account_type") == "real":
                        real = d
                    elif d.get("account_type") == "demo":
                        demo = d

            # Detect currency
            detected_currency = (
                real.get("currency") if real else None
            ) or (
                demo.get("currency") if demo else None
            ) or "IDR"

            real_balance = float(real.get("balance", 0)) if real else 0
            demo_balance = float(demo.get("balance", 0)) if demo else 0

            return UserBalance(
                real_balance=real_balance,
                demo_balance=demo_balance,
                currency=detected_currency,
            )

        except StockityAPIError:
            raise
        except Exception as e:
            logger.error(f"get_balance error: {e}")
            raise StockityAPIError(f"Gagal mengambil balance: {str(e)}")

    @classmethod
    async def get_profile(
        cls, auth_token: str, device_id: str, timezone: str = DEFAULT_TIMEZONE
    ) -> UserProfile:
        """
        Ambil profile user dari Stockity API.
        Mirrors: ProfileService.getProfile()
        Menggunakan platform/private/v2/profile (lebih lengkap).
        """
        url = f"{cls.BASE_URL}/platform/private/v2/profile?locale=id"
        headers = cls._build_headers(auth_token, device_id, timezone)

        try:
            resp = await cls._curl_get(url, headers, timeout=10)
            api_data = resp["data"]

            # Navigate response structure
            profile_data = None
            if isinstance(api_data, dict):
                profile_data = api_data.get("data") or api_data
            else:
                profile_data = api_data

            if not profile_data or not isinstance(profile_data, dict):
                raise StockityAPIError("Data profile kosong")

            return UserProfile(
                id=profile_data.get("id", 0),
                email=profile_data.get("email", ""),
                first_name=profile_data.get("first_name", ""),
                last_name=profile_data.get("last_name", ""),
                username=profile_data.get("username"),
                nickname=profile_data.get("nickname"),
                phone=profile_data.get("phone"),
                gender=profile_data.get("gender"),
                country=profile_data.get("country"),
                birthday=profile_data.get("birthday"),
                registered_at=profile_data.get("registered_at") or profile_data.get("created_at"),
                avatar=profile_data.get("avatar"),
                currency=profile_data.get("currency", "IDR"),
                email_verified=profile_data.get("email_verified", False),
                phone_verified=profile_data.get("phone_verified", False),
                personal_data_locked=profile_data.get("personal_data_locked", False),
                docs_verified=profile_data.get("docs_verified", False),
            )

        except StockityAPIError:
            # Fallback ke passport/v1/user_profile
            try:
                return await cls._get_profile_v1(auth_token, device_id, timezone)
            except Exception:
                raise
        except Exception as e:
            logger.error(f"get_profile error: {e}")
            raise StockityAPIError(f"Gagal mengambil profile: {str(e)}")

    @classmethod
    async def _get_profile_v1(
        cls, auth_token: str, device_id: str, timezone: str = DEFAULT_TIMEZONE
    ) -> UserProfile:
        """Fallback: ambil profile dari endpoint v1."""
        url = f"{cls.BASE_URL}/passport/v1/user_profile?locale=id"
        headers = cls._build_headers(auth_token, device_id, timezone)

        resp = await cls._curl_get(url, headers, timeout=10)
        api_data = resp["data"]

        profile_data = None
        if isinstance(api_data, dict):
            profile_data = api_data.get("data") or api_data
        else:
            profile_data = api_data

        if not profile_data or not isinstance(profile_data, dict):
            raise StockityAPIError("Data profile v1 kosong")

        return UserProfile(
            id=profile_data.get("id", 0),
            email=profile_data.get("email", ""),
            first_name=profile_data.get("first_name", ""),
            last_name=profile_data.get("last_name", ""),
            username=profile_data.get("username"),
            nickname=profile_data.get("nickname"),
            phone=profile_data.get("phone"),
            gender=profile_data.get("gender"),
            country=profile_data.get("country"),
            birthday=profile_data.get("birthday"),
            registered_at=profile_data.get("registered_at") or profile_data.get("created_at"),
            avatar=profile_data.get("avatar"),
            currency="IDR",  # v1 tidak punya field currency
        )

    @classmethod
    async def login(
        cls, email: str, password: str, device_id: str
    ) -> Optional[str]:
        """
        Login ke Stockity API menggunakan email + password (PK dari sessions).
        Digunakan untuk me-refresh token yang expired saat fetch balance gagal.

        Endpoint: POST /passport/v2/sign_in?locale=id
        Response:  { data: { authtoken: str, user_id: str } }

        Returns auth token baru jika berhasil, None jika gagal.
        """
        url = f"{cls.BASE_URL}/passport/v2/sign_in?locale=id"
        headers = {
            "device-id":     device_id,
            "device-type":   "web",
            "user-timezone": DEFAULT_TIMEZONE,
            "accept":        "application/json, text/plain, */*",
            "User-Agent":    DEFAULT_USER_AGENT,
            "Origin":        "https://stockity.id",
            "Referer":       "https://stockity.id/",
        }

        try:
            resp = await cls._curl_post(
                url, {"email": email, "password": password}, headers, timeout=15
            )
            status = resp["status"]

            if status == 429:
                logger.warning(f"[Login] Rate limited (429) untuk {email}")
                return None

            if status >= 400:
                logger.warning(f"[Login] Gagal untuk {email}: HTTP {status}")
                return None

            token: Optional[str] = resp["data"].get("data", {}).get("authtoken")
            if not token:
                logger.warning(f"[Login] authtoken tidak ada di response untuk {email}")
                return None

            logger.info(f"[Login] Berhasil refresh token untuk {email}")
            return token

        except StockityAPIError as e:
            logger.warning(f"[Login] StockityAPIError untuk {email}: {e}")
            return None
        except Exception as e:
            logger.error(f"[Login] Error untuk {email}: {e}")
            return None

    @classmethod
    async def get_user_balance_by_session(
        cls, session
    ) -> UserBalance:
        """
        Convenience method: ambil balance menggunakan session object.
        Session object harus punya: stockity_token, device_id, user_timezone
        """
        return await cls.get_balance(
            auth_token=session.stockity_token,
            device_id=session.device_id,
            timezone=session.user_timezone,
        )

    @classmethod
    async def get_user_profile_by_session(
        cls, session
    ) -> UserProfile:
        """
        Convenience method: ambil profile menggunakan session object.
        """
        return await cls.get_profile(
            auth_token=session.stockity_token,
            device_id=session.device_id,
            timezone=session.user_timezone,
        )


# Singleton instance
stockity_api = StockityAPI()