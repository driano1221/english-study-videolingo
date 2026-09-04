# Ambiente paralelo Python 3.12

O ambiente principal continua em `.venv` (Python 3.10). O candidato está em
`.venv312` e não substitui nem modifica o principal.

## Estado validado

- Python 3.12.10
- PyTorch 2.8.0 + CUDA 12.9
- TorchAudio 2.8.0 + CUDA 12.9
- TorchVision 0.23.0 + CUDA 12.9
- CTranslate2 4.8.2
- WhisperX 3.8.6
- Demucs 4.1.0
- 56 testes automatizados aprovados
- transcrição e alinhamento reais executados na RTX 3050

Dezessete DLLs CUDA byte a byte idênticas usam hard links entre os dois
ambientes. Uma atualização de pacote normalmente substitui o arquivo e rompe
apenas o link daquele ambiente; ainda assim, valide os dois ambientes depois
de atualizar PyTorch.

## Ativação de teste

Por padrão, o executável usa Python 3.10. Para iniciar uma sessão usando o
candidato 3.12, defina `VIDEOLINGO_PYTHON=3.12` antes de abrir o aplicativo.
Remova a variável para voltar imediatamente ao 3.10.

Validação rápida:

```powershell
.venv312\Scripts\python.exe -m unittest discover -s tests -q
.venv312\Scripts\python.exe ..\validation\asr_session_probe.py
```

Não promova o 3.12 a padrão antes de alguns vídeos reais longos cobrirem tanto
o caminho de legendas do YouTube quanto o fallback completo do WhisperX.
