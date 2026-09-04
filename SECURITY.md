# Segurança

## Segredos

- A chave principal deve existir apenas em `VIDEOLINGO_API_KEY` no ambiente do
  usuário.
- Não publique `.env`, `config.backup.yaml`, logs de requisição ou arquivos de
  cache sem revisá-los.
- `config.yaml` deve manter `api.key` vazio.
- Antes de qualquer publicação, execute `python tools/audit_repository.py` e
  revise `git diff --cached`.

## Relato de vulnerabilidade

Não coloque chaves, URLs privadas ou dados pessoais em uma issue pública.
Depois que o fork tiver um endereço próprio no GitHub, habilite **Private
vulnerability reporting** na aba Security e use esse canal.

## Conteúdo externo

Links e metadados de vídeo são entradas não confiáveis. O pipeline não deve
transformar títulos, descrições, legendas ou respostas de API em comandos do
sistema.
