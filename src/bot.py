import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from telegram import Update, Message, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from warnings import filterwarnings
from telegram.warnings import PTBUserWarning

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

filterwarnings(
    "ignore",
    category=PTBUserWarning,
    message=r"If 'per_message=False', 'CallbackQueryHandler' will not be tracked"
)

load_dotenv(override=True)

# ----- ESTADOS DA CONVERSA -----
WAITING_PHOTO, WAITING_DOC_TYPE = range(2)

DOWNLOAD_DIR = Path("/Users/enzobarbi/Development/github/guias-uniodonto/fotos")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --------- HELPERS ---------

def sanitize_filename_component(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w\s\-.,;]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text)
    return text[:80]

def escape_markdown_v2(text: str) -> str:
    """Escapa caracteres especiais para Markdown V2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\1', text)

def parse_date(text: str) -> Optional[str]:
    """Valida e retorna a data no formato DD/MM/YYYY."""
    if not text:
        return None
    text = text.strip()
    # Verifica formato DD/MM/YYYY
    pattern = r"^(\d{2})/(\d{2})/(\d{4})$"
    match = re.match(pattern, text)
    if not match:
        return None
    
    day, month, year = match.groups()
    try:
        # Valida se é uma data válida
        datetime(int(year), int(month), int(day))
        return text  # Retorna no formato DD/MM/YYYY
    except ValueError:
        return None

def extract_name_and_date_from_caption(caption: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrai nome e data da legenda da foto.
    Formato esperado: "Nome da Pessoa 15/10/2025" ou variações
    """
    if not caption:
        return None, None
    
    caption = caption.strip()
    
    # Procura por padrão de data DD/MM/YYYY
    date_pattern = r"(\d{2}/\d{2}/\d{4})"
    date_match = re.search(date_pattern, caption)
    
    if not date_match:
        return None, None
    
    date_str = date_match.group(1)
    date_validated = parse_date(date_str)
    
    if not date_validated:
        return None, None
    
    # Remove a data da caption para extrair o nome
    name_part = re.sub(date_pattern, "", caption).strip()
    
    # Remove caracteres extras e espaços múltiplos
    name_part = re.sub(r'\s+', ' ', name_part).strip()
    
    if not name_part:
        return None, None
    
    name_clean = sanitize_filename_component(name_part)
    
    return name_clean, date_validated

def best_photo(photos: list[PhotoSize]) -> PhotoSize:
    return photos[-1]

