import os
import re
import time
import asyncio
import streamlit as st
import pandas as pd
from playwright.async_api import async_playwright
import streamlit.components.v1 as components
import google.generativeai as genai

os.system("playwright install chromium")

st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS DO SGDE E SECRETS
# -----------------------------------------------------------------------------
empresa_sgde = "SED.MS"
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

if gemini_api_key:
    genai.configure(api_key=gemini_api_key)

# -----------------------------------------------------------------------------
# ESTADOS DA SESSÃO
# -----------------------------------------------------------------------------
if "rotinas_carregadas" not in st.session_state:
    st.session_state.rotinas_carregadas = None

if "df_rotina_detalhada" not in st.session_state:
    st.session_state.df_rotina_detalhada = None

if "rotina_selecionada_info" not in st.session_state:
    st.session_state.rotina_selecionada_info = None

if "sgde_cookies" not in st.session_state:
    st.session_state.sgde_cookies = None

if "sgde_login_time" not in st.session_state:
    st.session_state.sgde_login_time = 0

if "resultado_ia" not in st.session_state:
    st.session_state.resultado_ia = None

TEMPO_LIMITE_SESSAO = 15 * 60  # 15 minutos em segundos

def verificar_sessao_ativa():
    if st.session_state.sgde_cookies and st.session_state.sgde_login_time > 0:
        tempo_decorrido = time.time() - st.session_state.sgde_login_time
        if tempo_decorrido < TEMPO_LIMITE_SESSAO:
            tempo_restante = int(TEMPO_LIMITE_SESSAO - tempo_decorrido)
            minutos = tempo_restante // 60
            segundos = tempo_restante % 60
            return True, f"{minutos:02d}:{segundos:02d}"
    
    st.session_state.sgde_cookies = None
    st.session_state.sgde_login_time = 0
    return False, "00:00"

