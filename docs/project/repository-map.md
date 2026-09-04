# Mapa do repositório

## Fronteira de versionamento

`VideoLingo/` é o repositório Git canônico. A pasta pai é um workspace local
compatível com a instalação atual no Windows. Ela armazena conteúdo grande ou
específico da máquina e não deve ser enviada ao GitHub.

```text
english-study-videolingo/          workspace local
├── VideoLingo/                    repositório Git canônico
│   ├── app/                       interface desktop e cache
│   ├── core/                      pipeline de produção
│   ├── tests/                     regressões automatizadas
│   ├── tools/                     auditoria e diagnóstico
│   ├── packaging/windows/         receita do executável
│   ├── docs/project/              documentação desta modificação
│   ├── output/                    tarefa ativa; não versionada
│   ├── .venv/ e .venv312/         ambientes; não versionados
│   └── config.yaml                configuração sem segredos
├── cache/                         mídia e etapas reutilizáveis
├── videos/
│   ├── finalizados/               resultados escolhidos
│   ├── historico/                 versões antigas preservadas
│   └── testes/                    clipes de teste
├── validation/                    evidências visuais locais
├── tools/ffmpeg/                  binários locais
├── build/ e dist/                 artefatos do PyInstaller
├── simple_gui.py                  launcher de compatibilidade
└── pipeline_cache.py              import de compatibilidade
```

## Donos das responsabilidades

- `app/desktop.py`: opções da interface, orquestração e cópia do resultado.
- `app/pipeline_cache.py`: identidade da tarefa, snapshots e espaço livre.
- `core/_1_ytdlp.py`: aquisição e manifestação da mídia.
- `core/youtube_subtitles.py`: tentativa de reaproveitar legenda publicada.
- `core/_2_asr.py` e `core/asr_backend/`: transcrição e alinhamento local.
- `core/_3_*` a `core/_6_*`: segmentação, tradução e timestamps.
- `core/_7_sub_into_vid.py`: composição visual, encoder e validação de saída.
- `core/run_metrics.py`: métricas estruturadas da execução.

## O que nunca deve ser versionado

Chaves, `.env`, ambientes virtuais, `_model_cache`, `output`, caches, vídeos,
frames de auditoria, executáveis e logs reais. Evidências pequenas e
anonimizadas só entram quando sustentarem um teste ou uma decisão documentada.
