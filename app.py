import os
import re
import time
import asyncio
import requests
import pandas as pd
import streamlit as st
from playwright.async_api import async_playwright
import streamlit.components.v1 as components

# Instala o navegador Chromium para o Playwright
os.system("playwright install chromium")

st.set_page_config(
    page_title="Analisador de Rotina PCPI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS DO SGDE E SECRETS (GROQ)
# -----------------------------------------------------------------------------
empresa_sgde = "SED.MS"

# Leitura flexível da chave da Groq no Secrets do Streamlit
groq_api_key = st.secrets.get("GROQ_API_KEY") or st.secrets.get("groq_api_key") or ""

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
    
    # Validação do status da API Groq
    if groq_api_key and groq_api_key.startswith("gsk_"):
        st.caption("✅ **IA (Groq):** Chave Conectada")
    elif groq_api_key:
        st.caption("⚠️ **IA (Groq):** Chave Inválida (deve iniciar com gsk_)")
    else:
        st.caption("❌ **IA (Groq):** Chave Ausente nos Secrets")

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

import json

# -----------------------------------------------------------------------------
# ETAPA 3: ANALISAR COM IA (RETORNANDO JSON PARA O LAYOUT)
# -----------------------------------------------------------------------------
def executar_analise_ia(df_rotina, nome_servidor, eventos_mes):
    chave = st.secrets.get("GROQ_API_KEY") or st.secrets.get("groq_api_key") or ""

    if not chave:
        raise Exception("A chave da API da Groq não foi encontrada nos Secrets.")

    rotina_texto = df_rotina.to_string(index=False)

    prompt = f"""
Você é um especialista em análise pedagógica de rotinas de PCPI (Professor Coordenador de Tecnologias Inovadoras).
Análise a rotina do servidor/PROGETEC **{nome_servidor}** com base nos **Eventos do Mês** e nos **13 Critérios da Rubrica Oficial**.

### 📅 EVENTOS DO MÊS:
{eventos_mes if eventos_mes.strip() else "Nenhum evento específico informado para este mês."}

### 📋 ROTINA REGISTRADA:
{rotina_texto}

---
### 📏 OS 13 CRITÉRIOS:
1. Cumprimento da carga horária e do calendário escolar
1.1 Verificar se existe alternancia de períodos, matutino, vespertino e noturno, sendo aceitado no mínimo 2 diferentes por dia.
1.2 Identificar se os dias letivos descritos no campo "Eventos" são coerentes com os dias de rotinas. 
1.3 Identificar se as atividades de cada período são condizentes com as 4 horas por período, identificando ociosidade.
2. Execução das ações previstas no Plano de Ação do PCPI
2.1 Atividades referente ao plano de ação, como orientação a professores do projeto vinculados ao plano de ação.
3. Identificação das ações como parte do Plano de Ação
3.1 Escrita, estudo, formação, e qualquer ação vinculada ao projeto descrito como plano de ação do PCPI.
4. Apoio ao planejamento pedagógico dos professores
5. Promoção de práticas inovadoras
5.1 Inclusão da tecnologia, aplicativos, softweres, metodologias ativas, uso da STE, LDM, Lousa digital, robotica etc...
6. Uso pedagógico dos recursos e espaços
6.1 STE, computadores, tablets, projetores/datashow, laboratorios etc...
7. Participação em formações da COTED/SED
7.1 As formações são pontuais, geralmente descritas no campo eventos, podem ser 2 dias seguidos, 1 dia, ou meio período, se não houver no campo eventos, não apontar como algo que foi deixado de fazer.
8. Formação continuada e orientação aos docentes
8.1 As formações geralmente são descritas no campo de eventos, as orientações aos professores o PCPI pode fazer a qualquer momento quando necessário.
9. Gerenciamento e agendamento de recursos
9.1 Disponibilização de equipamentos e acesso a sala de tecnologia(STE) mediante a agendamento.
10. Projetos de iniciação científica e clubes
11. Participação em reuniões pedagógicas e conselhos
11.1 Quando houver...
12. Registro adequado das ações colaborativas
12.1 Ações colaborativas são aquelas que não se enquadram nas suas atribuições, observado até aqui do 1 a 12, porém quando precisar fazelas, descrever com clareza quem as solicitou e com qual proposito.
13. Clareza, objetividade e coerência dos registros

---
### 📤 SUA RESPOSTA DEVE SER EXCLUSIVAMENTE UM JSON VÁLIDO (SEM MARKDOWN DE CÓDIGO) NO SEGUINTE FORMATO:

{{
  "status_geral": "Pendente",
  "confronto_eventos": "Texto do confronto com os eventos do mês...",
  "aspectos": [
    {{
      "numero": 1,
      "titulo": "Cumprimento da carga horária e do calendário escolar",
      "status": "Pendente",
      "evidencia": "Não há registro do Sábado Letivo... Trazer trexo da rotina entre aspas quando necessário."
    }},
    ... (fazer isso do número 1 ao 13)
  ],
  "parecer_sugerido": "Olá, {nome_servidor}! Agradeço o envio dos seus registros... apontar brevemente pontos positivos, depois apontar os pontos 
  que necessitam alteração ou recomendação de melhoria para o proximo mes, finalizar com uma saldação "Atenciosamente, nome do assessor"
}}

O campo 'status' (tanto geral quanto dos aspectos) deve ser APENAS um destes valores exatos:
- "Adequado"
- "Com pendência"
- "Pendente"
"""

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=45)
        res_data = response.json()
        if response.status_code == 200:
            content = res_data['choices'][0]['message']['content']
            return json.loads(content)
        else:
            raise Exception(res_data.get('error', {}).get('message', 'Erro na IA'))
    except Exception as e:
        raise Exception(f"Erro ao processar análise em JSON: {str(e)}")