# -----------------------------------------------------------------------------
# BARRA LATERAL COMPACTA
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {
                width: 16.8rem !important;
                padding-top: 0rem !important;
            }
            [data-testid="stSidebar"] > div:first-child {
                width: 16.8rem !important;
            }
            [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
                gap: 0.35rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

    st.subheader("⚙️ Configurações")
    
    if gemini_api_key:
        st.caption("✅ **IA:** API Key Ativa")
    else:
        st.caption("❌ **IA:** API Key Ausente")

    sessao_valida, cronometro_str = verificar_sessao_ativa()
    if sessao_valida:
        st.caption(f"✅ **Login SGDE Ligado** | ⏰ {cronometro_str}")
    else:
        st.caption("❌ **Login SGDE Desligado** | ⏰ 00:00")

    st.markdown("---")

    col_usr, col_pwd = st.columns(2)
    with col_usr:
        usuario_sgde = st.text_input("Usuário", value="agoulart")
    with col_pwd:
        senha_sgde = st.text_input("Senha", type="password")

    assessor_nome = st.text_input("Assessor", value="ANDRE LUIS GOULART")
    
    col_mes, col_ano = st.columns([1.6, 1])
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

# -----------------------------------------------------------------------------
# CABEÇALHO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🤖 Analisador de Rotinas PCPI - SGDE")
st.write("Selecione os filtros no menu lateral para buscar as rotinas e clique em **Ver Rotina** para visualizar os detalhes.")

# -----------------------------------------------------------------------------
# FUNÇÃO PARA EXTRAIR E FORMATAR O TEXTO BRUTO EM DATAFRAME
# -----------------------------------------------------------------------------
def processar_texto_rotina(texto_bruto):
    padrao = r'(\d{2}/\d{2}/\d{4})\s+(Matutino|Vespertino|Noturno)\s+(.*?)(?=\d{2}/\d{2}/\d{4}\s+|\bParecer\b|$)'
    
    inicio = texto_bruto.find("DESCRIÇÃO DA ROTINA")
    fim = texto_bruto.find("Parecer", inicio if inicio != -1 else 0)
    
    bloco_util = texto_bruto[inicio:fim] if inicio != -1 and fim != -1 else texto_bruto
    
    registros = []
    matches = re.findall(padrao, bloco_util, re.DOTALL)
    
    for data, turno, descricao in matches:
        desc_limpa = " ".join(descricao.split())
        registros.append({
            "Data": data,
            "Turno": turno,
            "Descrição da Rotina": desc_limpa
        })
        
    return pd.DataFrame(registros)

# -----------------------------------------------------------------------------
# ETAPA 1: APENAS LISTAR AS ROTINAS (CÓDIGO ESTÁVEL)
# -----------------------------------------------------------------------------
async def buscar_lista_rotinas(usuario, senha, empresa, assessor, ano, vigencia, log_container):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        sessao_valida, _ = verificar_sessao_ativa()
        
        if sessao_valida and st.session_state.sgde_cookies:
            log_container.write("⚡ Usando sessão ativa do SGDE...")
            await context.add_cookies(st.session_state.sgde_cookies)
        else:
            if not senha:
                await browser.close()
                raise Exception("Sessão expirada ou inexistente. Por favor, digite a senha para efetuar um novo login.")
            
            log_container.write("🔑 Efetuando login no SGDE...")
            page = await context.new_page()
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")
            await page.wait_for_load_state("networkidle")

            st.session_state.sgde_cookies = await context.cookies()
            st.session_state.sgde_login_time = time.time()

        page = await context.new_page()

        try:
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
# ETAPA 2: EXTRAIR A ROTINA SELECIONADA (CÓDIGO ESTÁVEL)
# -----------------------------------------------------------------------------
async def extrair_rotina_especifica(usuario, senha, empresa, assessor, ano, vigencia, index_escolhido, log_container):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        sessao_valida, _ = verificar_sessao_ativa()

        if sessao_valida and st.session_state.sgde_cookies:
            log_container.write("⚡ Usando sessão ativa do SGDE...")
            await context.add_cookies(st.session_state.sgde_cookies)
        else:
            if not senha:
                await browser.close()
                raise Exception("Sessão expirada ou inexistente. Por favor, digite a senha para efetuar um novo login.")
            
            log_container.write("🔑 Efetuando login no SGDE...")
            page = await context.new_page()
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)
            await page.select_option("#ddlDominios", value=empresa)
            await page.click("#btnLogar")
            await page.wait_for_load_state("networkidle")

            st.session_state.sgde_cookies = await context.cookies()
            st.session_state.sgde_login_time = time.time()

        page = await context.new_page()

        try:
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
# ETAPA 3: ANALISAR COM IA (GEMINI COM FALLBACK DE MODELO)
# -----------------------------------------------------------------------------
def executar_analise_ia(df_rotina, nome_servidor, eventos_mes):
    if not gemini_api_key:
        raise Exception("A chave da API do Gemini não foi configurada nos Secrets.")

    rotina_texto = df_rotina.to_string(index=False)

    prompt = f"""
Você é um especialista em análise pedagógica de rotinas de PCPI (Professor Coordenador de Tecnologias Inovadoras).
Sua tarefa é analisar a rotina enviada do servidor/PROGETEC **{nome_servidor}** com base nos **Eventos do Mês** e nos **13 Critérios da Rubrica Oficial**.

### 📅 EVENTOS DO MÊS INFORMADOS PELO ASSESSOR:
{eventos_mes if eventos_mes.strip() else "Nenhum evento específico informado para este mês."}

### 📋 ROTINA REGISTRADA PELO PCPI:
{rotina_texto}

---

### 📏 REGRAS DE AVALIAÇÃO DOS 13 CRITÉRIOS (RUBRICA):
Avalie cada um dos 13 critérios a seguir escolhendO APENAS UMA destas 3 classificações: "Adequado", "Parcialmente Adequado" ou "Insuficiente".

1. **Cumprimento da carga horária**: Registros diários com turnos e dias letivos/não letivos coerentes com os eventos do mês.
2. **Execução das ações do Plano de Ação**: Registros indicam execução integral do planejado.
3. **Identificação da ação como Plano de Ação**: O PCPI explicita no texto "ação prevista no Plano de Ação".
4. **Apoio ao planejamento pedagógico**: Auxílio e orientação ao professor regente.
5. **Promoção de práticas inovadoras**: Incentivo a metodologias ativas, gamificação, projetos.
6. **Uso pedagógico das tecnologias**: Foco pedagógico no uso de STE, LDM, robótica (não apenas suporte técnico).
7. **Participação em formações da COTED/SED**: Registro de participação em oficinas/estudos da COTED.
8. **Formação/orientação aos docentes**: Momentos formativos e desdobramentos para os professores.
9. **Gerenciamento e agendamento de recursos e espaços**: Organização e controle de uso dos espaços/equipamentos.
10. **Projetos de iniciação científica e clubes**: Ações de fomento e incentivo a projetos/clubes.
11. **Participação em reuniões pedagógicas e conselhos**: Presença ativa em reuniões/conselhos.
12. **Registro de ações colaborativas**: Ações técnicas/operacionais com indicação de solicitação da direção/coordenação.
13. **Clareza dos registros**: Objetividade, coerência e detalhamento claro.

---

### 🎯 REGRA PARA O STATUS DO PARECER FINAL:
- Se houver **pelo menos 1 critério Insuficiente** -> Status Final = **Pendente**
- Se NÃO houver Insuficiente, mas houver **pelo menos 1 Parcialmente Adequado** -> Status Final = **Analisado com pendência**
- Se TODOS os critérios forem **Adequados** -> Status Final = **Analisado**

---

### ✍️ ESTRUTURA OBRIGATÓRIA DO PARECER FINAL:
1. **Saudação e Agradecimento**: Olá, {nome_servidor}! Parabéns pela entrega da sua rotina no prazo.
2. **Apontamentos Positivos**: Destaque pontos fortes da atuação registrada.
3. **Orientações / Recomendações**: Para cada critério avaliado como "Parcialmente Adequado" ou "Insuficiente", traga a orientação técnica em tom amigável e construtivo indicando o que precisa ser adjustedo/melhorado.
4. **Encorajamento Final**: Frase motivacional e de apoio.

---

### 📤 FORMATO DA RESPOSTA:
Por favor, responda estruturado exatamente assim:

STATUS: [Analisado / Analisado com pendência / Pendente]

---AVALIAÇÃO DA RUBRICA---
1. Cumprimento da carga horária: [Classificação] - [Breve justificativa]
2. Execução das ações do Plano de Ação: [Classificação] - [Breve justificativa]
3. Identificação da ação como Plano de Ação: [Classificação] - [Breve justificativa]
4. Apoio ao planejamento pedagógico: [Classificação] - [Breve justificativa]
5. Promoção de práticas inovadoras: [Classificação] - [Breve justificativa]
6. Uso pedagógico das tecnologias: [Classificação] - [Breve justificativa]
7. Participação em formações da COTED/SED: [Classificação] - [Breve justificativa]
8. Formação/orientação aos docentes: [Classificação] - [Breve justificativa]
9. Gerenciamento e agendamento de recursos e espaços: [Classificação] - [Breve justificativa]
10. Projetos de iniciação científica e clubes: [Classificação] - [Breve justificativa]
11. Participação em reuniões pedagógicas e conselhos: [Classificação] - [Breve justificativa]
12. Registro de ações colaborativas: [Classificação] - [Breve justificativa]
13. Clareza dos registros: [Classificação] - [Breve justificativa]

---PARECER SUGERIDO---
[Texto do parecer no formato exigido]
"""

    # Lista de nomes de modelos para tentar em ordem
    modelos_para_testar = [
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash-002",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]

    ultimo_erro = None
    for nome_modelo in modelos_para_testar:
        try:
            model = genai.GenerativeModel(nome_modelo)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            ultimo_erro = e
            continue

    raise Exception(f"Não foi possível conectar a nenhum modelo do Gemini. Último erro: {ultimo_erro}")

# -----------------------------------------------------------------------------
# AÇÃO DO BOTÃO DA SIDEBAR
# -----------------------------------------------------------------------------
if btn_buscar:
    sessao_ok, _ = verificar_sessao_ativa()
    if not sessao_ok and not senha_sgde:
        st.error("Sessão deslogada ou expirada. Por favor, informe a senha do SGDE na barra lateral para acessar.")
    else:
        st.session_state.df_rotina_detalhada = None
        st.session_state.rotina_selecionada_info = None
        st.session_state.resultado_ia = None
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
            st.rerun()
        except Exception as err:
            status_box.update(label="Falha na busca.", state="error", expanded=True)
            st.error(f"Erro: {err}")

# -----------------------------------------------------------------------------
# EXIBIÇÃO DA TABELA PRINCIPAL DE BUSCA
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
            st.session_state.resultado_ia = None
            status_extracao = st.status(f"Carregando detalhes de {rotina['Servidor']}...", expanded=True)
            try:
                texto_bruto = asyncio.run(
                    extrair_rotina_especifica(
                        usuario_sgde, senha_sgde, empresa_sgde,
                        assessor_nome, ano_ref, vigencia_ref, rotina["Index"], status_extracao
                    )
                )
                df_formatado = processar_texto_rotina(texto_bruto)
                st.session_state.df_rotina_detalhada = df_formatado
                
                status_extracao.update(label="Rotina carregada e formatada com sucesso!", state="complete", expanded=False)
                st.rerun()
            except Exception as err:
                status_extracao.update(label="Erro ao carregar rotina.", state="error", expanded=True)
                st.error(f"Erro: {err}")

# -----------------------------------------------------------------------------
# EXIBIÇÃO DA ROTINA DETALHADA E SESSÃO DE ANÁLISE COM IA
# -----------------------------------------------------------------------------
if st.session_state.df_rotina_detalhada is not None and st.session_state.rotina_selecionada_info:
    info = st.session_state.rotina_selecionada_info
    df = st.session_state.df_rotina_detalhada

    st.markdown("---")
    st.markdown("<div id='secao-detalhamento'></div>", unsafe_allow_html=True)
    
    st.header(f"📄 Detalhamento da Rotina: {info['Servidor']}")
    st.caption(f"Unidade Escolar: {info['Unidade Escolar']} | Situação: {info['Situação']}")

    if not df.empty:
        h1, h2, h3 = st.columns([1.2, 1.2, 7.6])
        h1.markdown("**Data**")
        h2.markdown("**Turno**")
        h3.markdown("**Descrição da Rotina**")
        st.divider()

        for idx, row in df.iterrows():
            c_data, c_turno, c_desc = st.columns([1.2, 1.2, 7.6])
            c_data.markdown(f"**{row['Data']}**")
            c_turno.write(row["Turno"])
            c_desc.write(row["Descrição da Rotina"])
            st.markdown("<hr style='margin: 8px 0; border: none; border-top: 1px solid #eee;'>", unsafe_allow_html=True)

        st.markdown("---")
        
        # CAMPO PARA EVENTOS DO MÊS E BOTÃO DA IA
        st.subheader("📅 Eventos e Calendário do Mês")
        st.caption("Cole abaixo os eventos específicos do mês (ex: dias letivos, reuniões, feriados, formações) para a IA considerar na avaliação:")
        
        eventos_input = st.text_area(
            "Eventos do Mês",
            value=" ",
            height=130
        )

        st.write("")
        btn_analisar_ia = st.button("🤖 Analisar com IA", type="primary", use_container_width=True)

        if btn_analisar_ia:
            status_ia = st.status("A IA está analisando a rotina e aplicando a rubrica...", expanded=True)
            try:
                resultado = executar_analise_ia(df, info['Servidor'], eventos_input)
                st.session_state.resultado_ia = resultado
                status_ia.update(label="Análise concluída com sucesso!", state="complete", expanded=False)
                st.rerun()
            except Exception as e:
                status_ia.update(label="Erro durante a análise.", state="error", expanded=True)
                st.error(f"Erro: {str(e)}")

        # EXIBIÇÃO DO RESULTADO DA IA
        if st.session_state.resultado_ia:
            st.markdown("---")
            st.subheader("📊 Resultado da Análise com IA")
            st.markdown(st.session_state.resultado_ia)

    else:
        st.warning("Não foram encontradas linhas de rotina válidas no texto capturado.")

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
