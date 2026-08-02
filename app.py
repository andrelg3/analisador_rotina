async def extrair_rotinas_sgde(usuario, senha, empresa, assessor, ano, vigencia):
    async with async_playwright() as p:
        # Lança o navegador em modo Headless (sem janela gráfica visível no servidor)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # 1. Login no SGDE
            await page.goto("https://www.sgde.ms.gov.br/", wait_until="networkidle")

            # Preenche Usuário e Senha
            await page.fill("#txtUsuario", usuario)
            await page.fill("#txtSenha", senha)

            # Seleciona o Domínio SED.MS
            await page.select_option("#ddlDominios", value=empresa)

            # Clica no botão 'Entrar'
            await page.click("#btnLogar")

            # Aguarda o carregamento pós-login
            await page.wait_for_load_state("networkidle")

            # 2. Navegação até a página de rotina
            await page.goto("https://www.sgde.ms.gov.br/progetec/rotinaAnalise", wait_until="networkidle")
            
            # Aguarda o elemento do formulário carregar
            await page.wait_for_selector("div[name='multiplicadorNte']", timeout=15000)

            # 3. SELEÇÃO DO ASSESSOR (Simular Acesso)
            await page.click("div[name='multiplicadorNte'] a.select2-choice")
            await page.fill(".select2-search input.select2-input:visible", assessor)
            await page.click(f".select2-result-label:has-text('{assessor}')")

            # 4. SELEÇÃO DO ANO DE REFERÊNCIA
            dropdowns = await page.query_selector_all("a.select2-choice")
            if len(dropdowns) >= 4:
                await dropdowns[3].click()
                await page.click(f".select2-result-label:has-text('{ano}')")

            # 5. SELEÇÃO DA VIGÊNCIA (Mês)
            if len(dropdowns) >= 5:
                await dropdowns[4].click()
                await page.click(f".select2-result-label:has-text('{vigencia}')")

            # 6. BOTÃO PESQUISAR
            await page.click("input[ng-click='pesquisar()']")
            
            # Aguarda a tabela de resultados carregar
            await page.wait_for_selector("tbody tr", timeout=15000)

            # 7. CAPTURA E EXTRAÇÃO DAS ROTINAS ENCONTRADAS
            linhas = await page.query_selector_all("tbody tr")
            rotinas_encontradas = []

            for index in range(len(linhas)):
                # Localiza os ícones/botões de 'Analisar' na tabela de resultados
                botoes_analisar = await page.query_selector_all("i.fa-info-circle, button:has-text('Analisar'), a[title='Analisar']")
                
                if index < len(botoes_analisar):
                    await botoes_analisar[index].click()
                    await page.wait_for_selector("text=Detalhes da Rotina", timeout=10000)

                    # Extrai as informações da tela da rotina do PCPI
                    dados_cabecalho = await page.inner_text("div.dados-rotina, div:has-text('Servidor')")
                    tabela_detalhes = await page.inner_text("table")

                    rotinas_encontradas.append({
                        "id": index + 1,
                        "cabecalho": dados_cabecalho,
                        "texto_rotina": tabela_detalhes
                    })

                    # Voltar para a listagem para analisar o próximo PCPI
                    await page.click("text=/Analisar Rotina/i")
                    await page.wait_for_selector("tbody tr", timeout=10000)

            await browser.close()
            return rotinas_encontradas

        except Exception as e:
            await browser.close()
            raise Exception(f"Erro durante a navegação no SGDE: {str(e)}")
