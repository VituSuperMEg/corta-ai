# Hospedagem do Corta Aí

O Dockerfile contém Python, FFmpeg, fontes e o servidor web. Pode ser usado em serviços que executem contêineres Linux. A publicação ainda depende de uma conta autenticada e da escolha do plano.

## Executar o contêiner

```sh
docker build -t corta-ai .
docker run --rm -p 7860:7860 corta-ai
```

Abra http://localhost:7860. A rota `/healthz` verifica se o servidor está respondendo; não testa o download do YouTube nem a transcrição.

## Configuração no Render

1. Envie o projeto para um repositório Git e conecte-o ao Render.
2. Crie um Web Service com linguagem Docker e Dockerfile `./Dockerfile`.
3. Configure o health check para `/healthz`.
4. Escolha o plano e confira o preço antes de confirmar a criação. Para o modelo `small`, comece avaliando uma máquina com pelo menos 2 GB de RAM; o uso real precisa ser medido com vídeos representativos.
5. Depois do deploy, abra a URL HTTPS fornecida pelo Render e teste um vídeo curto de ponta a ponta.

Não foi incluído um Blueprint que ative automaticamente um plano pago.

## Variáveis opcionais

| Variável | Padrão | Uso |
| --- | --- | --- |
| PORT | 7860 | Porta HTTP; o provedor pode sobrescrever |
| WHISPER_MODEL | small | Modelo de transcrição; `base` consome menos recursos e pode reduzir a qualidade |
| CPU_THREADS | 2 | Threads da transcrição |
| MAX_PENDING_JOBS | 5 | Total máximo de trabalhos em execução e esperando |
| WORKSPACE_DIR | /app/workspace | Diretório dos vídeos |
| HF_HOME | /app/cache | Cache dos modelos |

Use apenas um processo Uvicorn e uma instância: o estado dos trabalhos fica em memória. A fila executa um trabalho por vez e retorna HTTP 429 quando está cheia. Reinícios perdem o histórico e interrompem trabalhos; os arquivos também são temporários se o provedor não tiver disco persistente. Baixe os resultados antes de reiniciar ou fazer novo deploy. Ainda não há remoção automática dos vídeos: acompanhe o espaço disponível durante os testes.

O primeiro trabalho baixa o modelo Whisper. Downloads do YouTube podem ser recusados a partir de IPs de datacenter; valide essa etapa na hospedagem antes de distribuir o link. O app não possui login: qualquer pessoa com acesso à URL pode enviar trabalhos.

Referências: https://render.com/docs/docker e https://render.com/docs/compute-plans.
