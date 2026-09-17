# Instruções permanentes — Corta Aí

Leia este arquivo antes de planejar ou alterar o projeto.

## Controle do usuário por checkbox

- Todo novo recurso opcional deve ter um checkbox próprio, com nome claro em português e uma descrição curta do efeito.
- Recursos novos começam desmarcados. Só ativar por padrão se o usuário pedir explicitamente.
- Não aplicar efeitos, fontes, música, zoom, transições ou outras mudanças criativas sem a seleção correspondente.
- Opções diferentes devem ser independentes: marcar “Legendas estilosas” não pode ativar “Variar fontes” implicitamente.
- Se existir uma dependência indispensável, explicar na interface e desabilitar a opção dependente quando necessário; nunca ativar outra opção silenciosamente.
- Levar cada seleção da interface à API, ao trabalho e ao processamento final. O checkbox deve alterar o vídeo exportado, não apenas a prévia.
- Desmarcado deve preservar o comportamento base daquele recurso. Conferir combinações ligadas e desligadas, além de compatibilidade com versões antigas do servidor.
- Ajustes de intensidade, cor ou tamanho podem usar controles complementares; o checkbox continua sendo a chave de ativação.
- Correções de bugs, segurança e manutenção interna não precisam de checkbox. Campos obrigatórios, como URL e duração, continuam usando controles apropriados.

## Entrega e validação

- Preservar arquivos e alterações existentes do usuário.
- Validar a geração real quando mudar legendas, fontes ou efeitos; não basta testar a interface.
- Antes de reiniciar o servidor, conferir trabalhos ativos e preservar o acesso aos resultados. Não interromper renderizações.
- Informar com clareza qual endereço contém a versão atualizada e o que ainda exige reinício.
- Ideias futuras são propostas, não autorização para implementar todos os efeitos de uma vez.
