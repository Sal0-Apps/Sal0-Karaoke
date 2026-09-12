"""Executa o CLI do Demucs com o número de threads definido pela aplicação."""

import os

import torch


def main() -> None:
    configured = os.environ.get("DEMUCS_CPU_THREADS", "1").strip()
    try:
        threads = max(1, int(configured))
    except ValueError:
        threads = 1

    # Definir as threads antes de importar o CLI evita que o PyTorch escolha
    # um valor padrão menor durante a inicialização do processo filho.
    torch.set_num_threads(threads)
    try:
        # O paralelismo principal fica nas operações intra-op acima; manter
        # inter-op em uma fila evita multiplicação de workers e OOM.
        torch.set_num_interop_threads(1)
    except RuntimeError:
        # Algumas versões podem inicializar o pool antes desta chamada.
        pass

    from demucs.separate import main as demucs_main

    demucs_main()


if __name__ == "__main__":
    main()
