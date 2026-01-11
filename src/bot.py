import os
import re
import asyncio
import base64
import json
import shutil
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from contextlib import contextmanager

from telegram import Update, Message, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
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
from openai import OpenAI

# ----- CONFIGURAÇÃO DE LOGGING -----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ----- FILTROS DE WARNING -----
filterwarnings(
    "ignore",
    category=PTBUserWarning,
    message=r"If 'per_message=False', 'CallbackQueryHandler' will not be tracked"
)

# ----- CARREGAMENTO DE VARIÁVEIS DE AMBIENTE -----
load_dotenv()

# ----- CLIENTE OPENAI -----
_openai_api_key = os.getenv("OPENAI_API_KEY")
if not _openai_api_key:
    raise RuntimeError("Defina a variável de ambiente OPENAI_API_KEY no arquivo .env")

openai_client = OpenAI(api_key=_openai_api_key)

# ----- ESTADOS DA CONVERSA -----
WAITING_PHOTO, WAITING_CONFIRMATION = range(2)

# ----- DIRETÓRIO DE DOWNLOADS -----
DOWNLOAD_DIR = Path("fotos")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --------- CONTEXT MANAGERS ---------

@contextmanager
def temp_image_file(ext=".jpg"):
    """
    Context manager para garantir limpeza de arquivos temporários.
    Garante que o arquivo será deletado mesmo em caso de erro.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        yield tmp_path
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.debug(f"Arquivo temporário removido: {tmp_path}")
            except Exception as e:
                logger.warning(f"Falha ao remover arquivo temporário {tmp_path}: {e}")

# --------- HELPERS ---------

def sanitize_filename_component(text: str) -> str:
    """
    Remove caracteres inválidos de nomes de arquivo e limita o tamanho.
    
    Args:
        text: Texto a ser sanitizado
        
    Returns:
        String segura para uso em nome de arquivo
    """
    if not text:
        return ""
    
    text = text.strip()
    # Remove caracteres especiais, mantendo apenas alfanuméricos, espaços, hífen, ponto, vírgula e ponto-e-vírgula
    text = re.sub(r"[^\w\s\-.,;]", "", text, flags=re.UNICODE)
    # Substitui múltiplos espaços por underscore
    text = re.sub(r"\s+", "_", text)
    # Limita tamanho para evitar problemas com sistemas de arquivo
    return text[:80]

def parse_currency(text: str) -> str:
    """
    Converte texto para formato brasileiro R$ X.XXX,XX
    
    Exemplos:
        "65.00" → "65,00"
        "1500,50" → "1.500,50"
        "1.500.50" → "1.500,50"
    
    Args:
        text: Valor em formato textual
        
    Returns:
        Valor formatado no padrão brasileiro ou "0,00" se inválido
    """
    if not text:
        return "0,00"
    
    # Remove tudo exceto dígitos, vírgulas e pontos
    clean = re.sub(r"[^\d,.]", "", text.strip())
    
    if not clean:
        return "0,00"
    
    # Normaliza para ponto decimal
    if "," in clean and "." in clean:
        # Formato 1.000,50 → 1000.50
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        # Formato 1000,50 → 1000.50
        clean = clean.replace(",", ".")
    
    try:
        value = float(clean)
        # Formata para padrão brasileiro
        formatted = f"{value:,.2f}".replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
        return formatted
    except ValueError:
        logger.warning(f"Falha ao converter moeda: {text}")
        return "0,00"

def best_photo(photos: list[PhotoSize]) -> PhotoSize:
    """Retorna a foto de maior resolução da lista."""
    return photos[-1]

def timestamp_now() -> str:
    """Retorna timestamp atual formatado."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def validate_extracted_data(info: dict) -> Tuple[bool, list[str]]:
    """
    Valida se os dados extraídos são minimamente úteis.
    
    Args:
        info: Dicionário com dados extraídos
        
    Returns:
        Tupla (is_valid, lista_de_problemas)
    """
    problems = []
    
    # Valida nome
    nome = info.get("nome", "").strip()
    if not nome or nome == "null" or len(nome) < 3:
        problems.append("Nome não identificado ou inválido")
    
    # Valida senha
    senha = info.get("senha", "").strip()
    if not senha or senha == "null":
        problems.append("Senha não identificada")
    
    # Valida data (formato DD/MM/AAAA)
    data = info.get("data", "").strip()
    if not re.match(r"\d{2}/\d{2}/\d{4}", data):
        problems.append("Data inválida ou ausente (esperado: DD/MM/AAAA)")
    
    # Valida valor
    valor = info.get("valor", "").strip()
    if not valor or valor == "null":
        problems.append("Valor não identificado")
    
    return (len(problems) == 0, problems)

