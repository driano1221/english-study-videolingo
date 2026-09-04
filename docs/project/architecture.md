# Arquitetura

## Objetivo

Gerar material de estudo legível e sincronizado, preferindo caminhos locais ou
reutilizáveis e usando API paga apenas onde ela agrega tradução.

## Caminho representativo

1. `app.desktop.run_processing` valida as opções, calcula o ID da tarefa e
   verifica espaço em disco.
2. `JobCache` restaura uma execução compatível ou prepara `output/`.
3. `_1_ytdlp` baixa ou reutiliza a mídia e registra `input_manifest.json`.
4. `youtube_subtitles` tenta obter uma faixa inglesa confiável. Sem ela,
   `_2_asr` executa WhisperX local e valida a cobertura da fala.
5. `_3_1` e `_3_2` formam unidades de leitura; `_4_1` e `_4_2` criam contexto
   e traduzem em lotes; `_5` e `_6` ajustam texto e timestamps.
6. `_7_sub_into_vid` cria MP4 com legenda fixa ou MKV com legenda ativável,
   usando o primeiro encoder funcional entre NVENC, Quick Sync e CPU.
7. A interface valida áudio, vídeo e duração com `ffprobe`, copia o resultado
   para `videos/finalizados` e mostra custo e métricas.

## Contratos importantes

- O ID do cache muda quando fonte, resolução, idioma, perfil ou versão do
  pipeline mudam; a chave da API não participa do hash.
- `output/input_manifest.json` identifica a mídia ativa. Não escolha arquivos
  apenas por extensão ou data.
- A trilha inglesa é a referência temporal; tradução não pode inventar ou
  remover intervalos da fala.
- Uma saída concluída precisa ter duração positiva, faixa de vídeo, faixa de
  áudio e tamanho maior que 1 KiB.
- O custo mostrado é estimativa calculada a partir do uso informado pelo
  provedor e das tarifas configuradas; não substitui a fatura do provedor.

## Estado e artefatos

- `output/`: estado mutável da tarefa atual.
- `cache/jobs/<job-id>/`: snapshot retomável das etapas.
- `cache/media/<media-id>/`: uma cópia canônica por mídia/resolução.
- `output/log/run_metrics.json`: tempos, RTF, encoder, recursos e cobertura.
- `output/gpt_log/usage_summary.json`: chamadas, tokens e custo estimado.

## Pontos de extensão

Adicione comportamento no dono atual da responsabilidade. Perfis de ASR ficam
em `runtime_utils.py`; regras de layout em `_7_sub_into_vid.py`; contabilidade
de API em `ask_gpt.py`; novas opções de interface em `app/desktop.py`. Evite
scripts paralelos que repitam o pipeline.
