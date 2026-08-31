# Corta Aí — MVP local

## Objetivo

Receber uma URL pública do YouTube e gerar, localmente, a quantidade de cortes
verticais solicitada pelo usuário, com legendas sincronizadas e arquivos para
prévia e download.

## Critérios aceitos

1. O formulário aceita URL do YouTube, quantidade e duração dos cortes.
2. A API valida os dados e cria o processamento.
3. O pipeline gera exatamente a quantidade solicitada quando o vídeo possui
   duração suficiente.
4. O progresso e os erros ficam disponíveis pela API e aparecem na interface.
5. Os MP4 finais ficam disponíveis para prévia e download.

## Restrições

- Execução somente local nesta versão.
- O usuário é responsável por ter autorização para reutilizar o conteúdo.
- Vídeos públicos do YouTube.
- Português brasileiro por padrão.

