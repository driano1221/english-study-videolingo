# English Study VideoLingo

YouTube in. Legendas de estudo out.

Fork local-first do [VideoLingo](https://github.com/Huanshere/VideoLingo),
focado em inglês + PT-BR legível. Sem vínculo oficial com o upstream.

## O que mudou

> legenda do YouTube antes de WhisperX

> cache por mídia e configuração

> tradução em lotes + custo real por tarefa

> VAD, batch adaptativo e reparo seletivo de gaps

> NVENC -> Quick Sync -> CPU

> inglês, PT-BR ou bilíngue

> MP4 fixo ou MKV ativável

## Números

- 56 testes no Python 3.10
- 56 testes no Python 3.12
- 3 perfis de inferência
- 2 formatos de saída
- 1 chave fora do YAML

## Rodar

```powershell
python setup_env.py
$env:VIDEOLINGO_API_KEY = 'sua-chave'
.venv\Scripts\python.exe -m app.desktop
```

Auditoria:

```powershell
.venv\Scripts\python.exe tools\audit_repository.py --tests
```

## Mapa

- `app/` — desktop + cache
- `core/` — pipeline
- `tests/` — regressões
- `tools/` — auditoria e experimentos
- `docs/project/` — arquitetura, operação e referências

Comece por [architecture.md](docs/project/architecture.md).
As diferenças do upstream estão em [fork-changes.md](docs/project/fork-changes.md).

## Estado

Beta local. Validado no Windows 11 + RTX 3050.

Derivado do commit `814f84e`. Apache-2.0 preservada em [LICENSE](LICENSE) e
atribuição em [NOTICE](NOTICE).
