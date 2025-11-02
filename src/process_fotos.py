#!/usr/bin/env python3
"""
Script para processar automaticamente todas as fotos na pasta fotos/
e fazer upload no site Uniodonto para cada usuário correspondente.
"""

import os
from pathlib import Path
from time import sleep
from datetime import datetime
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Carrega variáveis de ambiente
load_dotenv()

# Configurações
FOTOS_DIR = Path(__file__).parent.parent / "fotos"

# Validação de variáveis de ambiente
def get_env_var(name: str, required: bool = True) -> str:
    """Obtém variável de ambiente com validação.
    
    Args:
        name: Nome da variável de ambiente
        required: Se True, lança exceção se variável não existir ou estiver vazia
        
    Returns:
        Valor da variável de ambiente
        
    Raises:
        ValueError: Se variável for obrigatória e não existir ou estiver vazia
    """
    value = os.getenv(name)
    if required and (value is None or value.strip() == ""):
        raise ValueError(
            f"Variável de ambiente '{name}' não está definida ou está vazia. "
            f"Verifique seu arquivo .env"
        )
    return value

CPF_TALUDE = get_env_var("CPF_TALUDE")
COD_UNIODONTO = get_env_var("COD_UNIODONTO")
PASSWORD = get_env_var("PASSWORD")


