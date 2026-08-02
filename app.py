import os
import re
import asyncio
import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
from playwright.async_api import async_playwright
import streamlit.components.v1 as components

os.system("playwright install chromium")

st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# LEITURA DA CHAVE VIA SECRETS
# -----------------------------------------------------------------------------
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

# -----------------------------------------------------------------------------
# ESTADOS DA SESSÃO
# -----------------------------------------------------------------------------
if "rotinas_carregadas" not in st.session_state:
    st.session_state.rotinas_carregadas = None

if "df_rotina_detalhada" not in st.session_state:
    st.session_state.df_rotina_detalhada = None

if "rotina_selecionada_info" not in st.session_state:
    st.session_state.rotina_selecionada_info = None

# -----------------------------------------------------------------------------
# BARRA LATERAL COMPACTA
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configurações")
    
    if gemini_api_key:
        st.caption("✅ **IA:** API Key Ativa (Secrets)")
    else:
        st.caption("❌ **IA:** API Key Ausente nos Secrets")

    st.write("")

    st.subheader("🔐 Acesso SGDE")
    col_usr, col_pwd = st.columns(2)
    with col_usr:
        usuario_sgde = st.text_input("Usuário", value="agoulart")
    with col_pwd:
        senha_sgde = st.text_input("Senha", type="password")

    st.subheader("🔍 Filtros")
    assessor_nome = st.text_input("Assessor", value="ANDRE LUIS GOULART")
    
    col_mes, col_ano = st.columns(2)
    with col_mes:
        meses_opcoes = [
            "02 - FEVEREIRO", "03 - MARÇO", "04 - ABRIL", 
            "05 - MAIO", "06 - JUNHO", "07 - JULHO", 
            "08 - AGOSTO", "09 - SETEMBRO", "10 - OUTUBRO", 
            "11 - NOVEMBRO", "12 - DEZEMBRO"
        ]
        vigencia_ref = st.selectbox("Mês", meses_opcoes, index=4)
    with col_ano:
        ano_ref = st.selectbox("Ano", ["2026", "2025"])

    st.write("")
    btn_buscar = st.button("🔍 Buscar Rotinas no SGDE", type="primary", use_container_width=True)

empresa_sgde = "SED.MS"

# -----------------------------------------------------------------------------
# CABEÇALHO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Selecione os filtros no menu lateral para buscar as rotinas e clique em **Ver Rotina** para visualizar os detalhes.")

# -----------------------------------------------------------------------------
# FUNÇÃO PARA EXTRAIR E FORMATAR O TEXTO BRUTO EM DATAFRAME
# -----------------------------------------------------------------------------
def processar_texto_rotina(texto_bruto):
    # Regex para capturar padrões de data (DD/MM/AAAA) seguidos do turno e da descrição
    # Padrão: 01/07/2026 \t Matutino \t Descrição...
    padrao = r'(\d{2}/\d{2}/\d{4})\s+(Matutino|Vespertino|Noturno)\s+(.*?)(?=\d{2}/\d{2}/\d{4}\s+|\bParecer\b|$)'
    
    # Recorta o bloco entre "DESCRIÇÃO DA ROTINA" e "Parecer"
    inicio = texto_bruto.find("DESCRIÇÃO DA ROTINA")
    fim = texto_bruto.find("Parecer", inicio if inicio != -1 else 0)
    
    bloco_util = texto_bruto[inicio:fim] if inicio != -1 and fim != -1 else texto_bruto
    
    registros = []
    matches = re.findall(padrao, bloco_util, re.DOTALL)
    
    for data, turno, descricao in matches:
        # Limpa espaços e quebras de linha desnecessárias
        desc_limpa = " ".join(descricao.split())
        registros.append({
            "Data": data,
            "Turno": turno,
            "Descrição da Rotina": desc_limpa
        })
        
    return pd.DataFrame(registros)