async def extract_guia_info(image_path: str) -> dict:
    """
    Usa a API de visão da OpenAI para extrair informações da guia odontológica.
    
    Args:
        image_path: Caminho para o arquivo de imagem
        
    Returns:
        Dicionário com campos extraídos ou erro
    """
    logger.info(f"Iniciando extração de dados da imagem: {image_path}")
    
    # Converte a imagem para base64
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Erro ao ler arquivo de imagem: {e}")
        return {"erro": f"Erro ao ler arquivo: {e}"}
    
    # Determina o tipo MIME baseado na extensão
    ext = Path(image_path).suffix.lower()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", 
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    
    prompt = """
Você é um assistente de OCR especializado em guias odontológicas brasileiras (padrão TISS).

EXTRAIA EXATAMENTE os seguintes dados da imagem:

1. **Senha** (Campo 5): Código alfanumérico, geralmente no formato "XXXXXXX-XXX"
2. **Nome do Paciente** (Campo 13): Nome completo, geralmente em MAIÚSCULAS
3. **Data** (Campo 4 - Data da Autorização): Formato DD/MM/AAAA
4. **Valor Total** (Campo 46 - Total Quantidade US): Valor em reais (exemplo: "65,00")

REGRAS IMPORTANTES:
- Se um campo não estiver visível ou legível, retorne null (não string "null", mas valor null JSON)
- Preserve formatação original dos valores monetários (com vírgula decimal)
- Para datas, use exatamente o formato DD/MM/AAAA
- Retorne APENAS o JSON, sem markdown (```), sem explicações adicionais

FORMATO DE SAÍDA (JSON puro):
{
  "senha": "string ou null",
  "nome": "string ou null",
  "data": "string ou null",
  "valor": "string ou null"
}
"""

    try:
        logger.info("Enviando requisição para OpenAI API...")
        
        response = openai_client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
        )
        
        # Extrai o texto da resposta
        response_text = response.choices[0].message.content.strip()
        logger.debug(f"Resposta da API: {response_text}")
        
        # Remove possíveis markdown code blocks
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)
        
        # Parseia JSON
        parsed = json.loads(response_text)
        
        # Normaliza valores null
        for key in ["senha", "nome", "data", "valor"]:
            if key in parsed and parsed[key] in [None, "null", "N/A", ""]:
                parsed[key] = None
        
        logger.info(f"Extração bem-sucedida: {parsed}")
        return parsed
        
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao parsear JSON da resposta: {e}\nResposta recebida: {response_text}")
        return {"erro": "Resposta da IA não está em formato JSON válido"}
        
    except Exception as e:
        logger.error(f"Erro na API OpenAI: {e}", exc_info=True)
        return {"erro": f"Erro ao processar com IA: {str(e)}"}

