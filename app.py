import asyncio
import streamlit as st
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide"
)

st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Selecione os parâmetros abaixo para buscar e analisar as rotinas diretamente do SGDE.")

# -----------------------------------------------------------------------------
# BARRA LATERAL (ENTRADAS DE DADOS E CHAVE DE API)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 Autenticação e Configurações")
    
    # Chave de API do Gemini (AI Studio)
    gemini_api_key = st.text_input("Gemini API Key", type="password", help="Chave gerada no Google AI Studio")
    
    st.divider()
    st.subheader("Acesso ao SGDE")
    usuario_sgde = st.text_input("Usuário SGDE", value="agoulart")
    senha_sgde = st.text_input("Senha SGDE", type="password")
    empresa_sgde = st.selectbox("Empresa/Domínio", ["SED.MS"])
    
    st.divider()
    st.subheader("Filtros da Busca")
    assessor_nome = st.text_input("Simular Acesso (Assessor)", value="ANDRE LUIS GOULART")
    ano_ref = st.selectbox("Ano de Referência", ["2026", "2025"])
    
    meses_opcoes = [
        "02 - FEVEREIRO", "03 - MARÇO", "04 - ABRIL", 
        "05 - MAIO", "06 - JUNHO", "07 - JULHO", 
        "08 - AGOSTO", "09 - SETEMBRO", "10 - OUTUBRO", 
        "11 - NOVEMBRO", "12 - DEZEMBRO"
    ]
    vigencia_ref = st.selectbox("Vigência (Mês)", meses_opcoes)

# -----------------------------------------------------------------------------
# FUNÇÃO DE AUTOMAÇÃO COM PLAYWRIGHT (ROBÔ SGDE)
# -----------------------------------------------------------------------------
async def extrair_rotinas_sgde(usuario, senha, empresa, assessor, ano, vigencia):
    async with async_playwright() as p:
        # Lança o navegador em modo Headless (sem janela gráfica visível no servidor)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # 1. Login no SGDE
            await page.goto("https://www.sgde.ms.gov.br/")
            await page.fill("input[name='usuario']", usuario)
            await page.fill("input[name='senha']", senha)
            await page.select_option("select[name='empresa']", label=empresa)
            await page.click("button:has-text('Entrar')")

            # 2. Navegação até a rotina de análise
            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise")
            await page.wait_for_selector("text=ANALISAR ROTINA", timeout=15000)

            # 3. Aplicando os Filtros de Busca
            await page.click("label:has-text('Simular Acesso') + div")
            await page.click(f"text={assessor}")

            await page.click("label:has-text('Ano de Referência') + div")
            await page.click(f"text={ano}")

            await page.click("label:has-text('Vigência') + div")
            await page.click(f"text={vigencia}")

            # 4. Pesquisar e Extrair
            await page.click("button:has-text('Pesquisar')")
            await page.wait_for_selector("table", timeout=10000)

            linhas = await page.query_selector_all("tbody tr")
            rotinas_encontradas = []

            for index in range(len(linhas)):
                botoes_analisar = await page.query_selector_all("i.fa-info-circle, button:has-text('Analisar')")
                if index < len(botoes_analisar):
                    await botoes_analisar[index].click()
                    await page.wait_for_selector("text=Detalhes da Rotina", timeout=10000)

                    # Extrai os dados do servidor e a tabela de atividades
                    dados_cabecalho = await page.inner_text("div.dados-rotina, div:has-text('Servidor')")
                    tabela_detalhes = await page.inner_text("table")

                    rotinas_encontradas.append({
                        "id": index + 1,
                        "cabecalho": dados_cabecalho,
                        "texto_rotina": tabela_detalhes
                    })

                    # Voltar para a listagem
                    await page.click("text=ANALISAR ROTINA")
                    await page.wait_for_selector("table", timeout=10000)

            await browser.close()
            return rotinas_encontradas

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro durante a navegação no SGDE: {str(e)}")

# -----------------------------------------------------------------------------
# FUNÇÃO DE ANÁLISE COM GEMINI (AI STUDIO)
# -----------------------------------------------------------------------------
def analisar_com_gemini(api_key, conteudo_rotina):
    client = genai.Client(api_key=api_key)
    
    # AQUI VOCÊ INSERE SUAS RUBRICAS E INSTRUÇÕES DE SISTEMA EXISTENTES
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
# EXECUÇÃO DO FLUXO NA TELA PRINCIPAL
# -----------------------------------------------------------------------------
if st.button("🚀 Buscar Rotinas e Processar Análise", type="primary"):
    if not gemini_api_key:
        st.error("Por favor, preencha a sua Gemini API Key na barra lateral.")
    elif not senha_sgde:
        st.error("Por favor, preencha a sua senha do SGDE na barra lateral.")
    else:
        with st.status("Executando processo...", expanded=True) as status:
            try:
                st.write("1. Conectando ao SGDE e raspando as rotinas...")
                rotinas = asyncio.run(
                    extrair_rotinas_sgde(
                        usuario_sgde, senha_sgde, empresa_sgde, 
                        assessor_nome, ano_ref, vigencia_ref
                    )
                )
                
                st.write(f"2. Sucesso! {len(rotinas)} rotina(s) localizada(s).")
                st.write("3. Enviando conteúdo para análise no Gemini (AI Studio)...")

                for rotina in rotinas:
                    st.markdown(f"---")
                    st.subheader(f"📄 Rotina #{rotina['id']}")
                    
                    # Exibe a análise gerada pela IA
                    analise_ia = analisar_com_gemini(gemini_api_key, rotina["texto_rotina"])
                    st.markdown(analise_ia)

                status.update(label="Análise concluída com sucesso!", state="complete", expanded=False)

            except Exception as err:
                status.update(label="Ocorreu uma falha no processo.", state="error")
                st.error(f"Erro: {err}")
