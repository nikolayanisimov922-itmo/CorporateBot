"""Кнопка «💰 Баланс» (только админ): остаток на Claude и ввод суммы после пополнения."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import keyboards as kb
from app.billing import BillingMonitor
from config import Config

router = Router()


class BalanceStates(StatesGroup):
    waiting_amount = State()


def _parse_amount(text: str) -> float | None:
    cleaned = text.strip().lstrip("$").rstrip("$").replace(",", ".").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if 0 <= value < 100_000 else None


@router.message(F.text == kb.BTN_BALANCE)
@router.message(Command("balance"))
async def show_balance(
    message: Message, state: FSMContext, config: Config, billing: BillingMonitor
) -> None:
    if not config.is_admin(message.from_user.id):
        return
    await state.set_state(BalanceStates.waiting_amount)
    await message.answer(
        billing.status_text(),
        reply_markup=kb.cancel_menu("Новый баланс в $, напр. 20"),
        disable_web_page_preview=True,
    )


@router.message(BalanceStates.waiting_amount, F.text == kb.BTN_CANCEL)
async def cancel_balance(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок, ничего не меняю.", reply_markup=kb.main_menu(is_admin=True))


@router.message(BalanceStates.waiting_amount, F.text)
async def set_balance(
    message: Message, state: FSMContext, billing: BillingMonitor
) -> None:
    amount = _parse_amount(message.text)
    if amount is None:
        await message.answer(
            "Не понял сумму. Пришлите только число в долларах, например: 20\n"
            "Или нажмите «❌ Отмена»."
        )
        return
    billing.set_balance(amount)
    await state.clear()
    await message.answer(
        f"✅ Записал: на Claude сейчас <b>${amount:.2f}</b>.\n"
        f"Предупрежу, когда останется меньше ${billing.low_balance_usd:.2f}.",
        reply_markup=kb.main_menu(is_admin=True),
    )
