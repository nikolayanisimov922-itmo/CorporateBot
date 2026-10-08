"""Контроль денег: баланс Claude API и напоминание об оплате хостинга.

Claude (Anthropic) не даёт узнать остаток баланса по обычному ключу, поэтому:
  1. Админ после пополнения сообщает боту сумму (кнопка «💰 Баланс»).
  2. Бот после каждого ответа Claude считает, сколько потрачено (по токенам
     и цене модели), и предупреждает, когда остаток ниже порога.
  3. Если деньги всё-таки кончились и Claude отвечает ошибкой оплаты — бот
     сразу пишет админу (не чаще раза в несколько часов).

Hetzner работает по постоплате: раз в месяц списывает деньги с карты. Бот
присылает напоминание в заданный день месяца, чтобы на карте были деньги.

Состояние хранится в data/billing.json.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib
from typing import Awaitable, Callable

import anthropic

BILLING_FILE = pathlib.Path("data") / "billing.json"

# Цена в долларах за 1 млн токенов: (вход, выход).
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# Для незнакомой модели считаем с запасом — лучше предупредить раньше.
DEFAULT_PRICE = (5.00, 25.00)

# Не спамить админа одинаковым «деньги кончились» чаще, чем раз в N часов.
OUT_OF_CREDIT_REPEAT_HOURS = 3

Notifier = Callable[[str], Awaitable[object]]


def is_out_of_credit(err: Exception) -> bool:
    """True, если Claude отказал из-за денег (баланс на нуле / проблема оплаты)."""
    if not isinstance(err, anthropic.APIStatusError):
        return False
    if err.status_code == 402 or getattr(err, "type", None) == "billing_error":
        return True
    text = str(getattr(err, "message", "") or err).lower()
    return "credit balance" in text or "billing" in text


def _cost_usd(model: str, usage) -> float:
    price_in, price_out = PRICES.get(model, DEFAULT_PRICE)
    tokens_in = (
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * 1.25
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * 0.1
    )
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


class BillingMonitor:
    def __init__(self, low_balance_usd: float = 2.0, hosting_day: int = 1,
                 hosting_note: str = "") -> None:
        self.low_balance_usd = low_balance_usd
        self.hosting_day = hosting_day  # 0 — напоминание о хостинге выключено
        self.hosting_note = hosting_note
        self.notify: Notifier | None = None  # задаётся в bot.py после создания бота
        self._state: dict = {
            "balance_usd": None,  # сумма, которую админ указал при пополнении
            "spent_usd": 0.0,  # потрачено с момента пополнения
            "set_at": None,
            "low_alerted": False,
            "out_alert_at": None,
            "hosting_month": None,  # месяц, за который уже напомнили (ГГГГ-ММ)
        }
        self._load()

    # --- хранение ---------------------------------------------------------
    def _load(self) -> None:
        if BILLING_FILE.exists():
            try:
                self._state.update(json.loads(BILLING_FILE.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                logging.warning("Не удалось прочитать %s — начинаю заново.", BILLING_FILE)

    def _save(self) -> None:
        try:
            BILLING_FILE.parent.mkdir(exist_ok=True)
            BILLING_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logging.exception("Не удалось сохранить %s", BILLING_FILE)

    async def _send(self, text: str) -> None:
        if self.notify is None:
            logging.warning("Уведомление админу не отправлено (бот не готов): %s", text)
            return
        try:
            await self.notify(text)
        except Exception:  # noqa: BLE001
            logging.exception("Не удалось отправить уведомление админу")

    # --- Claude -----------------------------------------------------------
    @property
    def remaining_usd(self) -> float | None:
        if self._state["balance_usd"] is None:
            return None
        return self._state["balance_usd"] - self._state["spent_usd"]

    def set_balance(self, amount_usd: float) -> None:
        """Админ пополнил счёт и сообщил текущий баланс — начинаем отсчёт заново."""
        self._state.update(
            balance_usd=amount_usd,
            spent_usd=0.0,
            set_at=dt.datetime.now().isoformat(timespec="seconds"),
            low_alerted=False,
            out_alert_at=None,
        )
        self._save()

    async def record_usage(self, model: str, usage) -> None:
        """Вызывается после каждого успешного ответа Claude."""
        self._state["spent_usd"] += _cost_usd(model, usage)
        self._save()
        left = self.remaining_usd
        if left is None or self._state["low_alerted"] or left > self.low_balance_usd:
            return
        self._state["low_alerted"] = True
        self._save()
        await self._send(
            "⚠️ <b>Заканчиваются деньги на Claude</b>\n\n"
            f"Осталось примерно <b>${max(left, 0):.2f}</b> "
            f"(порог предупреждения — ${self.low_balance_usd:.2f}).\n\n"
            "Пополните баланс: console.anthropic.com → Billing.\n"
            "После пополнения нажмите «💰 Баланс» и введите новый баланс."
        )

    async def on_api_error(self, err: Exception) -> None:
        """Вызывается при любой ошибке Claude: если дело в деньгах — пишем админу."""
        if not is_out_of_credit(err):
            return
        now = dt.datetime.now()
        last = self._state.get("out_alert_at")
        if last:
            try:
                if now - dt.datetime.fromisoformat(last) < dt.timedelta(
                    hours=OUT_OF_CREDIT_REPEAT_HOURS
                ):
                    return
            except ValueError:
                pass
        self._state["out_alert_at"] = now.isoformat(timespec="seconds")
        self._save()
        await self._send(
            "🔴 <b>Деньги на Claude закончились</b>\n\n"
            "Claude отказывается отвечать из-за баланса — база знаний, "
            "договорённости и перевод рассылок сейчас не работают.\n\n"
            "Пополните баланс: console.anthropic.com → Billing.\n"
            "После пополнения нажмите «💰 Баланс» и введите новый баланс."
        )

    def status_text(self) -> str:
        left = self.remaining_usd
        if left is None:
            claude = (
                "Баланс Claude ещё не указан — бот не знает, сколько денег на счёте.\n"
                "Посмотрите баланс на console.anthropic.com → Billing и "
                "пришлите сюда сумму в долларах (например: 20)."
            )
        else:
            claude = (
                f"Указано при пополнении: ${self._state['balance_usd']:.2f}\n"
                f"Потрачено с тех пор: ≈ ${self._state['spent_usd']:.2f}\n"
                f"Осталось: ≈ <b>${max(left, 0):.2f}</b>\n"
                f"Предупрежу, когда останется меньше ${self.low_balance_usd:.2f}.\n\n"
                "Это подсчёт бота — точная сумма на console.anthropic.com → Billing.\n"
                "Пополнили? Пришлите новый баланс в долларах (например: 20)."
            )
        if self.hosting_day:
            hosting = f"Напоминаю об оплате Hetzner каждый месяц {self.hosting_day}-го числа."
        else:
            hosting = "Напоминание об оплате Hetzner выключено."
        return f"💰 <b>Баланс</b>\n\n🤖 <b>Claude</b>\n{claude}\n\n🖥 <b>Хостинг</b>\n{hosting}"

    # --- хостинг ----------------------------------------------------------
    async def check_hosting_reminder(self, now: dt.datetime | None = None) -> None:
        """Раз в месяц, в день hosting_day (с 10:00), напоминает про оплату Hetzner."""
        if not self.hosting_day:
            return
        now = now or dt.datetime.now()
        month = now.strftime("%Y-%m")
        if self._state.get("hosting_month") == month:
            return
        if now.day < self.hosting_day or (now.day == self.hosting_day and now.hour < 10):
            return
        self._state["hosting_month"] = month
        self._save()
        note = f"\nСумма: {self.hosting_note}" if self.hosting_note else ""
        await self._send(
            "💳 <b>Напоминание: оплата сервера Hetzner</b>\n\n"
            "Hetzner раз в месяц сам списывает оплату с привязанной карты."
            f"{note}\n\n"
            "Проверьте, что на карте есть деньги и она не просрочена. "
            "Если оплата не пройдёт, сервер отключат и бот перестанет работать.\n"
            "Счета: console.hetzner.com → Billing (Rechnungen)."
        )