# --------- HANDLERS ---------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler para o comando /start."""
    user = update.effective_user
    logger.info(f"Usuário {user.id} ({user.username or user.first_name}) iniciou conversa")
    
    await update.message.reply_text(
        "Olá! Envie uma *foto* da guia odontológica.\n\n"
        "Para melhor resultado:\n"
        "• Foto nítida e bem iluminada\n"
        "• Guia completa no enquadramento\n"
        "• Sem reflexos ou sombras",
        parse_mode="Markdown",
    )
    return WAITING_PHOTO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler para o comando /cancel."""
    user = update.effective_user
    logger.info(f"Usuário {user.id} cancelou a conversa")
    
    # Limpa arquivo temporário se existir
    temp_path = context.user_data.get("temp_photo_path")
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
            logger.debug(f"Arquivo temporário removido na cancelamento: {temp_path}")
        except Exception as e:
            logger.warning(f"Erro ao remover arquivo temporário: {e}")
    
    context.user_data.clear()
    await update.message.reply_text(
        "Conversa cancelada.\n"
        "Use /start para recomeçar."
    )
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler para recebimento de fotos."""
    msg: Message = update.message
    user = update.effective_user
    
    if not msg.photo:
        await msg.reply_text("Ops, preciso de uma *foto*. Tente novamente.", parse_mode="Markdown")
        return WAITING_PHOTO

    logger.info(f"Usuário {user.id} enviou foto para processamento")
    
    ph = best_photo(msg.photo)
    context.user_data["pending_photo_file_id"] = ph.file_id
    
    # Envia mensagem de processamento com etapas
    processing_msg = await msg.reply_text(
        "*Processando...*\n"
        "Baixando imagem...",
        parse_mode="Markdown"
    )
    
    try:
        # Baixa a foto temporariamente para análise
        tg_file = await context.bot.get_file(ph.file_id)
        ext = Path(tg_file.file_path).suffix.lower() if tg_file.file_path else ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"
        
        # Cria arquivo temporário usando context manager
        with temp_image_file(ext) as tmp_path:
            logger.debug(f"Baixando imagem para: {tmp_path}")
            await tg_file.download_to_drive(custom_path=tmp_path)
            
            # Atualiza mensagem
            await processing_msg.edit_text(
                "*Processando...*\n"
                "Imagem baixada. Analisando...",
                parse_mode="Markdown"
            )
            
            # Extrai informações com OpenAI
            info = await extract_guia_info(tmp_path)
            
            # Copia arquivo temporário para não perder referência
            # (o context manager vai deletar o arquivo ao sair do bloco)
            new_tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            new_tmp_path = new_tmp.name
            new_tmp.close()
            shutil.copy2(tmp_path, new_tmp_path)
        
        # Armazena o novo caminho temporário e as informações extraídas
        context.user_data["temp_photo_path"] = new_tmp_path
        context.user_data["extracted_info"] = info
        
        # Verifica se houve erro na extração
        if "erro" in info:
            logger.warning(f"Erro na extração para usuário {user.id}: {info['erro']}")
            await processing_msg.edit_text(
                f"*Problema ao analisar a imagem:*\n\n"
                f"`{info['erro']}`\n\n"
                "Por favor, envie outra foto com melhor qualidade.",
                parse_mode="Markdown"
            )
            # Limpa arquivo temporário
            if os.path.exists(new_tmp_path):
                os.unlink(new_tmp_path)
            return WAITING_PHOTO
        
        # Valida dados extraídos
        is_valid, problems = validate_extracted_data(info)
        
        # Monta mensagem com informações extraídas
        info_text = "*Informações extraídas:*\n\n"
        info_text += f"*Nome:* {info.get('nome') or 'Não identificado'}\n"
        info_text += f"*Senha:* {info.get('senha') or 'Não identificada'}\n"
        info_text += f"*Data:* {info.get('data') or 'Não identificada'}\n"
        info_text += f"*Valor:* R$ {info.get('valor') or 'Não identificado'}\n\n"
        
        # Adiciona avisos se houver problemas
        if not is_valid:
            info_text += "*Atenção - Dados incompletos:*\n"
            for problem in problems:
                info_text += f"• {problem}\n"
            info_text += "\n"
        
        info_text += "*As informações estão corretas?*"
        
        keyboard = [
            [
                InlineKeyboardButton("Confirmar", callback_data="CONFIRM"),
                InlineKeyboardButton("Reenviar foto", callback_data="RETRY"),
            ]
        ]
        
        await processing_msg.edit_text(
            info_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        
        logger.info(f"Usuário {user.id}: Dados extraídos e aguardando confirmação")
        return WAITING_CONFIRMATION
        
    except Exception as e:
        logger.error(f"Erro ao processar foto do usuário {user.id}: {e}", exc_info=True)
        await processing_msg.edit_text(
            f"*Erro ao processar a foto:*\n\n`{e}`\n\n"
            "Por favor, tente novamente.",
            parse_mode="Markdown"
        )
        # Limpa arquivo temporário se existir
        if "temp_photo_path" in context.user_data:
            temp_path = context.user_data["temp_photo_path"]
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return WAITING_PHOTO

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe confirmação das informações extraídas e salva o arquivo."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    if query.data == "RETRY":
        logger.info(f"Usuário {user.id} solicitou reenvio de foto")
        
        # Limpa dados e volta para esperar nova foto
        temp_path = context.user_data.get("temp_photo_path")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        context.user_data.clear()
        
        await query.edit_message_text(
            "Envie uma nova foto da guia.",
        )
        return WAITING_PHOTO
    
    # CONFIRM - salva o arquivo
    logger.info(f"Usuário {user.id} confirmou dados, salvando arquivo...")
    
    temp_path = context.user_data.get("temp_photo_path")
    info = context.user_data.get("extracted_info", {})

    if not temp_path or not os.path.exists(temp_path):
        logger.error(f"Usuário {user.id}: Arquivo temporário não encontrado")
        await query.edit_message_text(
            "Faltam dados para salvar. Envie a foto novamente."
        )
        context.user_data.clear()
        return WAITING_PHOTO

    try:
        # Extrai e sanitiza informações
        nome = sanitize_filename_component(info.get("nome") or "SEM_NOME")
        senha = sanitize_filename_component(info.get("senha") or "SEM_SENHA")
        data = sanitize_filename_component(info.get("data") or "SEM_DATA")
        preco_raw = info.get("valor") or "0,00"
        
        # Formata o preço
        preco_fmt = parse_currency(preco_raw)
        
        # Monta o nome do arquivo
        ext = Path(temp_path).suffix.lower()
        fname = f"{nome} - {senha} - {data} - {preco_fmt} - GTO{ext}"
        dest = DOWNLOAD_DIR / fname
        
        # Move o arquivo temporário para o destino final
        shutil.move(temp_path, str(dest))
        
        logger.info(f"Usuário {user.id}: Arquivo salvo com sucesso - {fname}")

        # Atualiza a mensagem
        await query.edit_message_text(
            f"*Arquivo salvo com sucesso.*\n\n"
            f"Nome: `{fname}`\n"
            f"Local: `{DOWNLOAD_DIR}/`",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Usuário {user.id}: Falha ao salvar arquivo - {e}", exc_info=True)
        await query.edit_message_text(
            f"*Falha ao salvar:*\n\n`{e}`\n\n"
            "Por favor, tente novamente.",
            parse_mode="Markdown"
        )
        # Remove arquivo temporário em caso de erro
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        return WAITING_PHOTO

    # Limpa dados do contexto
    context.user_data.clear()

    # Manda uma mensagem preparando para a próxima
    if query.message and query.message.chat:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Para salvar outra guia, envie uma nova foto.\n"
                 "Use /cancel para encerrar.",
            parse_mode="Markdown",
        )

    return WAITING_PHOTO

async def handle_text_when_waiting_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler para mensagens de texto quando esperando foto."""
    await update.message.reply_text(
        "Envie uma *foto* da guia para continuar.\n"
        "Use /cancel para encerrar.",
        parse_mode="Markdown"
    )
    return WAITING_PHOTO

def main():
    """Função principal que inicializa e roda o bot."""
    logger.info("=" * 50)
    logger.info("Iniciando bot de processamento de guias odontológicas")
    logger.info("=" * 50)
    
    # Valida token
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.critical("BOT_TOKEN não definido no arquivo .env")
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN com o token do BotFather.")

    # Cria aplicação
    application = Application.builder().token(token).build()

    # Configura ConversationHandler
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_when_waiting_photo),
            ],
            WAITING_CONFIRMATION: [
                CallbackQueryHandler(handle_confirmation),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=False,
    )

    application.add_handler(conv)

    logger.info("Bot configurado com sucesso")
    logger.info(f"Diretório de salvamento: {DOWNLOAD_DIR.absolute()}")
    print("\n" + "="*50)
    print("BOT RODANDO - Pressione Ctrl+C para parar")
    print("="*50 + "\n")
    
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot encerrado pelo usuário")
        print("\n\nBot encerrado.")
    except RuntimeError:
        # Fallback para ambientes que já têm event loop
        main()
    except Exception as e:
        logger.critical(f"Erro fatal ao iniciar bot: {e}", exc_info=True)
        raise