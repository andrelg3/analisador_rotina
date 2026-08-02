import os
import asyncio
import streamlit as st
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

# Garante a instalação do browser headless no servidor
os.system("playwright install chromium")

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide"
)

st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Preencha as informações abaixo para que o sistema busque e analise as rotinas automaticamente.")

# -----------------------------------------------------------------------------
# BARRA LATERAL (APENAS A CHAVE DA API)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 Configurações da IA")
    gemini_api_key = st.text_input("Gemini API Key", type="password", help="Cole sua chave de API gerada no Google AI Studio")

# -----------------------------------------------------------------------------
# FORMULÁRIO PRINCIPAL NO CORPO DA PÁGINA (LAYOUT EM COLUNAS)
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
        vigencia_ref = st.selectbox("Vigência (Mês)", meses_opcoes)

empresa_sgde = "SED.MS"  # Domínio fixo interno

# -----------------------------------------------------------------------------
# FUNÇÃO DE AUTOMAÇÃO COM LOGS PASSO A PASSO
# -----------------------------------------------------------------------------
async def extrair_rotinas_sgde(usuario, senha, empresa, assessor, ano, vigencia, log_container):
    async with async_playwright() as p:
        log_container.write("🌐 1. Iniciando navegador em segundo plano...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            log_container.write("🔑 2. Acessando tela de Login do SGDE...")
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")

            log_container.write("✏️ 3. Preenchendo dados de autenticação...")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")

            log_container.write("⏳ 4. Aguardando processamento do Login...")
            await page.wait_for_load_state("networkidle")

            log_container.write("📍 5. Navegando para a URL de Análise de Rotina...")
            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            target_frame = page
            if len(page.frames) > 1:
                for frame in page.frames:
                    if "rotina" in frame.url or "progetec" in frame.url:
                        target_frame = frame
                        break

            log_container.write("🔍 6. Selecionando Assessor (Simular Acesso)...")
            simular_box = await target_frame.wait_for_selector("div[name='multiplicadorNte']", timeout=20000)
            await simular_box.click()
            await target_frame.fill(".select2-search input.select2-input:visible", assessor)
            await target_frame.click(f".select2-result-label:has-text('{assessor}')")

            log_container.write("📅 7. Selecionando Ano de Referência...")
            dropdowns = await target_frame.query_selector_all("a.select2-choice")
            if len(dropdowns) >= 4:
                await dropdowns[3].click()
                await target_frame.click(f".select2-result-label:has-text('{ano}')")

            log_container.write("🗓️ 8. Selecionando Vigência...")
            if len(dropdowns) >= 5:
                await dropdowns[4].click()
                await target_frame.click(f".select2-result-label:has-text('{vigencia}')")

            log_container.write("🚀 9. Clicando no botão Pesquisar...")
            await target_frame.click("input[ng-click='pesquisar()']")

            # Aguarda o indicador de carregamento do AngularJS sumir
            await page.wait_for_timeout(2000)
            await target_frame.wait_for_selector(".cg-busy-backdrop", state="hidden", timeout=20000)

            log_container.write("⏳ 10. Aguardando os resultados na UI-Grid...")
            # Espera o container de resultados do UI-Grid aparecer
            await target_frame.wait_for_selector(".ui-grid-row, div[ui-grid='dados.grid']", timeout=20000)

            linhas = await target_frame.query_selector_all(".ui-grid-row")
            log_container.write(f"📋 11. Sucesso! {len(linhas)} rotina(s) encontrada(s) no UI-Grid.")
            
            rotinas_encontradas = []
            for index in range(len(linhas)):
                # Busca o ícone/botão de ação dentro da linha do UI-Grid
                botoes_analisar = await target_frame.query_selector_all(".ui-grid-row i.fa-info-circle, .ui-grid-row button, .ui-grid-row a")
                
                if index < len(botoes_analisar):
                    log_container.write(f"📖 Extraindo conteúdo da rotina #{index + 1}...")
                    await botoes_analisar[index].click()
                    await target_frame.wait_for_selector("text=Detalhes da Rotina", timeout=15000)

                    dados_cabecalho = await target_frame.inner_text("div.dados-rotina, div:has-text('Servidor')")
                    texto_completo = await target_frame.inner_text("fieldset, .conteudo, table")

                    rotinas_encontradas.append({
                        "id": index + 1,
                        "cabecalho": dados_cabecalho,
                        "texto_rotina": texto_completo
                    })

                    # Botão para voltar à lista de resultados
                    await target_frame.click("text=/Analisar Rotina/i")
                    await target_frame.wait_for_selector(".ui-grid-row", timeout=10000)

            await browser.close()
            return rotinas_encontradas

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro durante a navegação no SGDE: {str(e)}")

# -----------------------------------------------------------------------------
# FUNÇÃO DE ANÁLISE COM GEMINI
# -----------------------------------------------------------------------------
def analisar_com_gemini(api_key, conteudo_rotina):
    client = genai.Client(api_key=api_key)
    
    system_instruction = """
    Você é um avaliador pedagógico especializado em analisar rotinas de PCPI.
    Analise o texto da rotina fornecido com base nas rubricas institucionais.
    Classifique os pontos fortes, fragilidades e emita uma sugestão de parecer estruturado.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Analise a seguinte rotina extraída do SGDE:\n\n{conteudo_rotina}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        )
    )
    return response.text

# -----------------------------------------------------------------------------
# EXECUÇÃO DO PROCESSO
# -----------------------------------------------------------------------------
st.write("---")
if st.button("🚀 Buscar Rotinas e Processar Análise", type="primary", use_container_width=True):
    if not gemini_api_key:
        st.error("Por favor, preencha a sua Gemini API Key na barra lateral esquerda.")
    elif not senha_sgde:
        st.error("Por favor, preencha a sua senha do SGDE.")
    else:
        status_box = st.status("Processando busca e análise...", expanded=True)
        try:
            rotinas = asyncio.run(
                extrair_rotinas_sgde(
                    usuario_sgde, senha_sgde, empresa_sgde, 
                    assessor_nome, ano_ref, vigencia_ref, status_box
                )
            )
            
            status_box.update(label=f"Concluído! {len(rotinas)} rotina(s) extraída(s) com sucesso.", state="complete", expanded=False)

            for rotina in rotinas:
                st.markdown("---")
                st.subheader(f"📄 Análise da Rotina #{rotina['id']}")
                with st.spinner("Gerando parecer pedagógico com Gemini..."):
                    analise_ia = analisar_com_gemini(gemini_api_key, rotina["texto_rotina"])
                    st.markdown(analise_ia)

        except Exception as err:
            status_box.update(label="Falha durante o processo.", state="error", expanded=True)
            st.error(f"Detalhes do erro: {err}")
