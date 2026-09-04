# Operação local

## Pré-requisitos

- Windows 10/11;
- Python 3.11 recomendado pelo upstream ou os ambientes locais já validados;
- FFmpeg no `PATH` ou em `../tools/ffmpeg/bin` no layout legado;
- espaço livre compatível com a resolução escolhida;
- GPU opcional; CPU continua sendo o último fallback.

Instalação base:

```powershell
python setup_env.py
```

## Executar

```powershell
.venv\Scripts\python.exe -m app.desktop
```

Para testar o ambiente paralelo no workspace legado:

```powershell
$env:VIDEOLINGO_PYTHON = '3.12'
..\simple_gui.py
```

## Construir o executável

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

O script grava `build/` e `dist/` ao lado do repositório quando detecta o
workspace legado. Esses diretórios não pertencem ao Git.

## Diagnóstico por etapa

1. Leia o erro apresentado pela interface.
2. Consulte `output/log/run_metrics.json` para identificar a etapa lenta.
3. Consulte `output/log/asr_runtime.json` para batch, compute type e gaps.
4. Consulte `output/gpt_log/usage_summary.json` para custo e chamadas.
5. Execute `tools/check_runtime.py` e depois a suíte de testes.
6. Preserve o job em `cache/jobs` antes de uma correção manual.

Não apague todo o cache para corrigir um job. O ID e os metadados existem para
permitir inspeção e retomada seletiva.

## Problemas comuns

- **Sem legenda em intervalos:** compare a faixa oficial/ASR com a cobertura e
  examine os candidatos de gap antes de traduzir novamente.
- **Texto cortado:** verifique primeiro segmentação e timestamps; aumentar a
  fonte ou forçar duas linhas apenas mascara o problema.
- **Render lento:** confirme o encoder registrado. A queda para CPU é funcional,
  porém naturalmente mais lenta.
- **Custo zero:** pode significar cache, tradução já presente no YouTube ou
  caminho totalmente local. Confirme `api_calls`, não apenas o valor monetário.
