# Pesquisa: Repositórios, Frameworks e Técnicas para Aprendizado de Idioma

Resumo de recursos encontrados para integrar ao projeto de estudo de inglês.

---

## 1. Técnicas de aprendizado baseadas em evidência

### Comprehensible Input (Input Compreensível)
- Teoria de Stephen Krashen: adquirimos idioma entendendo mensagens, não decorando regras.
- Ideal: conteúdo onde você entenda 80-90% e tenha 10-20% de novidade ("i+1").
- Vídeos com legendas bilíngues são uma forma clássica de input compreensível.
- Referência: [Comprehensible Input Wiki](https://comprehensibleinputwiki.org/wiki/Main_Page)

### Sentence Mining
- Extrair frases reais do conteúdo assistido que contenham palavras/desconhecidas.
- Cada frase vira um flashcard com contexto (vídeo, áudio, legenda original + tradução).
- Referência: [Sentence Mining - All Japanese All The Time](https://tatsumoto-ren.github.io/blog/sentence-mining.html)

### Shadowing
- Repetir em voz alta o que se ouve, imitando pronúncia, entonação e ritmo.
- Útil para fluência e pronúncia.
- Ferramenta relacionada: [EchoTalk](https://github.com/alisolphp/EchoTalk) — app web de shadowing com segmentação de frases e gravação.

### Spaced Repetition (SRS)
- Revisar flashcards em intervalos crescentes, baseado na curva do esquecimento.
- Algoritmos populares: SM-2 (Anki), FSRS (Free Spaced Repetition Scheduler).

---

## 2. Frameworks e algoritmos de repetição espaçada

### FSRS (Free Spaced Repetition Scheduler)
- Algoritmo moderno baseado no modelo DSR (Difficulty, Stability, Retrievability).
- Implementações oficiais em várias linguagens.
- Python: [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs)
- Organização: [Open Spaced Repetition](https://github.com/open-spaced-repetition)
- Wiki/Recursos: [Awesome FSRS](https://github.com/open-spaced-repetition/fsrs4anki/wiki/Awesome-FSRS)

### Anki
- Software de flashcards open-source com SRS.
- Pode ser integrado via AnkiConnect (plugin) para criar cards automaticamente.
- Versão Android: AnkiDroid.

---

## 3. Repositórios para gerar materiais a partir de vídeos/legendas

### gogadget
- Toolkit amigável para gerar ferramentas de aprendizado por imersão.
- Baixa mídia, gera legendas e cria decks Anki.
- GitHub: [jonathanfox5/gogadget](https://github.com/jonathanfox5/gogadget)

### Language Learning With Anki
- Cria cards Anki a partir de legendas usando a extensão Language Reactor.
- GitHub: [ClearlyKyle/Language-Learning-With-Anki](https://github.com/ClearlyKyle/Language-Learning-With-Anki)

### deck-gen
- Gera decks Anki a partir da frequência de palavras em legendas de séries.
- GitHub: [jack-willturner/deck-gen](https://github.com/jack-willturner/deck-gen)

### lat
- Ferramentas para aquisição de idioma por imersão.
- Análise de sentenças (livros, legendas) e criação de cards Anki.
- GitHub: [pigoz/lat](https://github.com/pigoz/lat)

### Watch Foreign Language Movies with Anki
- Add-on do Anki que converte vídeos/legendas em cards Anki.
- Divide o vídeo em cenas/frases.
- AnkiWeb: [939347702](https://ankiweb.net/shared/info/939347702)

### WordHunter
- Ferramenta de repetição espaçada com livros e textos.
- Destaca vocabulário, mostra tradução, contexto, TTS e revisão.
- GitHub: [Ironship/WordHunter](https://github.com/Ironship/WordHunter)

---

## 4. Ferramentas e extensões para legendas bilíngues

### Language Reactor
- Extensão de navegador para Netflix/YouTube com legendas duplas.
- Permite clicar em palavras, salvar vocabulário e exportar para Anki.
- Site: [languagereactor.com](https://languagereactor.com)

### Trancy
- Extensão para legendas bilíngues no YouTube.
- Site: [trancy.org](https://www.trancy.org)

### Migaku
- Ecossistema de aprendizado de idiomas com legendas, flashcards e imersão.
- Artigo: [Language Learning with Subtitles](https://migaku.com/blog/language-fun/language-learning-with-subtitles)

---

## 5. Canais do YouTube para input compreensível em inglês

- [EF GO Blog - Best YouTube channels to learn English](https://www.ef.com/wwen/blog/language/best-youtube-channels-to-learn-english-at-home/)
- [LangPanda - Best English Comprehensible Input YouTube Channels](https://langpanda.com/learn/english/comprehensible-input)
- [LangPanda - Comprehensible Input by language](https://langpanda.com/comprehensible-input)

Canais recomendados para inglês:
- Dreaming Spanish (metodologia CI)
- English with Lucy
- BBC Learning English
- TED-Ed
- Veritasium (seu caso de uso atual)

---

## 6. Ideias de integração com o projeto VideoLingo

1. **Exportar sentenças para Anki**
   - A partir de `src.srt` e `trans.srt`, gerar cards Anki com:
     - Frente: frase em inglês + screenshot do vídeo
     - Verso: tradução em português + áudio da frase

2. **Sentence Mining automático**
   - Identificar palavras desconhecidas pelo usuário.
   - Criar cards apenas para palavras novas, com contexto do vídeo.

3. **Playlist de estudo**
   - Permitir processar múltiplos vídeos de uma playlist do YouTube.
   - Gerar um catálogo de vídeos legendados por tema/dificuldade.

4. **Repetição espaçada integrada**
   - Usar [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) para criar um SRS leve dentro do projeto.
   - Ou exportar diretamente para Anki via AnkiConnect.

5. **Exercícios de shadowing**
   - Segmentar o áudio por frases.
   - Mostrar a legenda e gravar a voz do usuário para comparar.

6. **Geração de vocabulário por frequência**
   - Analisar legendas de vários vídeos.
   - Listar as palavras mais frequentes e criar decks prioritários.

---

## 7. Frameworks web para expandir a interface

- **Reflex** (Python puro, full-stack): [reflex.dev](https://reflex.dev)
- **Streamlit**: já usado no VideoLingo, bom para protótipos.
- **FastAPI + React**: mais robusto para app de produção.
- **Django/Flask**: se quiser backend com banco de dados de usuário/vocabulário.

---

## 8. Próximos passos sugeridos

1. Criar um parser de `.srt` para extrair frases + timestamps.
2. Integrar com AnkiConnect para exportar cards automaticamente.
3. Adicionar ao `.exe` uma opção "Gerar deck Anki" após processar o vídeo.
4. Explorar [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) para um SRS interno leve.

---

*Documento gerado em 19/08/2026 para o projeto `english-study-videolingo`.*
