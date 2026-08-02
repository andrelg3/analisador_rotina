import os
import asyncio
import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

os.system("playwright install chromium")

st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide"
)

# -----------------------------------------------------------------------------
# LEITURA DA CHAVE VIA SECRETS
# -----------------------------------------------------------------------------
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

# -----------------------------------------------------------------------------
# BARRA LATERAL COMPACTA E OTIMIZADA
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configurações")
    
    # Status da IA compacto
    if gemini_api_key:
        st.caption("✅ **IA:** API Key Ativa (Secrets)")
    else:
        st.caption("❌ **IA:** API Key Ausente nos Secrets")

    st.write("") # Espaçamento leve

    # Credenciais SGDE em colunas (Lado a Lado)
    st.subheader("🔐 Acesso SGDE")
    col_usr, col_pwd = st.columns(2)
    with col_usr:
        usuario_sgde = st.text_input("Usuário", value="agoulart")
    with col_pwd:
        senha_sgde = st.text_input("Senha", type="password")

    # Filtros em formato enxuto
    st.subheader("🔍 Filtros")
    assessor_nome = st.text_input("Assessor", value="ANDRE LUIS GOULART")
    
    col_ano, col_mes = st.columns(2)
    with col_ano:
        ano_ref = st.selectbox("Ano", ["2026", "2025"])
    with col_mes:
        meses_opcoes = [
            "02 - FEVEREIRO", "03 - MARÇO", "04 - ABRIL", 
            "05 - MAIO", "06 - JUNHO", "07 - JULHO", 
            "08 - AGOSTO", "09 - SETEMBRO", "10 - OUTUBRO", 
            "11 - NOVEMBRO", "12 - DEZEMBRO"
        ]
        vigencia_ref = st.selectbox("Mês", meses_opcoes, index=4)

# -----------------------------------------------------------------------------
# CABEÇALHO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Pesquise as rotinas disponíveis no SGDE e selecione qual deseja analisar.")

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
                    "Situação": situacao,
                    "Rótulo": f"{servidor} - {escola} ({situacao})"
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
            log_container.write("🔑 Acessando SGDE para abrir a rotina...")
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
                log_container.write(f"📖 Clicando no ícone (i) da rotina #{index_escolhido + 1}...")
                linha_alvo = linhas[index_escolhido]
                
                icone_info = await linha_alvo.query_selector("i, a, .ui-grid-cell-contents")
                if icone_info:
                    await icone_info.click()
                else:
                    await linha_alvo.click()

                log_container.write("⏳ Extraindo dados do relatório...")
                await page.wait_for_timeout(3000)

                texto_completo = await target_frame.inner_text("body")

                await browser.close()
                return texto_completo

            await browser.close()
            raise Exception("Linha da rotina não encontrada.")

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro ao extrair detalhes: {str(e)}")

# -----------------------------------------------------------------------------
# FUNÇÃO GEMINI
# -----------------------------------------------------------------------------
def analisar_com_gemini(api_key, conteudo_rotina):
    client = genai.Client(api_key=api_key)
    system_instruction = """
    Você é um avaliador pedagógico especializado em analisar rotinas de PCPI do PROGETEC.
    Analise o texto fornecido e estruture o parecer em:
    1. Pontos Fortes
    2. Fragilidades / Pontos de Atenção
    3. Sugestão de Parecer Pedagógico Final
    """
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Analise a seguinte rotina do SGDE:\n\n{conteudo_rotina}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        )
    )
    return response.text

# -----------------------------------------------------------------------------
# CORPO DA APLICAÇÃO
# -----------------------------------------------------------------------------
st.markdown("---")

if "rotinas_carregadas" not in st.session_state:
    st.session_state.rotinas_carregadas = None

# Botão principal de Busca
if st.button("🔍 1. Buscar Lista de Rotinas no SGDE", type="primary", use_container_width=True):
    if not senha_sgde:
        st.error("Por favor, informe a senha do SGDE na barra lateral.")
    else:
        status_box = st.status("Pesquisando rotinas no SGDE...", expanded=True)
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

# Exibição dos Resultados e Seleção
if st.session_state.rotinas_carregadas:
    st.success(f"Foram encontradas {len(st.session_state.rotinas_carregadas)} rotinas!")
    
    df_exibicao = pd.DataFrame(st.session_state.rotinas_carregadas)[["Unidade Escolar", "Servidor", "Situação"]]
    st.dataframe(df_exibicao, use_container_width=True)

    st.markdown("---")
    st.subheader("🎯 Seleção de Rotina")
    opcoes = {r["Rótulo"]: r["Index"] for r in st.session_state.rotinas_carregadas}
    rotina_escolhida = st.selectbox("Escolha a rotina que deseja analisar:", list(opcoes.keys()))

    if st.button("🚀 2. Processar Análise Pedagógica da Rotina Selecionada", use_container_width=True):
        if not gemini_api_key:
            st.error("Gemini API Key não está configurada nos Secrets do Streamlit.")
        else:
            status_box_analise = st.status("Extraindo dados e gerando parecer...", expanded=True)
            try:
                index_alvo = opcoes[rotina_escolhida]
                texto_rotina = asyncio.run(
                    extrair_rotina_especifica(
                        usuario_sgde, senha_sgde, empresa_sgde,
                        assessor_nome, ano_ref, vigencia_ref, index_alvo, status_box_analise
                    )
                )
                status_box_analise.write("🧠 Gerando parecer pedagógico com Gemini...")
                parecer = analisar_com_gemini(gemini_api_key, texto_rotina)
                
                status_box_analise.update(label="Análise concluída com sucesso!", state="complete", expanded=False)
                st.markdown("---")
                st.subheader(f"📄 Parecer: {rotina_escolhida}")
                st.markdown(parecer)

            except Exception as err:
                status_box_analise.update(label="Falha ao processar a análise.", state="error", expanded=True)
                st.error(f"Erro: {err}")