def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# --------- HANDLERS ---------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Comando /start recebido de {update.effective_user.id}")
    
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name or "usuário"
    
    # Mensagem modificada explicando o novo formato
    message = (
        f"Olá, {user_name}! Envie **uma foto** da guia.\n"
        "Na legenda da foto coloque *nome* e *data* e depois você escolhe o tipo (RX ou GTO).\n\n"
        "📝 **Formato da legenda:** `João Silva 15/10/2025`\n"
        "📅 **Data:** DD/MM/YYYY\n\n"
        f"*Seu Chat ID:* `{chat_id}`\n"
    )
    
    try:
        await update.message.reply_text(
            message,
            parse_mode="Markdown",
        )
        logger.info("Mensagem de start enviada com sucesso")
        return WAITING_PHOTO
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de start: {e}")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Comando /cancel recebido de {update.effective_user.id}")
    context.user_data.clear()
    await update.message.reply_text("Conversa cancelada. Use /start para recomeçar.")
    return ConversationHandler.END

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Encerra o bot e envia mensagem de despedida."""
    logger.info(f"Comando /stop recebido de {update.effective_user.id}")
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name or "usuário"
    
    # Envia mensagem de despedida
    await update.message.reply_text(
        f"👋 Até logo, {user_name}!\n\n"
        "🤖 Bot encerrado. Obrigado por usar!",
        parse_mode="Markdown",
    )
    
    # Envia notificação para o admin se configurado
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")
    if admin_chat_id and str(admin_chat_id) != str(chat_id):
        try:
            await context.bot.send_message(
                chat_id=int(admin_chat_id),
                text=f"🔴 Bot encerrado por {user_name} (Chat ID: {chat_id})",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de encerramento: {e}")
    
    logger.info("Bot encerrado via comando /stop")
    
    # Para o bot
    context.application.stop()
    
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Foto recebida de {update.effective_user.id}")
    
    msg: Message = update.message
    if not msg.photo:
        await msg.reply_text("Ops, preciso de uma *foto*. Tente novamente.", parse_mode="Markdown")
        return WAITING_PHOTO

    # Extrai nome e data da legenda
    caption = msg.caption or ""
    name, date = extract_name_and_date_from_caption(caption)
    
    if not name or not date:
        await msg.reply_text(
            "❌ Não consegui extrair o nome e data da legenda.\n\n"
            "📝 **Formato correto:** `João Silva 15/10/2025`\n"
            "📅 **Data:** DD/MM/YYYY\n\n"
            "Tente enviar a foto novamente com a legenda no formato correto.",
            parse_mode="Markdown"
        )
        return WAITING_PHOTO

    # Salva os dados extraídos
    ph = best_photo(msg.photo)
    context.user_data["pending_photo_file_id"] = ph.file_id
    context.user_data["name"] = name
    context.user_data["date"] = date
    
    logger.info(f"Dados extraídos - Nome: {name}, Data: {date}")

    # Mostra botões de escolha (RX / GTO) diretamente
    keyboard = [
        [
            InlineKeyboardButton("📎 Anexar RX", callback_data="RX"),
            InlineKeyboardButton("📄 Anexar GTO Digitalizada", callback_data="GTO"),
        ]
    ]
    
    # Converte underscores de volta para espaços para exibição
    display_name = name.replace("_", " ")
    
    try:
        await msg.reply_text(
            f"✅ *Dados extraídos:*\n"
            f"👤 *Nome:* {display_name}\n"
            f"�� *Data:* {date}\n\n"
            "Escolha o tipo do documento:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except BadRequest as e:
        logger.error(f"Erro de BadRequest ao enviar mensagem: {e}")
        # Fallback sem formatação Markdown
        await msg.reply_text(
            f"✅ Dados extraídos:\n"
            f"👤 Nome: {display_name}\n"
            f"📅 Data: {date}\n\n"
            "Escolha o tipo do documento:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar mensagem: {e}")
        await msg.reply_text(
            "Dados extraídos com sucesso! Escolha o tipo do documento:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return WAITING_DOC_TYPE

async def handle_doc_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe a escolha do botão (RX/GTO), baixa a foto e salva com o sufixo."""
    logger.info(f"Tipo de documento escolhido: {update.callback_query.data}")
    
    query = update.callback_query
    await query.answer()

    doc_type = query.data  # "RX" ou "GTO"
    context.user_data["doc_type"] = doc_type

    # Valida dados necessários
    file_id = context.user_data.get("pending_photo_file_id")
    name = context.user_data.get("name")
    date = context.user_data.get("date")

    if not (file_id and name and date):
        await query.edit_message_text("Faltam dados para salvar. Envie a foto novamente, por favor.")
        context.user_data.clear()
        return WAITING_PHOTO

    # Baixa e salva com sufixo do tipo
    try:
        tg_file = await context.bot.get_file(file_id)
        ext = Path(tg_file.file_path).suffix.lower() if tg_file.file_path else ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"

        # Sanitiza a data substituindo barras por hífens para evitar problemas no sistema de arquivos
        date_safe = date.replace("/", "-")
        
        fname = f"{name} - {date_safe} - {doc_type}{ext}"
        dest = DOWNLOAD_DIR / fname
        
        # Garante que o diretório existe
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        await tg_file.download_to_drive(custom_path=str(dest))
        
        logger.info(f"Arquivo salvo: {dest}")

        # Atualiza a mensagem dos botões para um texto final
        try:
            await query.edit_message_text(
                f"✅ *Arquivo salvo como:*\n`{fname}`\n\n"
                f"📁 *Local:* `{dest}`",
                parse_mode="Markdown",
            )
        except BadRequest:
            # Fallback sem formatação Markdown
            await query.edit_message_text(
                f"✅ Arquivo salvo como:\n{fname}\n\n"
                f"📁 Local: {dest}"
            )

    except Exception as e:
        logger.error(f"Erro ao baixar/salvar foto: {e}")
        await query.edit_message_text(f"❌ Falhou ao baixar/salvar a foto: {e}")
        return WAITING_PHOTO

    # Limpa dados e volta para esperar outra foto
    context.user_data.pop("pending_photo_file_id", None)
    context.user_data.pop("name", None)
    context.user_data.pop("date", None)
    context.user_data.pop("doc_type", None)

    # Manda uma mensagem fora do callback preparando para a próxima
    if query.message and query.message.chat:
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Se quiser salvar outra guia, é só *enviar outra foto* com nome e data na legenda. Para sair, use /cancel.",
                parse_mode="Markdown",
            )
        except BadRequest:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Se quiser salvar outra guia, é só enviar outra foto com nome e data na legenda. Para sair, use /cancel."
            )

    return WAITING_PHOTO

