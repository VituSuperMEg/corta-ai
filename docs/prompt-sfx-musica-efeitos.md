# Prompt para avaliação — SFX reais, música NoCopyrightSounds e efeitos de atenção em Shorts

Cole este prompt em uma sessão nova do agente (ou avalie primeiro e ajuste) antes de começar a implementação.

---

## Contexto do projeto

Você trabalha no **Corta Aí**, app local Python 3.10+ (FastAPI + uvicorn, não Flask) em `/home/vitu/Projetos/corta-ai`. Recebe URL pública do YouTube e gera cortes verticais 1080×1920 com legendas sincronizadas (faster-whisper `medium`, pt-BR), renderizados por FFmpeg.

Estrutura relevante:

- `corta_ai/app.py` — `CreateJobRequest` (modelo pydantic, `app.py:20-41`) valida a URL e **15 flags booleanas, todas default `False`**; `POST /api/jobs` repassa cada flag explicitamente para `store.create` (`app.py:154-176`).
- `corta_ai/jobs.py` — dataclass `Job` (`jobs.py:10-40`) guarda as flags; store em memória.
- `corta_ai/pipeline.py` — `process_job` (`pipeline.py:317-375`) orquestra download → transcrição → `choose_highlights` → por clip: legendas ASS, overlays, e `render_clip` (`pipeline.py:260-314`), que **monta o comando FFmpeg** (único ponto de construção de filtro do projeto).
- `corta_ai/effects.py` — efeitos visuais/sonoros atuais: `emphasis_times` (`effects.py:14-39`), zoom (`effects.py:78-85`), overlays (`effects.py:57-72`), SFX acentos sintetizados (`create_accent_audio`, `effects.py:88-106`), bipes de censura (`effects.py:157-164`), **música de fundo sintetizada** (`create_music_audio`, `effects.py:167-183` — pad lo-fi + kick, hardcoded, só liga/desliga).
- `corta_ai/director.py` — plano de edição por LLM opcional (NVIDIA/Ollama): mood, callouts, zoom, emoji.
- `corta_ai/static/index.html` + `app.js` — 15 checkboxes em português; `optionNames` (`app.js:72-73`) monta o corpo do POST; gate de compatibilidade busca `/openapi.json` e exige todos os campos presentes no schema (`app.py` → `CreateJobRequest.properties`) antes de liberar o submit (`app.js:76-81`).
- Áudio atual em `render_clip`: `loudnorm` + `afade` sempre; trilhas extras via `-i` temporários (`.accents.wav`, `.beeps.wav`, `.music.wav`), mistura com `amix=...:normalize=0`, ducking por `sidechaincompress` (`pipeline.py:299-304`), `alimiter=limit=0.95` (`pipeline.py:306-307`). Não existe `adelay`, não existem diretórios de assets de áudio, nem volume/intensidade configuráveis.
- Testes: `tests/test_api.py`, `test_subtitles.py`, `test_effects.py`, `test_highlights.py`, `test_director.py` (pytest) + `tests/check_caption_submit.cjs` (node, varre ~32k combinações de flags garantindo independência de cada opção no POST).

Regras permanentes do repositório (ler `AGENTS.md` antes de qualquer alteração):

1. Todo recurso opcional **novo ganha um checkbox próprio**, nome claro em português e descrição curta.
2. Recursos novos **começam desmarcados**; só ativar por padrão se eu pedir explicitamente.
3. Opções são **independentes**: marcar uma nunca pode ativar outra silenciosamente. Dependências reais devem ser explicadas na UI e desabilitar a opção dependente, nunca ligá-la às escondidas.
4. Cada seleção deve ser levada da interface → API → `Job` → `process_job` → comando FFmpeg → **vídeo exportado**. Checkbox que só muda prévia não serve.
5. Desmarcado = comportamento base exatamente como hoje. Testar combinações ligadas/desligadas e compatibilidade com servidor antigo.
6. Ajustes de intensidade/volume podem ser controles complementares (slider/select), mas o checkbox continua sendo a chave de ativação.
7. Correções de bug/manutenção não precisam de checkbox.

---

## Objetivo

Três entregas, todas com checkbox próprio, desmarcadas por padrão, independentes entre si:

- **A. Biblioteca de SFX reais** no lugar (ou ao lado) dos sons sintetizados atuais.
- **B. Música de fundo do catálogo NoCopyrightSounds (NCS)** com atribuição correta.
- **C. Novos efeitos de atenção para Shorts** (gancho, impacto, transições, ritmo) para aumentar retenção nos primeiros segundos.

