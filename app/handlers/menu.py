"""Команда /start, главное меню, помощь и переключение языка."""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app import keyboards as kb
from app.i18n import t
from app.users import UserRegistry
from config import Config

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config, users: UserRegistry) -> None:
    is_admin = config.is_admin(message.from_user.id)
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("greeting", lang), reply_markup=kb.main_menu(is_admin))


@router.message(F.text == kb.BTN_LANG)
async def switch_language(
    message: Message, config: Config, users: UserRegistry
) -> None:
    current = users.get_lang(message.from_user.id)
    new_lang = "en" if current == "ru" else "ru"
    users.set_lang(message.from_user.id, new_lang)
    is_admin = config.is_admin(message.from_user.id)
    await message.answer(
        t("lang_switched", new_lang), reply_markup=kb.main_menu(is_admin)
    )


@router.message(F.text == kb.BTN_HELP)
async def on_help(message: Message, config: Config, users: UserRegistry) -> None:
    is_admin = config.is_admin(message.from_user.id)
    lang = users.get_lang(message.from_user.id)

    lines = [t("help_title", lang), "", t("help_kb", lang), t("help_submit", lang)]
    if is_admin:
        lines.append(t("help_admin_broadcast", lang))
        lines.append(t("help_admin_refresh", lang))
    lines.append(t("help_lang", lang))
    lines.append("")
    lines.append(t("help_start_note", lang))

    if config.support_username:
        lines.append("")
        lines.append(t("help_contact", lang).format(user=config.support_username))

    await message.answer(
        "\n".join(lines),
        reply_markup=kb.main_menu(is_admin),
        disable_web_page_preview=True,
    )


@router.message()
async def fallback(message: Message, config: Config, users: UserRegistry) -> None:
    """Любое непонятное сообщение — вежливо возвращаем в меню (вне режимов)."""
    is_admin = config.is_admin(message.from_user.id)
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("fallback", lang), reply_markup=kb.main_menu(is_admin))
