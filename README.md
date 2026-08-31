# Corta Aí

Aplicação local que recebe uma URL pública do YouTube e gera a quantidade de cortes verticais solicitada, com transcrição Whisper, legendas sincronizadas e MP4 prontos para download.

## Iniciar

Requisitos: Python 3.10+, FFmpeg/FFprobe e `yt-dlp`.

```bash
cd /home/vitu/Projetos/corta-ai
chmod +x iniciar.sh
./iniciar.sh
```

Abra <http://127.0.0.1:8000>. Na primeira execução, o modelo Whisper `small` será baixado. Ele fica em cache e o processamento posterior é local.

O sistema baixa um único vídeo, transcreve em português, seleciona janelas não repetidas, converte para 1080×1920, normaliza o áudio e incorpora legendas animadas. Os resultados ficam em `workspace/<id>/outputs/`.

## Testes

```bash
python3 -m pytest -q
```

Use apenas conteúdo que você tem autorização para baixar e reutilizar.