# -----------------------------------------------------------------------------
# EXECUÇÃO DO BOTÃO BUSCAR ROTINAS
# -----------------------------------------------------------------------------
if btn_buscar:
    log_status = st.status("Iniciando busca no SGDE...", expanded=True)
    try:
        resultado = asyncio.run(buscar_lista_rotinas(
            usuario_sgde, senha_sgde, empresa_sgde, 
            assessor_nome, ano_ref, vigencia_ref, log_status
        ))
        st.session_state.rotinas_carregadas = resultado
        log_status.update(label="Rotinas listadas com sucesso!", state="complete", expanded=False)
    except Exception as e:
        log_status.update(label="Erro durante a busca.", state="error", expanded=True)
        st.error(f"Erro: {str(e)}")

# -----------------------------------------------------------------------------
# EXIBIÇÃO DA LISTA DE ROTINAS (COM CONTADOR)
# -----------------------------------------------------------------------------
if st.session_state.rotinas_carregadas is not None:
    qtd_rotinas = len(st.session_state.rotinas_carregadas)
    st.subheader(f"📋 Rotinas Encontradas ({qtd_rotinas})")
    
    df_lista = pd.DataFrame(st.session_state.rotinas_carregadas)
    
    for idx, row in df_lista.iterrows():
        col_esc, col_serv, col_sit, col_btn = st.columns([3, 3, 2, 2])
        col_esc.write(f"**{row['Unidade Escolar']}**")
        col_serv.write(row["Servidor"])
        col_sit.write(row["Situação"])
        
        if col_btn.button("Ver Rotina", key=f"btn_rotina_{row['Index']}"):
            log_ext = st.status(f"Buscando detalhes da rotina de {row['Servidor']}...", expanded=True)
            try:
                texto_bruto = asyncio.run(extrair_rotina_especifica(
                    usuario_sgde, senha_sgde, empresa_sgde, 
                    assessor_nome, ano_ref, vigencia_ref, row["Index"], log_ext
                ))
                
                df_detalhado = processar_texto_rotina(texto_bruto)
                st.session_state.df_rotina_detalhada = df_detalhado
                
                # Salva como dicionário nativo Python para evitar o erro de 'bool' do Pandas
                st.session_state.rotina_selecionada_info = row.to_dict()
                st.session_state.resultado_ia = None  # Limpa análise anterior
                
                log_ext.update(label="Rotina extraída com sucesso!", state="complete", expanded=False)
                st.rerun()
            except Exception as e:
                log_ext.update(label="Erro ao extrair rotina.", state="error", expanded=True)
                st.error(f"Erro: {str(e)}")