async def handle_text_when_waiting_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Texto recebido quando esperava foto: {update.message.text}")
    try:
        await update.message.reply_text(
            "Envie uma *foto* com nome e data na legenda para começar. 😊\n\n"
            "📝 *Formato:* `João Silva 15/10/2025`", 
            parse_mode="Markdown"
        )
    except BadRequest:
        await update.message.reply_text(
            "Envie uma foto com nome e data na legenda para começar. 😊\n\n"
            "�� Formato: João Silva 15/10/2025"
        )
    return WAITING_PHOTO

async def post_init(application: Application) -> None:
    """Envia uma mensagem quando o bot estiver pronto."""
    logger.info("Bot inicializado, tentando enviar mensagem de confirmação...")
    
    # Obtém informações do bot e imprime
    try:
        bot_info = await application.bot.get_me()
        bot_name = bot_info.first_name
        token = os.getenv("BOT_TOKEN", "N/A")
        
        print("\n" + "="*50)
        print("🤖 BOT INICIADO")
        print("="*50)
        print(f"Token: {token}")
        print(f"Nome do Bot: {bot_name}")
        print("="*50 + "\n")
    except Exception as e:
        logger.error(f"Erro ao obter informações do bot: {e}")
        token = os.getenv("BOT_TOKEN", "N/A")
        print("\n" + "="*50)
        print("🤖 BOT INICIADO")
        print("="*50)
        print(f"Token: {token}")
        print("Nome do Bot: Erro ao obter informações")
        print("="*50 + "\n")
    
    chat_id = os.getenv("ADMIN_CHAT_ID")
    if chat_id:
        try:
            await application.bot.send_message(
                chat_id=int(chat_id),
                text="🤖 Bot iniciado e pronto para receber guias! Use /start para começar.",
                parse_mode="Markdown",
            )
            logger.info(f"Mensagem de inicialização enviada para o chat {chat_id}")
        except Exception as e:
            logger.error(f"Não foi possível enviar mensagem de inicialização: {e}")
    else:
        logger.warning("ADMIN_CHAT_ID não configurado. Bot iniciado sem enviar mensagem.")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN não encontrado!")
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN com o token do BotFather.")

    logger.info("Iniciando aplicação...")
    
    application = Application.builder().token(token).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_when_waiting_photo),
            ],
            WAITING_DOC_TYPE: [
                CallbackQueryHandler(handle_doc_type),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=False,
    )

    application.add_handler(conv)
    
    # Adiciona handler para /stop (fora do ConversationHandler para estar sempre disponível)
    application.add_handler(CommandHandler("stop", stop))

    logger.info("Bot configurado, iniciando polling...")
    print("Bot rodando... Pressione Ctrl+C para parar.")
    
    try:
        # MUDANÇA PRINCIPAL: usar run_polling() diretamente em vez de asyncio.run()
        application.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Bot encerrado pelo usuário.")
        print("\nBot encerrado pelo usuário.")
    except Exception as e:
        logger.error(f"Erro ao rodar o bot: {e}")
        print(f"Erro ao rodar o bot: {e}")
        raise

if __name__ == "__main__":
    main()