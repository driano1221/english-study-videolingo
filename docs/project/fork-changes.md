# Inventário da modificação

## Proveniência

- Upstream: `Huanshere/VideoLingo`
- Commit base local: `814f84e`
- Licença preservada: Apache-2.0
- Estado: alterações locais ainda não publicadas em um fork próprio

## Mudanças por área

### Aplicação e operação

- interface Tkinter em `app/desktop.py`;
- perfis Grátis, Equilibrado e Máxima robustez;
- modos inglês, português e bilíngue;
- MP4 com legenda fixa e MKV com legenda ativável;
- cache retomável, espaço preventivo e saída organizada;
- estimativa de custo e métricas apresentadas ao usuário.

### Aquisição e inferência

- reaproveitamento de mídia e legendas do YouTube;
- carregamento reutilizável de modelos;
- `int8_float16` com fallback automático de batches;
- VAD, detecção e reparo seletivo de gaps;
- título e descrição convertidos em hotwords;
- execução paralela validada no Python 3.12.

### Texto, tradução e legenda

- processamento local antes de fallback ao LLM;
- tradução ordenada em lotes e contabilidade centralizada;
- reparo de fragmentos isolados e pontuação;
- reflow de frases sem perder a associação temporal;
- layout bilíngue com tamanhos equivalentes, português amarelo claro e sem
  caixa preta exclusiva.

### Renderização e observabilidade

- fallback NVENC -> Quick Sync -> CPU;
- validação com `ffprobe`;
- RTF, VRAM, encoder, cobertura e tempos por etapa;
- testes automatizados para cache, custo, ASR, tradução e modos de saída.

## Arquivos experimentais

Utilitários pontuais foram retirados da raiz e preservados em
`tools/experimental`. Eles não fazem parte do caminho normal e podem conter
hipóteses específicas de vídeos usados durante a depuração.