---

## Escopo A — Biblioteca de SFX reais

1. Criar diretório de assets, ex.: `corta_ai/assets/sfx/`, organizado por categoria, por exemplo:
   - `hook/` (impacto no gancho do primeiro segundo)
   - `whoosh/` (transições/cortes de câmera)
   - `riser/` (construção antes do CTA final)
   - `impact/` (batida em palavra de ênfase)
   - `pop/` (aparecimento de callout/emoji)
   - `ding/` (destaque positivo, número, resultado)
2. Scanner que lê a pasta no início do job (ou do app) e expõe as categorias/arquivos disponíveis. Se a pasta estiver vazia, a opção se comporta como hoje (SFX sintetizados) ou fica desabilitada com aviso na UI — **nunca ativa outra coisa silenciosamente**.
3. Escolha da fonte dos arquivos ( decidir comigo antes de implementar ):
   - (a) você me informa os arquivos `.wav/.mp3` que posso usar (livres de direitos), eu só os coloco na pasta; ou
   - (b) gerar um pacote mínimo sintetizado de melhor qualidade (mais real que o acento atual) já versionado no repo.
4. Novos checkboxes sugeridos (nomes finais a combinar, todos default desmarcado, independentes):
   - **SFX de impacto no gancho** — som no início do clip quando `hook_start` estiver ativo ou no primeiro evento de ênfase.
   - **Whoosh nas transições** — som em cada corte de câmera (`camera_cuts`, `pipeline.py:362`) e nas bordas de zoom.
   - **Riser antes da chamada final** — subida de 1,5–2 s terminando no `end_cta`.
   - **SFX em palavras de ênfase** — existe hoje via `sound_effects` ("Efeitos sonoros leves", sintetizado); decidir se evolui este mesmo checkbox ou vira opção separada. **Não duplicar funcionalidade.**
5. Mixing: montar uma única trilha `.sfx.wav` por clip (eventos posicionados com `adelay`/soma em Python, no estilo do `create_accent_audio`) e entrá-la no grafo existente de `amix` — evita explodir o número de `-i`. Ajustar `duration=first`/limitador se necessário. Volume da trilha SFX com controle complementar (ex.: slider 0–100%), aplicado só quando o checkbox correspondente estiver marcado.

---

## Escopo B — Música NoCopyrightSounds (NCS)

1. **Origem da música:** pasta local `corta_ai/assets/music/` preenchida por mim com faixas que eu baixar oficialmente (ncs.io). **Não baixar música automaticamente do YouTube/yt-dlp** — viola ToS do YouTube e não respeita a licença. Se existir forma oficial/programática de obter faixas NCS, pode ser proposta, mas como alternativa, não como premissa.
2. UI: quando "Música de fundo" estiver marcado, exibir **select "Faixa"** com as opções detectadas (mais a atual "sintetizada" como fallback). Select fica desabilitado quando o checkbox está desmarcado.
3. **Atribuição obrigatória (licença NCS exige crédito):**
   - Novo checkbox **"Crédito da música NCS"** (ou integrado ao "Título, descrição e hashtags" — decidir, mas nada de ativação silenciosa) que injeta o crédito no cartão final e/ou nas sugestões de metadados geradas por `suggest_metadata` (`effects.py:195-212`), no formato que a licença NCS pedir (artista + faixa + link).
   - Se a atribuição não puder ser emitida, avisar na UI e não usar faixa NCS.
4. Controles complementares (só ativos com o checkbox marcado): volume da música e, se fizer sentido, opção de ducking (hoje fixo: `volume=0.35`, `threshold=0.03`, `ratio=8` em `pipeline.py:302-303`).
5. A mistura atual (`amix` + `sidechaincompress` + `alimiter`) deve continuar sem clipping e sem estourar o loudness alvo (`loudnorm I=-14`).

---

## Escopo C — Efeitos de atenção para Shorts

Efeitos candidatos — **cada um com checkbox próprio, desmarcado, independente**; avaliar e escolher o subconjunto que vale a pena antes de implementar tudo:

