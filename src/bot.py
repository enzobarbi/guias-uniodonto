import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update, Message, PhotoSize
from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ----- ESTADOS DA CONVERSA -----
WAITING_PHOTO, WAITING_NAME, WAITING_VALUE = range(3)

DOWNLOAD_DIR = Path("fotos")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --------- HELPERS ---------

def sanitize_filename_component(text: str) -> str:
    """
    Remove caracteres problemáticos para nomes de arquivo.
    Mantém letras, números, espaços, hífens e underscores.
    Converte múltiplos espaços em underscore.
    """
    text = text.strip()
    # troque acentos simples; opcional: normalizar unicode
    text = re.sub(r"[^\w\s\-.,;]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text)
    return text[:80]  # evita nomes muito longos

def parse_currency(text: str) -> Optional[str]:
    """
    Aceita formatos como: 123,45 | 1.234,56 | R$ 123,45 | 123.45
    Retorna string formatada '123,45' (padrão BR), ou None se inválido.
    """
    if not text:
        return None
    t = text.strip().upper()
    t = t.replace("R$", "").replace(" ", "")
    # se tiver vírgula, assumimos que é decimal br; remover pontos de milhar
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    # agora t deve estar em decimal com ponto
    try:
        value = float(t)
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return None

def best_photo(photos: list[PhotoSize]) -> PhotoSize:
    """Escolhe a melhor resolução (a última costuma ser a maior)."""
    return photos[-1]

def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# --------- HANDLERS ---------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Olá! Envie **uma foto** da guia.\n"
        "Depois vou pedir *nome* e *valor* para salvar o arquivo com essas informações.",
        parse_mode="Markdown",
    )
    return WAITING_PHOTO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Conversa cancelada. Use /start para recomeçar.")
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg: Message = update.message
    if not msg.photo:
        await msg.reply_text("Ops, preciso de uma *foto*. Tente novamente.", parse_mode="Markdown")
        return WAITING_PHOTO

    # Guarda o file_id da melhor resolução
    ph = best_photo(msg.photo)
    context.user_data["pending_photo_file_id"] = ph.file_id

    await msg.reply_text("Recebi a foto! Agora me diga o *nome* para o arquivo.", parse_mode="Markdown")
    return WAITING_NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text or ""
    name_clean = sanitize_filename_component(name)
    if not name_clean:
        await update.message.reply_text("Não entendi o nome. Pode enviar novamente?")
        return WAITING_NAME

    context.user_data["name"] = name_clean
    await update.message.reply_text(
        "Perfeito. Agora informe o *valor da guia* (ex.: 123,45 ou R$ 123,45).",
        parse_mode="Markdown",
    )
    return WAITING_VALUE

async def handle_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value_raw = update.message.text or ""
    value_fmt = parse_currency(value_raw)
    if value_fmt is None:
        await update.message.reply_text(
            "Valor inválido. Tente algo como *123,45* ou *R$ 123,45*.",
            parse_mode="Markdown",
        )
        return WAITING_VALUE

    context.user_data["value"] = value_fmt

    # Agora baixamos a foto que ficou pendente
    file_id = context.user_data.get("pending_photo_file_id")
    if not file_id:
        await update.message.reply_text("Não encontrei a foto. Envie a foto novamente, por favor.")
        # volta para o estado de esperar foto
        return WAITING_PHOTO

    # Recupera extensão do arquivo quando baixar
    try:
        # Baixa arquivo
        tg_file = await context.bot.get_file(file_id)
        # tenta inferir extensão do caminho remoto
        ext = Path(tg_file.file_path).suffix.lower() if tg_file.file_path else ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"

        fname = f"{timestamp_now()} - {context.user_data['name']} - R$ {context.user_data['value']}{ext}"
        dest = DOWNLOAD_DIR / fname
        await tg_file.download_to_drive(custom_path=str(dest))

        await update.message.reply_text(f"✅ Arquivo salvo em: `{dest}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Falhou ao baixar/salvar a foto: {e}")
        return WAITING_PHOTO

    # Limpa somente itens da última operação (deixa a conversa pronta p/ próxima foto)
    context.user_data.pop("pending_photo_file_id", None)
    context.user_data.pop("name", None)
    context.user_data.pop("value", None)

    await update.message.reply_text(
        "Se quiser salvar outra guia, é só **enviar outra foto**. Para sair, use /cancel.",
        parse_mode="Markdown",
    )
    return WAITING_PHOTO

async def handle_text_when_waiting_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Envie uma *foto* para começar, por favor. 😊", parse_mode="Markdown")
    return WAITING_PHOTO

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN com o token do BotFather.")

    application = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_when_waiting_photo),
            ],
            WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name),
            ],
            WAITING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv)

    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        # Em alguns ambientes, já existe um loop rodando; nesse caso, apenas chama main() sem asyncio.run
        main()
