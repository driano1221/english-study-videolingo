# Referências e atribuições

## Projeto de origem

- [Huanshere/VideoLingo](https://github.com/Huanshere/VideoLingo) — pipeline
  original de download, transcrição, segmentação, tradução, legenda e dublagem.
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) — licença
  mantida neste derivado.

## Componentes técnicos principais

- [WhisperX](https://github.com/m-bain/whisperX) — ASR com timestamps por
  palavra, alinhamento e VAD.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — aquisição de mídia e metadados.
- [FFmpeg](https://ffmpeg.org/documentation.html) e
  [filtro subtitles](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1) —
  composição, mux, encoders e inspeção audiovisual.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) — inferência otimizada
  usada pelo backend Faster-Whisper.
- [spaCy](https://spacy.io/usage/linguistic-features) — análise linguística
  usada na segmentação determinística.
- [PyInstaller](https://pyinstaller.org/en/stable/spec-files.html) — geração do
  executável Windows.
- [uv](https://docs.astral.sh/uv/) — criação reproduzível do ambiente Python.

## Aprendizado de inglês

A pesquisa aplicada, incluindo input compreensível, sentence mining, shadowing
e repetição espaçada, está em [learning-research.md](learning-research.md). Cada
ferramenta ou método citado ali mantém seu link de origem.

## Como interpretar estas referências

As bibliotecas acima fundamentam componentes do sistema; elas não validam por
si só a qualidade pedagógica de um vídeo produzido. A qualidade é determinada
pelas métricas, testes e inspeções descritos em [validation.md](validation.md).