class UniodontoProcessor:
    """Classe para processar fotos no site Uniodonto."""
    
    def __init__(self):
        self.driver = None
        self.wait = None
        
    def setup_driver(self):
        """Configura e inicializa o driver do Selenium."""
        opts = Options()
        # opts.add_argument("--headless=new")  # descomente para rodar sem interface
        opts.add_argument("--start-maximized")  # Inicia maximizado
        opts.add_experimental_option("detach", True)  # Mantém navegador aberto mesmo em caso de erro
        
        self.driver = webdriver.Chrome(options=opts)
        self.wait = WebDriverWait(self.driver, 20)
        print("✓ Driver configurado")
        
    def login(self):
        """Faz login no site Uniodonto."""
        print("\n=== Fazendo login ===")
        self.driver.get("https://www.uniodontosc.coop.br/cooperados/index.php")
        sleep(3)
        
        # Preenche CPF
        cpf_bar = self.driver.find_element(By.ID, 'campoCpf')
        sleep(1)
        for numero in CPF_TALUDE:
            sleep(0.5)
            cpf_bar.send_keys(numero)
        
        # Preenche código
        cod_bar = self.driver.find_element(By.ID, 'campoCodigo')
        sleep(1)
        cod_bar.send_keys(COD_UNIODONTO)
        
        # Preenche senha
        paswd_bar = self.driver.find_element(By.ID, 'campoSenha')
        paswd_bar.send_keys(PASSWORD)
        
        sleep(3)
        
        # Clica no botão de login
        login_button = self.driver.find_element(
            By.XPATH, '/html/body/div[2]/section/div[3]/div/div/div/div/form/div/div[4]/div/div/button'
        )
        login_button.click()
        sleep(1.5)
        
        # Fecha o anúncio se existir
        try:
            close_add_button = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[1]/div/a')
            close_add_button.click()
            sleep(1.5)
        except Exception:
            pass
        
        print("✓ Login realizado com sucesso")
        
    def navigate_to_lote_generation(self):
        """Navega para a página de geração de lote."""
        print("\n=== Navegando para geração de lote ===")
        
        # Clica no menu Produção
        production_button = self.driver.find_element(
            By.XPATH, '/html/body/div[1]/div[3]/div[2]/div/div[4]/nav/ul/li[6]/a'
        )
        production_button.click()
        sleep(0.5)
        
        # Clica em Geração de Lote
        lote_generation = self.driver.find_element(
            By.XPATH, '/html/body/div[1]/div[3]/div[2]/div/div[4]/nav/ul/li[6]/ul/li[1]/a'
        )
        lote_generation.click()
        sleep(2)
        
        print("✓ Navegação concluída")
        
    def prepare_search_filters(self):
        """Prepara os filtros de busca (empresa e mês/ano)."""
        print("\n=== Preparando filtros de busca ===")
        
        # Seleciona "Todos" na empresa
        empresa_lote = self.driver.find_element(By.ID, 'empresaLote')
        empresa_lote.click()
        sleep(0.5)
        
        all_option = self.driver.find_element(
            By.XPATH, '/html/body/form/div/div/table/tbody/tr/td/table/tbody/tr[2]/td[3]/select/option[12]'
        )
        all_option.click()
        sleep(0.5)
        
        # Calcula mês/ano anterior
        agora = datetime.now()
        mes = agora.month
        ano = agora.year
        
        if mes == 1:
            mes_anterior = 12
            ano_anterior = ano - 1
        else:
            mes_anterior = mes - 1
            ano_anterior = ano
        
        mes_ano_str = f"{mes_anterior:02d}{ano_anterior}"
        
        # Preenche mês/ano
        month_year = self.driver.find_element(By.ID, 'mesAno')
        month_year.clear()
        month_year.click()
        sleep(1.5)
        
        for n in mes_ano_str:
            sleep(1)
            month_year.send_keys(int(n))
        
        print(f"✓ Filtros configurados (mês/ano: {mes_ano_str})")
        return mes_ano_str
        
    def search_guides(self):
        """Executa a busca de guias."""
        search = self.driver.find_element(By.ID, 'pesquisarGuia')
        search.click()
        sleep(2)
        
        # Espera a tabela carregar
        self.wait.until(EC.presence_of_element_located((By.ID, "tabelaListagem")))
        print("✓ Busca realizada")
        
    def parse_filename(self, file_path):
        """Extrai nome, data e tipo de anexo do nome do arquivo.
        
        Formato esperado: Nome_completo - DD-MM-YYYY - TIPO.jpg
        Exemplo: Leticia_Jahn - 10-10-2025 - GTO.jpg
        """
        file_name = os.path.basename(file_path)
        parts = file_name.split(" - ")
        
        if len(parts) < 3:
            raise ValueError(f"Formato de arquivo inválido: {file_name}")
        
        data_name = parts[0].replace("_", " ")
        data_date = parts[1]  # DD-MM-YYYY
        data_anexo = parts[2].split(".")[0]  # Remove a extensão
        
        nome = data_name.title()
        # Converte data de DD-MM-YYYY para DD/MM/YYYY para busca no site
        data_site = data_date.replace("-", "/")
        anexo = data_anexo
        
        return nome, data_site, anexo, file_path
        
    def scroll_table_to_load_all(self):
        """Faz scroll na tabela para carregar todos os elementos."""
        try:
            # Encontra o container da tabela ou a própria tabela
            table = self.driver.find_element(By.ID, "tabelaListagem")
            
            # Tenta encontrar o container pai que tem o scrollbar (geralmente um div ou tbody)
            container = None
            try:
                # Primeiro tenta encontrar um container com scrollbar
                container = table.find_element(By.XPATH, "./ancestor::div[contains(@style, 'overflow')]")
            except:
                try:
                    # Se não encontrar, tenta o tbody
                    container = table.find_element(By.TAG_NAME, "tbody")
                except:
                    # Se não encontrar, usa a própria tabela
                    container = table
            
            # Obtém a altura inicial
            last_height = self.driver.execute_script("return arguments[0].scrollHeight", container)
            scroll_attempts = 0
            max_scroll_attempts = 20  # Limite de tentativas para evitar loop infinito
            
            print("  → Carregando toda a tabela (fazendo scroll)...")
            
            while scroll_attempts < max_scroll_attempts:
                # Faz scroll até o final do container
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight;",
                    container
                )
                sleep(0.5)  # Aguarda elementos carregarem
                
                # Verifica nova altura
                new_height = self.driver.execute_script("return arguments[0].scrollHeight", container)
                
                # Se a altura não mudou, significa que chegou ao final
                if new_height == last_height:
                    break
                
                last_height = new_height
                scroll_attempts += 1
            
            # Faz scroll de volta para o topo para facilitar a visualização
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            sleep(0.5)
            
            print(f"  ✓ Tabela totalmente carregada ({scroll_attempts} tentativas de scroll)")
            return True
            
        except Exception as e:
            print(f"  ⚠ Aviso ao fazer scroll na tabela: {e}")
            return False
    
    def find_and_click_user(self, nome, data):
        """Encontra e clica no usuário correto na tabela."""
        print(f"\n  → Procurando: {nome} ({data})")
        
        # Primeiro, faz scroll para carregar toda a tabela
        self.scroll_table_to_load_all()
        
        # XPath para encontrar a linha que tem o nome e a data
        # No site: coluna 3 (td[3]) tem a data, coluna 4 (td[4]) tem o nome
        row_xpath = (
            f"//table[@id='tabelaListagem']//tr["
            f"  td[4]//a[normalize-space()='{nome}'] and "
            f"  td[3][normalize-space()='{data}']"
            f"]"
        )
        

        try:
            # Tenta encontrar o elemento
            row = self.driver.find_element(By.XPATH, row_xpath)
            link = row.find_element(By.XPATH, "td[4]//a")
            
            # Faz scroll até o elemento para garantir que está visível
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            sleep(0.5)
            
            try:
                self.wait.until(EC.element_to_be_clickable(link)).click()
            except Exception:
                # Se houver overlay, força clique via JS
                self.driver.execute_script("arguments[0].click();", link)
            
            print(f"  ✓ Usuário encontrado e clicado")
            sleep(3)
            return True
            
        except Exception as e:
            print(f"  ✗ Erro ao encontrar usuário: {e}")
            return False
            
    def click_anexo_button(self, anexo):
        """Clica no botão de anexo correto (RX ou GTO)."""
        print(f"  → Clicando em anexo: {anexo}")
        
        rx_button = self.driver.find_element(By.ID, "AnexarRx1")
        gto_button = self.driver.find_element(By.ID, "AnexarRx2")
        
        if anexo == "GTO":
            gto_button.click()
        elif anexo == "RX":
            rx_button.click()
        else:
            raise ValueError(f"Tipo de anexo desconhecido: {anexo}")
        
        print(f"  ✓ Botão {anexo} clicado")
        
    def navigate_to_upload_page(self):
        """Navega para a página de upload (via iframe)."""
        print("  → Navegando para página de upload")
        
        # Encontra o iframe
        iframe = self.wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR, "iframe#TB_iframeContent, iframe[src*='imagens_lote_guias.php']"
        )))
        
        src = iframe.get_attribute("src")
        src_abs = urljoin(self.driver.current_url, src)
        
        # Navega direto para a URL do iframe
        self.driver.get(src_abs)
        print("  ✓ Navegação concluída")
        
    def upload_file(self, file_path, file_name):
        """Faz upload do arquivo usando requests."""
        print(f"  → Fazendo upload: {file_name}")
        
        # Extrai código de controle da URL
        url_atual = self.driver.current_url
        if "controle=" not in url_atual:
            print(f"  ✗ Erro: URL não contém parâmetro 'controle'")
            return False
        
        codigo = url_atual.split("controle=")[1].split("&")[0]
        
        # Obtém cookies do Selenium
        try:
            cookie = self.driver.get_cookie('PHPSESSID')
            if not cookie or 'value' not in cookie:
                print(f"  ✗ Erro: Cookie PHPSESSID não encontrado")
                return False
            phpsessid = cookie['value']
        except Exception as e:
            print(f"  ✗ Erro ao obter cookie: {e}")
            return False
        
        # Configura upload via requests
        url_upload = "https://www.sisoweb.coop.br/web/cooperados/upload.process.imagens.php"
        
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'x-requested-with': 'XMLHttpRequest',
            'referer': url_atual
        }
        
        cookies = {
            'PHPSESSID': phpsessid,
            'loginCooperados': '1'
        }
        
        data = {
            'controle': codigo,
            'baixada': 'f',
            'liberada': 'f',
            'pendente': 'f'
        }
        
        # Faz upload
        with open(file_path, 'rb') as f:
            files = {
                'files[]': (file_name, f, 'image/jpeg')
            }
            response = requests.post(
                url_upload, 
                data=data, 
                files=files, 
                headers=headers, 
                cookies=cookies, 
                timeout=120
            )
        
        if response.status_code == 200:
            print(f"  ✓ Upload realizado com sucesso")
            # Recarrega página
            sleep(2)
            self.driver.refresh()
            sleep(2)
            return True
        else:
            print(f"  ✗ Erro no upload: Status {response.status_code}")
            return False
            
    def complete_upload(self):
        """Completa o processo de upload selecionando procedimento e enviando."""
        print("  → Completando upload")
        
        # Seleciona a segunda opção do select de procedimento
        try:
            element = self.driver.find_element(By.XPATH, "//*[starts-with(@id, 'procedimento')]/option[2]")
            element.click()
            sleep(1)
            
            # Clica no botão de concluir
            button_concluir = self.driver.find_element(By.XPATH, '//*[@id="btnEnviarArquivoImagem"]')
            button_concluir.click()
            sleep(2)
            
            print("  ✓ Upload finalizado")
            return True
        except Exception as e:
            print(f"  ✗ Erro ao finalizar upload: {e}")
            return False
    
    def return_to_search_page(self):
        """Volta para a página de busca de guias."""
        print("  → Voltando para página de busca")
        self.driver.get("https://www.sisoweb.coop.br/web/cooperados/gerar.lote.php#")
        sleep(2)
        print("  ✓ Retornou para página de busca")
            
    def process_file(self, file_path):
        """Processa um arquivo completo: busca usuário e faz upload.
        
        Args:
            file_path: Caminho do arquivo a ser processado
        """
        try:
            nome, data, anexo, file_path = self.parse_filename(file_path)
            file_name = os.path.basename(file_path)
            
            print(f"\n{'='*60}")
            print(f"Processando: {file_name}")
            print(f"Nome: {nome}")
            print(f"Data: {data}")
            print(f"Tipo: {anexo}")
            
            # Volta para a página de busca e refaz a pesquisa
            self.return_to_search_page()
            sleep(2)
            self.prepare_search_filters()
            sleep(1)
            self.search_guides()
            
            # Busca e clica no usuário
            if not self.find_and_click_user(nome, data):
                print(f"  ✗ Não foi possível encontrar o usuário. Pulando arquivo.")
                return False
            
            # Clica no botão de anexo correto
            self.click_anexo_button(anexo)
            sleep(1)
            
            # Navega para página de upload
            self.navigate_to_upload_page()
            
            # Faz upload
            if not self.upload_file(file_path, file_name):
                return False
            
            # Completa o upload
            if not self.complete_upload():
                return False
            
            print(f"✓ Arquivo processado com sucesso!")
            return True
            
        except Exception as e:
            print(f"✗ Erro ao processar arquivo {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def process_all_files(self):
        """Processa todos os arquivos na pasta fotos/."""
        print("\n" + "="*60)
        print("INICIANDO PROCESSAMENTO DE FOTOS")
        print("="*60)
        
        # Lista arquivos de imagem
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        files = [
            f for f in FOTOS_DIR.glob("*")
            if f.is_file() and f.suffix.lower() in image_extensions
        ]
        
        if not files:
            print(f"Nenhum arquivo encontrado em {FOTOS_DIR}")
            return
        
        print(f"\nEncontrados {len(files)} arquivo(s) para processar\n")
        
        # Setup inicial
        self.setup_driver()
        
        try:
            # Login uma única vez
            self.login()
            
            # Navega para página de lote
            self.navigate_to_lote_generation()
            
            # Prepara filtros e busca inicial (para confirmar que está tudo OK)
            # self.prepare_search_filters()
            # self.search_guides()
            
            # Processa cada arquivo
            successful = 0
            failed = 0
            
            for i, file_path in enumerate(files, 1):
                print(f"\n[{i}/{len(files)}]")
                
                result = self.process_file(file_path)
                if result:
                    successful += 1
                else:
                    failed += 1
                
                # Pequena pausa entre arquivos
                if i < len(files):
                    sleep(2)
            
            # Resumo final
            print("\n" + "="*60)
            print("RESUMO DO PROCESSAMENTO")
            print("="*60)
            print(f"Total de arquivos: {len(files)}")
            print(f"Sucesso: {successful}")
            print(f"Falhas: {failed}")
            print("="*60)
            
        except KeyboardInterrupt:
            print("\n\nProcessamento interrompido pelo usuário.")
        except Exception as e:
            print(f"\nErro fatal: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\nMantendo o navegador aberto. Feche manualmente quando terminar.")
            # self.driver.quit()  # Descomente se quiser fechar automaticamente


def main():
    """Função principal."""
    processor = UniodontoProcessor()
    processor.process_all_files()


if __name__ == "__main__":
    main()
