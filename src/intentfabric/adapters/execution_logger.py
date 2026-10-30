"""Persiste registros completos JSON y metricas CSV acumulativas en UTF-8."""

import csv
import json
from pathlib import Path

from intentfabric.domain.execution import CSV_HEADERS, ExecutionRecord


class FileExecutionLogger:
    """Exporta evidencia experimental a los caminos solicitados."""

    def __init__(
        self, *, json_path: Path | str | None = None, csv_path: Path | str | None = None,
    ) -> None:
        self._json_path = Path(json_path) if json_path is not None else None
        self._csv_path = Path(csv_path) if csv_path is not None else None

    def record(self, execution: ExecutionRecord) -> None:
        """Reemplaza el JSON y anexa una fila CSV escribiendo encabezado solo si falta."""
        if self._json_path is not None:
            self._json_path.parent.mkdir(parents=True, exist_ok=True)
            self._json_path.write_text(
                json.dumps(execution.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8", newline="\n",
            )
        if self._csv_path is not None:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = not self._csv_path.exists() or self._csv_path.stat().st_size == 0
            with self._csv_path.open("a", encoding="utf-8", newline="\n") as stream:
                writer = csv.DictWriter(stream, fieldnames=CSV_HEADERS, lineterminator="\n")
                if needs_header:
                    writer.writeheader()
                writer.writerow(execution.to_csv_row())