# -----------------------------------------------------------------------------
# EXIBIÇÃO DA ROTINA DETALHADA E SESSÃO DE ANÁLISE COM IA
# -----------------------------------------------------------------------------
if st.session_state.df_rotina_detalhada is not None and st.session_state.rotina_selecionada_info is not None:
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
            status_ia = st.status("A IA (Groq - Llama 3.3) está analisando...", expanded=True)
            try:
                resultado = executar_analise_ia(df, info['Servidor'], eventos_input)
                st.session_state.resultado_ia = resultado
                status_ia.update(label="Análise realizada com sucesso!", state="complete", expanded=False)
                st.rerun()
            except Exception as e:
                status_ia.update(label="Erro durante o teste.", state="error", expanded=True)
                st.error(f"Erro: {str(e)}")

       # EXIBIÇÃO DO RESULTADO DA IA ESTILIZADO (IGUAL AOS PRINTS)
        if st.session_state.resultado_ia:
            res = st.session_state.resultado_ia
            
            st.markdown("---")
            
            # CSS Personalizado para badges, cards e caixas
            st.markdown("""
                <style>
                    .card-box {
                        background-color: #f8f9fa;
                        border: 1px solid #e9ecef;
                        border-radius: 12px;
                        padding: 16px 20px;
                        margin-bottom: 16px;
                    }
                    .card-eventos {
                        background-color: #fffdf5;
                        border: 1px solid #fce8b3;
                        border-radius: 12px;
                        padding: 18px;
                        margin-bottom: 20px;
                        color: #795548;
                    }
                    .badge-pendente {
                        background-color: #ffebee;
                        color: #c62828;
                        padding: 4px 12px;
                        border-radius: 16px;
                        font-weight: bold;
                        font-size: 0.85rem;
                        border: 1px solid #ffcdd2;
                    }
                    .badge-compendencia {
                        background-color: #fff8e1;
                        color: #b78103;
                        padding: 4px 12px;
                        border-radius: 16px;
                        font-weight: bold;
                        font-size: 0.85rem;
                        border: 1px solid #ffe082;
                    }
                    .badge-adequado {
                        background-color: #e8f5e9;
                        color: #2e7d32;
                        padding: 4px 12px;
                        border-radius: 16px;
                        font-weight: bold;
                        font-size: 0.85rem;
                        border: 1px solid #c8e6c9;
                    }
                </style>
            """, unsafe_allow_html=True)

            # 1. CABEÇALHO DO CARD SUPERIOR
            status_geral = res.get("status_geral", "Pendente")
            badge_class = "badge-pendente" if "Pendente" in status_geral else ("badge-compendencia" if "Pendência" in status_geral else "badge-adequado")
            
            st.caption("ANÁLISE CONCLUÍDA")
            col_t1, col_t2 = st.columns([3, 1])
            with col_t1:
                st.markdown(f"### **{info['Servidor']}**")
            with col_t2:
                st.markdown(f"<div style='text-align: right;'><span class='{badge_class}'>● {status_geral}</span></div>", unsafe_allow_html=True)
            
            st.caption(f"📄 {info['Servidor'].lower().replace(' ', '_')}_rotina.pdf")
            st.write("")

            # 2. CONFRONTO DE EVENTOS DO MÊS
            st.markdown(f"""
                <div class='card-eventos'>
                    <h5 style='color: #a0522d; margin-top:0;'>📅 CONFRONTO DE EVENTOS DO MÊS</h5>
                    <p style='margin-bottom:0;'>{res.get('confronto_eventos', '')}</p>
                </div>
            """, unsafe_allow_html=True)

            # 3. AVALIAÇÃO DOS 13 ASPECTOS TÉCNICOS
            st.subheader("✔️ Avaliação dos 13 Aspectos Técnicos")
            st.caption("Clique nos itens abaixo para ver a justificativa e evidência de cada um:")

            for asp in res.get("aspectos", []):
                st_asp = asp.get("status", "Pendente")
                tag_icon = "🔴" if "Pendente" in st_asp else ("🟡" if "Pendência" in st_asp else "🟢")
                
                with st.expander(f"ASPECTO {asp.get('numero')} - {asp.get('titulo')}  |  {tag_icon} {st_asp}"):
                    st.markdown("**Análise e Evidência:**")
                    st.write(asp.get("evidencia", "Sem detalhes fornecidos."))

            st.write("")
            st.markdown("---")

            # 4. CARD DE SUGESTÃO DE STATUS
            if "Pendente" in status_geral:
                st.error(f"❌ **SUGESTÃO DE STATUS DO PARECER: {status_geral.upper()}**\n\nHá pelo menos um dos 13 aspectos considerado insuficiente ou em desacordo grave com as diretrizes do projeto.")
            elif "Pendência" in status_geral:
                st.warning(f"⚠️ **SUGESTÃO DE STATUS DO PARECER: {status_geral.upper()}**\n\nExistem aspectos pontuais que necessitam de ajustes do PCPI.")
            else:
                st.success(f"✅ **SUGESTÃO DE STATUS DO PARECER: {status_geral.upper()}**\n\nTodos os critérios foram atendidos de forma adequada.")

            st.write("")

            # 5. PARECER SUGERIDO PARA O SGDE
            st.subheader("📝 Sugestão de Parecer para o e-SGDE")
            parecer_texto = res.get("parecer_sugerido", "")
            
            st.text_area("Parecer Completo (pronto para copiar):", value=parecer_texto, height=260)