1. **Gancho explosivo** — nos primeiros ~1,5 s: flash rápido + zoom agressivo + tremor curto. Só no início do clip.
2. **Tremor de tela (screen shake)** — deslocamento/rotacionezinho curto em palavras de ênfase (`emphasis_times`) ou nos cortes de câmera.
3. **Flash branco nas trocas** — 2–3 quadros de overexposure a cada `camera_cuts` (só faz sentido com "Cortes de câmera"; se depender, desabilitar a opção com aviso quando `camera_cuts` estiver desmarcado, sem ligá-lo sozinho).
4. **Aceleração (speed ramp)** — trecho de alta energia (usar `audio_energy`, `pipeline.py:85-92`, e/ou score do `highlights`) acelerado com volta normal; áudio precisa ficar sem chipmunk (`atempo` adequado ou mantido só o vídeo).
5. **Riser/impacto sonoro antes do CTA** — ver Escopo A; se implementado como SFX, não duplicar como efeito visual separado.
6. **Destaque de palavras-chave** — palavra-chave na legenda ganha escala/cor maior por instante (complementa "Legendas estilosas", não depende dela).
7. **Vinheta + grain cinematográfico** — acabamento sutil, sem mexer nas legendas.
8. **Congelar (freeze) + zoom no ponto alto** — micro-pausa de 0,3–0,5 s no clímax da frase.

Restrições de Escopo C:

- Efeitos não podem quebrar legendas ASS, barra de progresso, título de abertura, CTA final nem o plano do `director` — testar com combinações liga/desliga.
- Nenhum efeito pode ser ativado implicitamente por outro ("Flash branco" não pode ligar "Cortes de câmera").
- Respeitar o budget de performance: o render já é FFmpeg único; preferir filtros existentes (`zoompan`, `eq`, `rgbashift`, `shake` se disponível, `setpts`+`atempo`) a pós-etapas extras.

---

## Fases de entrega (proposta)

1. **Fundação de assets**: pastas, scanner de música/SFX, select de faixa, crédito NCS, novos campos em `CreateJobRequest`/`Job`/`optionNames`/`check_caption_submit.cjs`.
2. **SFX reais**: biblioteca, agendamento por evento, mixing (`adelay`/trilha única), volume por trilha.
3. **Efeitos de atenção**: um por vez, com checkbox, teste de independência e render real.
4. **Politura**: loudness final, limiter, UX dos controles complementares, docs.

Entregar fase a fase, cada uma com testes passando, antes de começar a próxima.

---

## Validação obrigatória (não vale só testar a interface)

- `python3 -m pytest -q` verde.
- `node tests/check_caption_submit.cjs` atualizado cobrindo **todos** os novos nomes em `optionNames`.
- Novos testes no estilo dos existentes: independência 2×N de flags, round-trip API, e mapeamento flag → comando FFmpeg (como `tests/test_effects.py` faz com `pipeline._run`).
- **Geração real**: rodar o pipeline de ponta a ponta em um vídeo curto que eu indique, com cada novo recurso ligado e desligado, conferindo o MP4 final (legenda íntegra, áudio sem clipping, efeito presente/ausente conforme o checkbox).
- Antes de reiniciar o servidor: checar jobs ativos em `workspace/`, nunca interromper renderização; me informar qual endereço (porta) tem a versão nova e o que ainda exige reinício.
- Não commitar sem eu pedir.

---

## Critérios de aceite

1. Cada recurso novo tem checkbox próprio em português, desmarcado por padrão, com descrição curta na UI.
2. Marcar qualquer combinação de checkboxes produz exatamente os efeitos combinados no vídeo exportado — zero ativações cruzadas silenciosas.
3. Música NCS toca quando selecionada, com atribuição gerada corretamente, e a pasta de música pode ficar vazia sem quebrar nada.
4. SFX reais soam nos eventos certos (gancho, cortes, ênfase, CTA) e mixam sem distorção.
5. Pelo menos 4 novos efeitos de atenção implementados, validados por render real, sem regressão nos 15 checkboxes atuais.
6. Servidor antigo (sem os novos campos) é detectado pelo gate do `app.js` e bloqueia o submit com a mensagem existente.

---

## Perguntas em aberto (responder antes de implementar)

1. Origem dos arquivos: você fornece SFX/música NCS ou o repo gera/versão um pacote mínimo?
2. Crédito NCS: cartão final, sugestões de metadados ou os dois?
3. "SFX em palavras de ênfase": evoluir o checkbox existente "Efeitos sonoros leves" ou criar um novo ao lado?
4. Quais efeitos do Escopo C entram na primeira leva (sugestão: gancho explosivo, tremor de tela, flash nas trocas, destaque de palavras-chave)?
5. Faixa NCS por clip: mesma faixa para todos os cortes ou sorteio por clip?
