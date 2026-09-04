# Contribuindo

## Antes de alterar

1. Leia `docs/project/architecture.md` e localize o dono da responsabilidade.
2. Não adicione vídeos, modelos, caches, ambientes virtuais, chaves ou saídas.
3. Preserve a compatibilidade dos três modos de legenda e dos dois formatos.
4. Para mudanças herdadas do upstream, registre a origem em
   `docs/project/fork-changes.md`.

## Verificação mínima

```powershell
.venv\Scripts\python.exe tools\audit_repository.py --tests
```

Mudanças de renderização também exigem um clipe curto, `ffprobe`, captura com a
legenda ligada e desligada quando aplicável, e inspeção visual em pelo menos
três momentos diferentes. Registre somente métricas e evidências pequenas; o
vídeo completo fica fora do Git.

## Pull request

Descreva o problema, a causa, os arquivos alterados, o comando de validação e
o resultado. Diga explicitamente se houve chamada paga de API e o custo medido.

## Publicar o fork pela primeira vez

O remoto `upstream` aponta para o projeto original e tem push localmente
desativado. Depois de criar seu fork no GitHub, conecte-o sem substituir a
referência original:

```powershell
git remote add origin URL_DO_SEU_FORK
git push -u origin main
```
