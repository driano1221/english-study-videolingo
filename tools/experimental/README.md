# Utilitários experimentais

Estes scripts de recuperação e validação não fazem parte do pipeline de
produção:

- `fix_srt_artifacts.py`
- `process_after_download.py`
- `process_existing.py`
- `process_video.py`
- `regenerate_video_from_subs.py`
- `reprocess_spider.py`
- `validate_subtitles.py`

Execute a partir da raiz do repositório, por exemplo:

```powershell
.venv\Scripts\python.exe tools\experimental\validate_subtitles.py
```

Alguns arquivos contêm URLs, regras ou hipóteses específicas dos vídeos usados
na depuração. Novos experimentos ficam nesta pasta e não devem ser importados
por `core` nem por `app`.
