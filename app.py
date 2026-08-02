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
st.write("Preencha os dados abaixo para extrair e analisar as rotinas em uma única navegação.")

# BARRA LATERAL
with st.sidebar:
    st.header("🔑 Configurações da IA")
    gemini_api_key = st.text_input("Gemini API Key", type="password")

# CORPO DA PÁGINA
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

# FUNÇÃO ÚNICA DE NAVEGAÇÃO E EXTRAÇÃO (UM ÚNICO LOGIN)
async def processar_sgde_completo(usuario, senha, empresa, assessor, ano, vigencia, log_container):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            log_container.write("🔑 1. Efetuando Login no SGDE (Sessão Única)...")
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")
            await page.wait_for_load_state("networkidle")

            log_container.write("📍 2. Acessando Análise de Rotina...")
            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            target_frame = page
            if len(page.frames) > 1:
                for frame in page.frames:
                    if "rotina" in frame.url or "progetec" in frame.url:
                        target_frame = frame
                        break

            log_container.write("🔍 3. Preenchendo filtros de busca...")
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

            log_container.write("🚀 4. Executando Pesquisa...")
            await target_frame.click("input[ng-click='pesquisar()']")

            await page.wait_for_timeout(2000)
            await target_frame.wait_for_selector(".cg-busy-backdrop", state="hidden", timeout=20000)
            await target_frame.wait_for_selector(".ui-grid-row", timeout=20000)

            linhas = await target_frame.query_selector_all(".ui-grid-row")
            log_container.write(f"📋 5. Encontradas {len(linhas)} rotina(s) na tabela.")

            rotinas_extraidas = []

            for index in range(len(linhas)):
                linhas_atuais = await target_frame.query_selector_all(".ui-grid-row")
                if index < len(linhas_atuais):
                    linha = linhas_atuais[index]
                    texto_linha = await linha.inner_text()
                    cols = [c.strip() for c in texto_linha.split('\n') if c.strip()]
                    
                    servidor = cols[2] if len(cols) > 2 else f"Servidor #{index+1}"
                    escola = cols[1] if len(cols) > 1 else "Escola N/I"

                    log_container.write(f"📖 6.{index+1} Abrindo detalhes de {servidor}...")
                    
                    icone_info = await linha.query_selector("i, a, .ui-grid-cell-contents")
                    if icone_info:
                        await icone_info.click()
                    else:
                        await linha.click()

                    await page.wait_for_timeout(2500)

                    # Extrai o conteúdo visível da rotina
                    conteudo = await target_frame.inner_text("body")

                    rotinas_extraidas.append({
                        "id": index + 1,
                        "servidor": servidor,
                        "escola": escola,
                        "conteudo": conteudo
                    })

                    # Botão para voltar ajustado sem usar regex problemático
                    voltar_btn = await target_frame.query_selector("button:has-text('Voltar'), button:has-text('Analisar Rotina'), .btn-warning, .btn-default")
                    if voltar_btn:
                        await voltar_btn.click()
                        await target_frame.wait_for_selector(".ui-grid-row", timeout=10000)

            await browser.close()
            return rotinas_extraidas

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro na automação do SGDE: {str(e)}")

# FUNÇÃO GEMINI AJUSTADA
def analisar_com_gemini(api_key, servidor, escola, conteudo_rotina):
    client = genai.Client(api_key=api_key)
    system_instruction = """
    Você é um avaliador pedagógico especializado em analisar rotinas de PCPI do PROGETEC.
    Faça uma análise rigorosa do texto da rotina fornecido com base nas diretrizes pedagógicas.
    Estruture a resposta com:
    1. Pontos Fortes
    2. Fragilidades / Pontos de Atenção
    3. Sugestão de Parecer Pedagógico
    """
    
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=f"Servidor: {servidor}\nEscola: {escola}\n\nTexto da Rotina:\n{conteudo_rotina}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        )
    )
    return response.text

# BOTÃO DE EXECUÇÃO
st.write("---")
if st.button("🚀 Buscar e Analisar Todas as Rotinas", type="primary", use_container_width=True):
    if not gemini_api_key:
        st.error("Por favor, preencha sua Gemini API Key na barra lateral.")
    elif not senha_sgde:
        st.error("Por favor, preencha sua senha do SGDE.")
    else:
        status_box = st.status("Processando fluxo contínuo no SGDE...", expanded=True)
        try:
            rotinas = asyncio.run(
                processar_sgde_completo(
                    usuario_sgde, senha_sgde, empresa_sgde,
                    assessor_nome, ano_ref, vigencia_ref, status_box
                )
            )

            status_box.update(label=f"Concluído com sucesso! {len(rotinas)} rotinas extraídas.", state="complete", expanded=False)

            st.success("Análises pedagógicas geradas:")
            for r in rotinas:
                with st.expander(f"📄 Parecer: {r['servidor']} - {r['escola']}", expanded=True):
                    with st.spinner(f"Gerando análise da IA para {r['servidor']}..."):
                        parecer = analisar_com_gemini(gemini_api_key, r["servidor"], r["escola"], r["conteudo"])
                        st.markdown(parecer)

        except Exception as err:
            status_box.update(label="Falha no processo.", state="error", expanded=True)
            st.error(f"Erro: {err}")
