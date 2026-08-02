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

st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Pesquise as rotinas, escolha qual PROGETEC/Escola deseja analisar e gere o parecer.")

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO AUTOMÁTICA DA API KEY (SECRETS OU MANUAL)
# -----------------------------------------------------------------------------
# Tenta pegar a chave diretamente dos Secrets do Streamlit
chave_salva = st.secrets.get("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("🔑 Configurações da IA")
    if chave_salva:
        st.success("✅ Gemini API Key configurada via Secrets!")
        gemini_api_key = st.text_input("Gemini API Key (Opcional - sobrescrever)", value=chave_salva, type="password")
    else:
        st.warning("⚠️ Nenhuma chave salva nos Secrets.")
        gemini_api_key = st.text_input("Gemini API Key", type="password")

# -----------------------------------------------------------------------------
# FORMULÁRIO PRINCIPAL
# -----------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("🔐 Credenciais SGDE")
    usuario_sgde = st.text_input("Usuário SGDE", value="agoulart")
    senha_sgde = st.text_input("Senha SGDE", type="password")

with col2:
    st.subheader("🔍 Filtros de Pesquisa")
    assessor_nome = st.text_input("Simular Acesso (Assessor)", value="ANDRE LUIS GOULART")
    
    col_ano, col_vigencia = st.columns(2)
    with col_ano:
        ano_ref = st.selectbox("Ano de Referência", ["2026", "2025"])
    with col_vigencia:
        meses_opcoes = [
            "02 - FEVEREIRO", "03 - MARÇO", "04 - ABRIL", 
            "05 - MAIO", "06 - JUNHO", "07 - JULHO", 
            "08 - AGOSTO", "09 - SETEMBRO", "10 - OUTUBRO", 
            "11 - NOVEMBRO", "12 - DEZEMBRO"
        ]
        vigencia_ref = st.selectbox("Vigência (Mês)", meses_opcoes, index=4)

empresa_sgde = "SED.MS"

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

            log_container.write("🔍 Aplicando filtros...")
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

            log_container.write("🚀 Pesquisando...")
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
# TELA PRINCIPAL
# -----------------------------------------------------------------------------
st.write("---")

if "rotinas_carregadas" not in st.session_state:
    st.session_state.rotinas_carregadas = None

if st.button("🔍 1. Buscar Lista de Rotinas", type="primary", use_container_width=True):
    if not senha_sgde:
        st.error("Por favor, informe a senha do SGDE.")
    else:
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

if st.session_state.rotinas_carregadas:
    st.success(f"Foram encontradas {len(st.session_state.rotinas_carregadas)} rotinas!")
    
    df_exibicao = pd.DataFrame(st.session_state.rotinas_carregadas)[["Unidade Escolar", "Servidor", "Situação"]]
    st.dataframe(df_exibicao, use_container_width=True)

    st.subheader("🎯 Selecione a Rotina que deseja analisar:")
    opcoes = {r["Rótulo"]: r["Index"] for r in st.session_state.rotinas_carregadas}
    rotina_escolhida = st.selectbox("Escolha o Servidor/Escola:", list(opcoes.keys()))

    if st.button("🚀 2. Processar Análise Pedagógica da Rotina Selecionada", use_container_width=True):
        if not gemini_api_key:
            st.error("Por favor, configure a Gemini API Key nos Secrets do Streamlit ou informe na barra lateral.")
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
                
                status_box_analise.update(label="Análise concluída!", state="complete", expanded=False)
                st.markdown("---")
                st.subheader(f"📄 Parecer: {rotina_escolhida}")
                st.markdown(parecer)

            except Exception as err:
                status_box_analise.update(label="Falha ao processar.", state="error", expanded=True)
                st.error(f"Erro: {err}")
