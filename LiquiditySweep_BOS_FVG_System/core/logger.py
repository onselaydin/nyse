from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logger(log_dir: Path, name: str = "ls_bos_fvg") -> logging.Logger:
    """Konsol + dosya loglamayı Türkçe format ile kurar."""

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "system.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    rich_handler = RichHandler(rich_tracebacks=True, markup=True)
    rich_handler.setLevel(logging.INFO)
    rich_formatter = logging.Formatter("%(message)s")
    rich_handler.setFormatter(rich_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(rich_handler)
    logger.propagate = False

    logger.info("[bold green]Log sistemi başlatıldı.[/bold green]")
    return logger
