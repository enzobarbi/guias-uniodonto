import os
import time
import requests
import logging
from pathlib import Path
from urllib.parse import urljoin
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime

class UniodontoCrawler:
    def __init__(self):
        load_dotenv()
        self.cpf = str(os.getenv("CPF_TALUDE"))
        self.codigo = str(os.getenv("COD_UNIODONTO"))
        self.senha = str(os.getenv("PASSWORD"))
        self.diretorio_fotos = Path('/Users/enzobarbi/Development/Projects/guias-uniodonto/fotos')
        self.driver = None
        self.wait = None
        
        # Configurar logging
        self.configurar_logging()
        
        # Contadores para relatório final
        self.total_arquivos = 0
        self.processados_sucesso = 0
        self.processados_erro = 0
        self.arquivos_nao_encontrados = 0
        self.erros_detalhados = []
        
    def configurar_logging(self):
        """Configura o sistema de logging"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"uniodonto_crawler_{timestamp}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("Sistema de logging inicializado")
        
    def inicializar_driver(self):
        """Inicializa o driver do Chrome"""
        self.logger.info("Inicializando driver do Chrome...")
        try:
            opts = Options()
            opts.add_argument("--start-maximized")
            opts.add_experimental_option("detach", True)
            
            self.driver = webdriver.Chrome(options=opts)
            self.wait = WebDriverWait(self.driver, 10)
            self.logger.info("Driver inicializado com sucesso")
            return True
        except Exception as e:
            self.logger.error(f"Erro ao inicializar driver: {e}")
            return False
        
    def fazer_login(self):
        """Realiza o login no sistema"""
        self.logger.info("Iniciando processo de login...")
        try:
            self.driver.get("https://www.uniodontosc.coop.br/cooperados/index.php")
            time.sleep(3)
            
            # Preencher campos
            self.logger.info("Preenchendo campos de login...")
            cpf_bar = self.driver.find_element(By.ID, 'campoCpf')
            cod_bar = self.driver.find_element(By.ID, 'campoCodigo')
            paswd_bar = self.driver.find_element(By.ID, 'campoSenha')
            
            # Digitar CPF com delay
            for numero in self.cpf:
                time.sleep(0.5)
                cpf_bar.send_keys(numero)
                
            cod_bar.send_keys(self.codigo)
            paswd_bar.send_keys(self.senha)
            time.sleep(3)
            
            # Fazer login
            login_button = self.driver.find_element(By.XPATH, '/html/body/div[2]/section/div[3]/div/div/div/div/form/div/div[4]/div/div/button')
            login_button.click()
            time.sleep(1.5)
            
            # Fechar popup
            close_add_button = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[1]/div/a')
            close_add_button.click()
            time.sleep(1.5)
            
            self.logger.info("Login realizado com sucesso")
            return True
            
        except Exception as e:
            self.logger.error(f"Erro durante login: {e}")
            return False
        
    def navegar_para_lote(self):
        """Navega para a página de geração de lote"""
        self.logger.info("Navegando para página de geração de lote...")
        try:
            production_button = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[3]/div[2]/div/div[4]/nav/ul/li[6]/a')
            production_button.click()
            time.sleep(0.5)
            
            lote_generation = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[3]/div[2]/div/div[4]/nav/ul/li[6]/ul/li[1]/a')
            lote_generation.click()
            time.sleep(2)
            
            self.logger.info("Configurando filtros de busca...")
            # Configurar filtros
            empresa_lote = self.driver.find_element(By.ID, 'empresaLote')
            empresa_lote.click()
            all_option = self.driver.find_element(By.XPATH, '/html/body/form/div/div/table/tbody/tr/td/table/tbody/tr[2]/td[3]/select/option[12]')
            all_option.click()
            
            month_year = self.driver.find_element(By.ID, 'mesAno')
            mesano = '102025'
            month_year.clear()
            month_year.click()
            time.sleep(1.5)
            
            for n in mesano:
                time.sleep(1)
                month_year.send_keys(int(n))
                
            search = self.driver.find_element(By.ID, 'pesquisarGuia')
            search.click()
            time.sleep(3)
            
            self.logger.info("Navegação para lote concluída")
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao navegar para lote: {e}")
            return False
        
    def obter_protocolos_arquivos(self):
        """Mapeia os protocolos disponíveis nos arquivos"""
        self.logger.info("Mapeando protocolos disponíveis nos arquivos...")
        try:
            arquivos = [arquivo.name for arquivo in self.diretorio_fotos.iterdir() if arquivo.is_file()]
            protocolos_disponiveis = {}
            
            for arquivo in arquivos:
                partes = arquivo.split(' - ')
                if len(partes) >= 2:
                    protocolo = partes[1].strip()
                    # Verificar se é arquivo GTO
                    tipo_anexo = partes[-1].split(".")[0] if len(partes) >= 5 else ""
                    if tipo_anexo == "GTO":
                        protocolos_disponiveis[protocolo] = arquivo
                        
            self.total_arquivos = len(protocolos_disponiveis)
            self.logger.info(f"Encontrados {self.total_arquivos} arquivos GTO para processamento")
            
            for protocolo, arquivo in protocolos_disponiveis.items():
                self.logger.info(f"  - Protocolo: {protocolo} | Arquivo: {arquivo}")
                
            return protocolos_disponiveis
            
        except Exception as e:
            self.logger.error(f"Erro ao mapear protocolos: {e}")
            return {}
        
    def obter_linhas_tabela(self):
        """Obtém as linhas da tabela de guias"""
        try:
            self.logger.info("Localizando tabela de guias...")
            tabela = self.driver.find_element(By.XPATH, '//*[@id="tabelaListagem"]')
            linhas = tabela.find_elements(By.XPATH, './/tbody/tr')
            self.logger.info(f"Encontradas {len(linhas)} linhas na tabela")
            return linhas
        except Exception as e:
            self.logger.error(f"Erro ao localizar tabela: {e}")
            return []
        
    def processar_guias(self):
        """Processa todas as guias disponíveis"""
        self.logger.info("Iniciando processamento das guias...")
        protocolos_disponiveis = self.obter_protocolos_arquivos()
        
        if not protocolos_disponiveis:
            self.logger.warning("Nenhum arquivo GTO encontrado para processamento")
            return
        
        protocolos_processados = set()
        
        while len(protocolos_processados) < len(protocolos_disponiveis):
            linhas = self.obter_linhas_tabela()
            
            if not linhas:
                self.logger.error("Não foi possível obter linhas da tabela")
                break
                
            protocolo_encontrado = False
            
            for linha in linhas:
                celulas = linha.find_elements(By.TAG_NAME, 'td')
                
                if len(celulas) >= 5:
                    protocolo = celulas[1].text.strip()
                    
                    # Verificar se protocolo está disponível e ainda não foi processado
                    if protocolo in protocolos_disponiveis and protocolo not in protocolos_processados:
                        self.logger.info(f"Processando protocolo: {protocolo}")
                        
                        beneficiario = celulas[3].text.strip()
                        data = celulas[2].text.strip()
                        valor = celulas[4].text.strip()
                        
                        self.logger.info(f"  Beneficiário: {beneficiario}")
                        self.logger.info(f"  Data: {data}")
                        self.logger.info(f"  Valor: {valor}")
                        
                        if self.processar_guia_individual(protocolo, protocolos_disponiveis[protocolo], celulas):
                            self.processados_sucesso += 1
                            self.logger.info(f"Guia {protocolo} processada com sucesso")
                            
                            # Deletar arquivo após sucesso
                            self.deletar_arquivo(protocolos_disponiveis[protocolo])
                        else:
                            self.processados_erro += 1
                            self.logger.error(f"Erro ao processar guia {protocolo}")
                            
                        protocolos_processados.add(protocolo)
                        protocolo_encontrado = True
                        
                        # Voltar para a lista
                        self.logger.info("Retornando para lista de guias...")
                        self.driver.get("https://www.sisoweb.coop.br/web/cooperados/gerar.lote.php")
                        time.sleep(12)  # Sleep maior conforme solicitado
                        break
                        
            if not protocolo_encontrado:
                self.logger.warning("Nenhum protocolo pendente encontrado na tabela atual")
                break
                
        # Verificar protocolos não encontrados
        for protocolo in protocolos_disponiveis:
            if protocolo not in protocolos_processados:
                self.arquivos_nao_encontrados += 1
                self.logger.warning(f"Protocolo {protocolo} não encontrado na tabela do sistema")
                
        self.logger.info("Processamento de guias concluído")
        
    def processar_guia_individual(self, protocolo, arquivo_nome, celulas):
        """Processa uma guia individual"""
        try:
            self.logger.info(f"Clicando na linha do protocolo {protocolo}")
            celulas[1].click()
            time.sleep(3)
            
            # Clicar no botão GTO
            self.logger.info("Clicando no botão de anexo GTO")
            gto_button = self.driver.find_element(By.ID, "AnexarRx2")
            gto_button.click()
            
            # Fazer upload
            if self.fazer_upload(protocolo, arquivo_nome):
                self.finalizar_upload()
                return True
            else:
                return False
                
        except Exception as e:
            erro_msg = f"Erro ao processar guia {protocolo}: {e}"
            self.logger.error(erro_msg)
            self.erros_detalhados.append(erro_msg)
            return False
            
    def fazer_upload(self, protocolo, arquivo_nome):
        """Realiza o upload do arquivo"""
        self.logger.info(f"Iniciando upload do arquivo: {arquivo_nome}")
        try:
            # Navegar para iframe
            iframe = self.wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR, "iframe#TB_iframeContent, iframe[src*='imagens_lote_guias.php']"
            )))
            
            src = iframe.get_attribute("src")
            src_abs = urljoin(self.driver.current_url, src)
            self.driver.get(src_abs)
            self.logger.info("Navegação para página de upload concluída")
            
            # Preparar upload via requests
            url_atual = self.driver.current_url
            
            if "controle=" not in url_atual:
                self.logger.error("URL não contém parâmetro 'controle'")
                return False
                
            codigo = url_atual.split("controle=")[1].split("&")[0]
            
            cookie = self.driver.get_cookie('PHPSESSID')
            if not cookie or 'value' not in cookie:
                self.logger.error("Cookie PHPSESSID não encontrado")
                return False
                
            phpsessid = cookie['value']
            arquivo_path = os.path.join(self.diretorio_fotos, arquivo_nome)
            
            # Fazer upload
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
            
            with open(arquivo_path, 'rb') as f:
                files = {
                    'files[]': (arquivo_nome, f, 'image/jpeg')
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
                self.logger.info("Upload realizado com sucesso")
                time.sleep(2)
                self.driver.refresh()
                time.sleep(2)
                return True
            else:
                self.logger.error(f"Erro no upload: Status {response.status_code}")
                return False
                
        except Exception as e:
            erro_msg = f"Erro durante upload do protocolo {protocolo}: {e}"
            self.logger.error(erro_msg)
            self.erros_detalhados.append(erro_msg)
            return False
            
    def finalizar_upload(self):
        """Finaliza o processo de upload"""
        try:
            self.logger.info("Finalizando processo de upload")
            element = self.driver.find_element(By.XPATH, "//*[starts-with(@id, 'procedimento')]/option[2]")
            element.click()
            
            button_concluir = self.driver.find_element(By.XPATH, '//*[@id="btnEnviarArquivoImagem"]')
            button_concluir.click()
            time.sleep(2)
            self.logger.info("Upload finalizado")
            
        except Exception as e:
            erro_msg = f"Erro ao finalizar upload: {e}"
            self.logger.error(erro_msg)
            self.erros_detalhados.append(erro_msg)
            
    def deletar_arquivo(self, arquivo_nome):
        """Deleta o arquivo após processamento bem-sucedido"""
        try:
            arquivo_path = os.path.join(self.diretorio_fotos, arquivo_nome)
            os.remove(arquivo_path)
            self.logger.info(f"Arquivo deletado: {arquivo_nome}")
        except Exception as e:
            self.logger.warning(f"Não foi possível deletar arquivo {arquivo_nome}: {e}")
            
    def gerar_relatorio_final(self):
        """Gera relatório final do processamento"""
        self.logger.info("=" * 60)
        self.logger.info("RELATÓRIO FINAL DE PROCESSAMENTO")
        self.logger.info("=" * 60)
        self.logger.info(f"Total de arquivos GTO encontrados: {self.total_arquivos}")
        self.logger.info(f"Processados com sucesso: {self.processados_sucesso}")
        self.logger.info(f"Processados com erro: {self.processados_erro}")
        self.logger.info(f"Não encontrados na tabela: {self.arquivos_nao_encontrados}")
        self.logger.info(f"Taxa de sucesso: {(self.processados_sucesso/self.total_arquivos*100):.1f}%" if self.total_arquivos > 0 else "N/A")
        
        if self.erros_detalhados:
            self.logger.info("\nERROS DETALHADOS:")
            for erro in self.erros_detalhados:
                self.logger.info(f"  - {erro}")
                
        self.logger.info("=" * 60)
        
    def executar(self):
        """Executa o processo completo"""
        self.logger.info("Iniciando execução do crawler Uniodonto")
        
        try:
            if not self.inicializar_driver():
                return
                
            if not self.fazer_login():
                return
                
            if not self.navegar_para_lote():
                return
                
            self.processar_guias()
            
        except Exception as e:
            self.logger.error(f"Erro crítico durante execução: {e}")
        finally:
            self.gerar_relatorio_final()
            if self.driver:
                input("Pressione Enter para fechar o navegador...")
                self.driver.quit()

if __name__ == "__main__":
    crawler = UniodontoCrawler()
    crawler.executar()