# -----------------------------------------------------------------------------
# ETAPA 1: APENAS LISTAR AS ROTINAS
# -----------------------------------------------------------------------------
async def buscar_lista_rotinas(usuario, senha, empresa, assessor, ano, vigencia, log_container):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            log_container.write("🔑 Efetuando login no SGDE...")
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")
            await page.wait_for_load_state("networkidle")

            log_container.write("📍 Acessando tela de Análise de Rotina...")
            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            target_frame = page
            if len(page.frames) > 1:
                for frame in page.frames:
                    if "rotina" in frame.url or "progetec" in frame.url:
                        target_frame = frame
                        break

            log_container.write("🔍 Aplicando filtros de busca...")
            simular_box = await target_frame.wait_for_selector("div[name='multiplicadorNte']", timeout=20000)
            await simular_box.click()
            await target_frame.fill(".select2-search input.select2-input:visible", assessor)
            await target_frame.click(f".select2-result-label:has-text('{assessor}')")

            dropdowns = await target_frame.query_selector_all("a.select2-choice")
            if len(dropdowns) >= 4:
                await dropdowns[3].click()
                await target_frame.click(f".select2-result-label:has-text('{ano}')")

            if len(dropdowns) >= 5:
                await dropdowns[4].click()
                await target_frame.click(f".select2-result-label:has-text('{vigencia}')")

            log_container.write("🚀 Pesquisando rotinas...")
            await target_frame.click("input[ng-click='pesquisar()']")

            await page.wait_for_timeout(2000)
            await target_frame.wait_for_selector(".cg-busy-backdrop", state="hidden", timeout=20000)
            await target_frame.wait_for_selector(".ui-grid-row", timeout=20000)

            linhas = await target_frame.query_selector_all(".ui-grid-row")
            log_container.write(f"📋 Mapeando {len(linhas)} rotina(s)...")

            lista_rotinas = []
            for index, linha in enumerate(linhas):
                texto_linha = await linha.inner_text()
                colunas = [col.strip() for col in texto_linha.split('\n') if col.strip()]
                
                escola = colunas[1] if len(colunas) > 1 else "Escola N/I"
                servidor = colunas[2] if len(colunas) > 2 else f"Servidor #{index+1}"
                situacao = colunas[5] if len(colunas) > 5 else "N/I"

                lista_rotinas.append({
                    "Index": index,
                    "Unidade Escolar": escola,
                    "Servidor": servidor,
                    "Situação": situacao
                })

            await browser.close()
            return lista_rotinas

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro ao listar rotinas: {str(e)}")

# -----------------------------------------------------------------------------
# ETAPA 2: EXTRAIR A ROTINA SELECIONADA
# -----------------------------------------------------------------------------
async def extrair_rotina_especifica(usuario, senha, empresa, assessor, ano, vigencia, index_escolhido, log_container):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            log_container.write("🔑 Acessando SGDE...")
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")
            await page.wait_for_load_state("networkidle")

            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            target_frame = page
            if len(page.frames) > 1:
                for frame in page.frames:
                    if "rotina" in frame.url or "progetec" in frame.url:
                        target_frame = frame
                        break

            simular_box = await target_frame.wait_for_selector("div[name='multiplicadorNte']", timeout=20000)
            await simular_box.click()
            await target_frame.fill(".select2-search input.select2-input:visible", assessor)
            await target_frame.click(f".select2-result-label:has-text('{assessor}')")

            dropdowns = await target_frame.query_selector_all("a.select2-choice")
            if len(dropdowns) >= 4:
                await dropdowns[3].click()
                await target_frame.click(f".select2-result-label:has-text('{ano}')")

            if len(dropdowns) >= 5:
                await dropdowns[4].click()
                await target_frame.click(f".select2-result-label:has-text('{vigencia}')")

            await target_frame.click("input[ng-click='pesquisar()']")
            await page.wait_for_timeout(2000)
            await target_frame.wait_for_selector(".cg-busy-backdrop", state="hidden", timeout=20000)
            await target_frame.wait_for_selector(".ui-grid-row", timeout=20000)

            linhas = await target_frame.query_selector_all(".ui-grid-row")
            
            if index_escolhido < len(linhas):
                log_container.write(f"🎯 Abrindo rotina #{index_escolhido + 1}...")
                linha_alvo = linhas[index_escolhido]
                
                botao_analisar = await linha_alvo.query_selector("input[title='Analisar'], input[ng-click*='analisar']")
                if botao_analisar:
                    await botao_analisar.click()
                else:
                    await linha_alvo.click()

                log_container.write("⏳ Extraindo e estruturando relatórios...")
                await page.wait_for_timeout(4000)

                try:
                    await target_frame.wait_for_selector(".cg-busy-backdrop", state="hidden", timeout=10000)
                except:
                    pass

                texto_bruto = await target_frame.inner_text("body")
                await browser.close()
                return texto_bruto

            await browser.close()
            raise Exception("Linha da rotina não encontrada.")

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro ao extrair detalhes: {str(e)}")

# -----------------------------------------------------------------------------
# AÇÃO DO BOTÃO DA SIDEBAR
# -----------------------------------------------------------------------------
if btn_buscar:
    if not senha_sgde:
        st.error("Por favor, informe a senha do SGDE na barra lateral.")
    else:
        st.session_state.df_rotina_detalhada = None
        st.session_state.rotina_selecionada_info = None
        status_box = st.status("Pesquisando rotinas...", expanded=True)
        try:
            lista = asyncio.run(
                buscar_lista_rotinas(
                    usuario_sgde, senha_sgde, empresa_sgde, 
                    assessor_nome, ano_ref, vigencia_ref, status_box
                )
            )
            st.session_state.rotinas_carregadas = lista
            status_box.update(label=f"Sucesso! {len(lista)} rotina(s) encontrada(s).", state="complete", expanded=False)
        except Exception as err:
            status_box.update(label="Falha na busca.", state="error", expanded=True)
            st.error(f"Erro: {err}")

