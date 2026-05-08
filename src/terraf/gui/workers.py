"""
TerraF GUI — Workers QThread para ejecutar pipeline en background.

Patrón: cada tarea pesada corre en un PipelineWorker (QThread),
emite señales de progreso (step_signal) y resultado (done_signal / error_signal).
La UI nunca se congela.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt5.QtCore import QThread, pyqtSignal


class PipelineWorker(QThread):
    """
    Worker genérico para ejecutar cualquier función de pipeline en background.

    Uso:
        worker = PipelineWorker(fn, arg1, arg2, on_step=callback, kwarg=val)
        worker.step_signal.connect(log_widget.append)
        worker.done_signal.connect(on_done)
        worker.error_signal.connect(on_error)
        worker.start()
    """

    # Señal de paso de progreso (mensaje texto)
    step_signal  = pyqtSignal(str)
    # Señal de resultado exitoso (objeto arbitrario)
    done_signal  = pyqtSignal(object)
    # Señal de error (mensaje de error)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        fn: Callable,
        *args: Any,
        on_step_kwarg: str = "on_step",
        **kwargs: Any,
    ):
        """
        Args:
            fn:             Función del pipeline a ejecutar.
            *args:          Argumentos posicionales para fn.
            on_step_kwarg:  Nombre del kwarg de callback de progreso en fn.
            **kwargs:       Kwargs adicionales para fn (excepto on_step).
        """
        super().__init__()
        self._fn             = fn
        self._args           = args
        self._kwargs         = kwargs
        self._on_step_kwarg  = on_step_kwarg

    def run(self) -> None:
        """Ejecutado en el hilo secundario."""
        try:
            # Inyectar callback de progreso si la función lo acepta
            self._kwargs[self._on_step_kwarg] = self._emit_step
            result = self._fn(*self._args, **self._kwargs)
            self.done_signal.emit(result)
        except TypeError:
            # La función no acepta on_step — reintentar sin él
            self._kwargs.pop(self._on_step_kwarg, None)
            try:
                result = self._fn(*self._args, **self._kwargs)
                self.done_signal.emit(result)
            except Exception as exc:
                self.error_signal.emit(str(exc))
        except Exception as exc:
            self.error_signal.emit(str(exc))

    def _emit_step(self, msg: str) -> None:
        self.step_signal.emit(msg)


class SimpleWorker(QThread):
    """
    Worker mínimo para funciones sin callback de progreso.

    Uso:
        worker = SimpleWorker(lambda: mi_funcion(arg1, arg2))
        worker.done_signal.connect(on_done)
        worker.error_signal.connect(on_error)
        worker.start()
    """

    done_signal  = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.done_signal.emit(result)
        except Exception as exc:
            self.error_signal.emit(str(exc))
