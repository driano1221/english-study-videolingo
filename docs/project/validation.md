# Validação e evidências

## Porta de entrada

```powershell
.venv\Scripts\python.exe tools\audit_repository.py --tests
```

O auditor verifica documentação obrigatória, arquivos indevidos no Git,
segredo principal no YAML, arquivos versionados grandes e a suíte de testes.

Validação explícita nos dois ambientes:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.venv312\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

## Vídeo real

Para cada mudança de pipeline, registre:

- URL ou hash da mídia e duração;
- perfil, modo de legenda, tamanho e formato;
- origem da transcrição (`youtube*` ou `whisperx`);
- tempo total e por etapa, RTF, encoder e pico de VRAM;
- cobertura temporal e gaps relevantes;
- chamadas, tokens e custo estimado;
- `ffprobe` da saída e capturas visuais representativas.

## Critérios mínimos

- testes automatizados passam;
- saída contém áudio e vídeo reproduzíveis;
- nenhum bloco se sobrepõe de forma ilegível ou sai do quadro;
- a faixa traduzida permanece associada à fala correspondente;
- gaps de fala longos são explicados ou reparados;
- custo exibido coincide com `usage_summary.json`;
- cache repetido não chama a API sem necessidade.

## Última linha de base local

Em 3 de setembro de 2026: 56 testes aprovados no Python 3.10 e 56 no Python
3.12. Um teste de abertura do executável também foi concluído. Evidências
grandes permanecem no diretório local `../validation` e não no Git.