# -----------------------------------------------------------------------------
# EXIBIÇÃO DA TABELA COM BOTÕES POR LINHA
# -----------------------------------------------------------------------------
if st.session_state.rotinas_carregadas:
    st.markdown("---")
    st.subheader(f"📋 Rotinas Encontradas ({len(st.session_state.rotinas_carregadas)})")

    col_esc, col_serv, col_sit, col_act = st.columns([3, 3, 2, 2])
    col_esc.markdown("**Unidade Escolar**")
    col_serv.markdown("**Servidor / PROGETEC**")
    col_sit.markdown("**Situação**")
    col_act.markdown("**Ação**")

    st.markdown("---")

    for rotina in st.session_state.rotinas_carregadas:
        c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
        c1.write(rotina["Unidade Escolar"])
        c2.write(rotina["Servidor"])
        c3.write(rotina["Situação"])
        
        if c4.button(f"👁️ Ver Rotina", key=f"btn_{rotina['Index']}"):
            st.session_state.rotina_selecionada_info = rotina
            status_extracao = st.status(f"Carregando detalhes de {rotina['Servidor']}...", expanded=True)
            try:
                texto_bruto = asyncio.run(
                    extrair_rotina_especifica(
                        usuario_sgde, senha_sgde, empresa_sgde,
                        assessor_nome, ano_ref, vigencia_ref, rotina["Index"], status_extracao
                    )
                )
                # Processa e converte para Tabela Nítida
                df_formatado = processar_texto_rotina(texto_bruto)
                st.session_state.df_rotina_detalhada = df_formatado
                
                status_extracao.update(label="Rotina carregada e formatada com sucesso!", state="complete", expanded=False)
                st.rerun()
            except Exception as err:
                status_extracao.update(label="Erro ao carregar rotina.", state="error", expanded=True)
                st.error(f"Erro: {err}")

# -----------------------------------------------------------------------------
# AREA DE EXIBIÇÃO DA ROTINA DETALHADA (COM QUEBRA AUTOMÁTICA DE LINHA E LARGURAS AJUSTADAS)
# -----------------------------------------------------------------------------
if st.session_state.df_rotina_detalhada is not None and st.session_state.rotina_selecionada_info:
    info = st.session_state.rotina_selecionada_info
    df = st.session_state.df_rotina_detalhada

    st.markdown("---")
    st.markdown("<div id='secao-detalhamento'></div>", unsafe_allow_html=True)
    
    st.header(f"📄 Detalhamento da Rotina: {info['Servidor']}")
    st.caption(f"Unidade Escolar: {info['Unidade Escolar']} | Situação: {info['Situação']}")

    if not df.empty:
        # Estilização CSS personalizada para permitir Text Wrap e colunas proporcionais
        estilo_tabela = """
        <style>
            .tabela-rotina {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
                font-family: Arial, sans-serif;
            }
            .tabela-rotina th {
                background-color: #f0f2f6;
                color: #31333F;
                text-align: left;
                padding: 12px;
                border-bottom: 2px solid #e6e8eb;
                font-weight: bold;
            }
            .tabela-rotina td {
                padding: 12px;
                border-bottom: 1px solid #e6e8eb;
                vertical-align: top;
                line-height: 1.5;
                font-size: 14px;
            }
            .col-data {
                width: 110px;
                white-space: nowrap;
                font-weight: 500;
            }
            .col-turno {
                width: 110px;
                white-space: nowrap;
            }
            .col-desc {
                word-wrap: break-word;
                white-space: normal;
            }
            .tabela-rotina tr:hover {
                background-color: #f9f9f9;
            }
        </style>
        """

        # Construção da tabela em HTML puro
        html_tabela = estilo_tabela + '<table class="tabela-rotina">'
        html_tabela += """
            <thead>
                <tr>
                    <th class="col-data">Data</th>
                    <th class="col-turno">Turno</th>
                    <th class="col-desc">Descrição da Rotina</th>
                </tr>
            </thead>
            <tbody>
        """

        for _, row in df.iterrows():
            html_tabela += f"""
                <tr>
                    <td class="col-data">{row['Data']}</td>
                    <td class="col-turno">{row['Turno']}</td>
                    <td class="col-desc">{row['Descrição da Rotina']}</td>
                </tr>
            """

        html_tabela += '</tbody></table>'

        # Renderiza a tabela HTML nítida e responsiva
        st.markdown(html_tabela, unsafe_allow_html=True)

    else:
        st.warning("Não foram encontradas linhas de rotina válidas no texto capturado.")

    st.write("")
    st.info("💡 **Próximo passo:** Na sequência, traremos a análise de IA ajustada para ler essa tabela e aplicar as rubricas do parecer!")

    # Auto-Scroll para a tabela
    components.html(
        """
        <script>
            var element = window.parent.document.getElementById('secao-detalhamento');
            if (element) {
                element.scrollIntoView({ behavior: 'smooth' });
            }
        </script>
        """,
        height=0,
    )
