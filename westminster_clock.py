"""Reloj analógico Westminster con sonidos y barra de progreso.

Este módulo crea una interfaz gráfica con un reloj analógico que reproduce
el carillón Westminster en los cuartos de hora y emite un sonido de
"tic-tac" cada segundo. Debe ejecutarse en un entorno con soporte para
Tkinter.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as exc:  # pragma: no cover - Tkinter es requisito de ejecución
    raise RuntimeError("Tkinter es necesario para ejecutar este reloj") from exc


Note = Tuple[float, int]


@dataclass(frozen=True)
class Phrase:
    """Representa una frase musical compuesta por notas."""

    name: str
    notes: Tuple[Note, ...]


class SoundPlayer:
    """Reproduce tonos simples utilizando distintas salidas de audio."""

    def __init__(self, bell_callback: Optional[Callable[[], None]] = None) -> None:
        self._backend = None
        self._wave_cache: Dict[Tuple[float, int], object] = {}
        self._bell_callback = bell_callback

        try:  # Preferimos simpleaudio por su portabilidad
            import simpleaudio as sa  # type: ignore

            self._backend = ("simpleaudio", sa)
            self._sample_rate = 44100
        except Exception:
            try:  # Windows cuenta con winsound
                import winsound  # type: ignore

                self._backend = ("winsound", winsound)
            except Exception:
                # Último recurso: el timbre del sistema (puede ser silencioso en
                # algunos entornos, pero es preferible a fallar por completo).
                self._backend = ("bell", None)

    # ------------------------------------------------------------------
    def play_tone(self, frequency: float, duration_ms: int, volume: float = 0.4) -> None:
        """Reproduce un tono simple sincrónicamente."""

        backend, handler = self._backend

        if backend == "simpleaudio":
            sa = handler
            wave_obj = self._wave_cache.get((frequency, duration_ms))
            if wave_obj is None:
                wave_obj = self._create_wave(sa, frequency, duration_ms, volume)
                self._wave_cache[(frequency, duration_ms)] = wave_obj
            play_obj = wave_obj.play()
            play_obj.wait_done()
        elif backend == "winsound":
            handler.Beep(int(frequency), int(duration_ms))  # type: ignore[attr-defined]
        else:  # backend bell
            if self._bell_callback:
                try:
                    self._bell_callback()
                except Exception:
                    pass
            time.sleep(duration_ms / 1000.0)

    # ------------------------------------------------------------------
    def play_tone_async(self, frequency: float, duration_ms: int, volume: float = 0.4) -> None:
        threading.Thread(
            target=self.play_tone,
            args=(frequency, duration_ms, volume),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    def play_sequence(self, notes: Iterable[Note], pause_ms: int = 60) -> None:
        """Reproduce una secuencia de notas en un hilo aparte."""

        sequence: List[Note] = list(notes)
        if not sequence:
            return

        def runner() -> None:
            for frequency, duration in sequence:
                self.play_tone(frequency, duration)
                time.sleep(pause_ms / 1000.0)

        threading.Thread(target=runner, daemon=True).start()

    # ------------------------------------------------------------------
    def play_tick(self, is_tock: bool = False) -> None:
        """Reproduce un sonido breve que simula un "tic" o "tac"."""

        base_freq = 800 if is_tock else 1000
        self.play_tone_async(base_freq, 80, volume=0.3)

    # ------------------------------------------------------------------
    def _create_wave(self, sa_module: object, frequency: float, duration_ms: int, volume: float):
        import math as _math
        from array import array

        sample_rate = self._sample_rate
        num_samples = max(1, int(sample_rate * duration_ms / 1000))
        amplitude = int(32767 * max(0.0, min(volume, 1.0)))

        data = array(
            "h",
            (
                int(amplitude * _math.sin(2 * _math.pi * frequency * i / sample_rate))
                for i in range(num_samples)
            ),
        )

        # Atenúa los últimos 5 ms para evitar clics bruscos.
        fade_samples = min(num_samples, int(sample_rate * 0.005))
        for i in range(fade_samples):
            factor = (fade_samples - i) / fade_samples
            data[-(i + 1)] = int(data[-(i + 1)] * factor)

        wave_obj = sa_module.WaveObject(data.tobytes(), 1, 2, sample_rate)  # type: ignore[attr-defined]
        return wave_obj


class WestminsterClock:
    """Reloj Westminster con carillón y barra de progreso de la hora."""

    CLOCK_SIZE = 420
    CLOCK_RADIUS = 190

    HOUR_HAND = CLOCK_RADIUS * 0.55
    MINUTE_HAND = CLOCK_RADIUS * 0.75
    SECOND_HAND = CLOCK_RADIUS * 0.85

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Reloj Westminster")

        self.sound_player = SoundPlayer(bell_callback=self.root.bell)

        self.canvas = tk.Canvas(
            self.root,
            width=self.CLOCK_SIZE,
            height=self.CLOCK_SIZE,
            bg="#f4f4f4",
            highlightthickness=0,
        )
        self.canvas.pack(padx=16, pady=(16, 8))

        self.time_label = tk.Label(
            self.root,
            font=("Helvetica", 18, "bold"),
            text="",
            fg="#222",
        )
        self.time_label.pack(pady=(0, 10))

        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=320, mode="determinate")
        self.progress.configure(maximum=3600)
        self.progress.pack(pady=(0, 16))

        self._tick_state = False
        self._last_second: Optional[int] = None
        self._last_chime: Optional[datetime] = None

        self._create_clock_face()
        self._create_hands()
        self._setup_phrases()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _create_clock_face(self) -> None:
        center = self.CLOCK_SIZE // 2
        radius = self.CLOCK_RADIUS

        # Borde del reloj
        self.canvas.create_oval(
            center - radius,
            center - radius,
            center + radius,
            center + radius,
            fill="#ffffff",
            outline="#333",
            width=4,
        )

        # Marcas de minutos y horas
        for minute in range(60):
            angle = math.radians(minute * 6 - 90)
            outer = radius - 6
            inner = radius - (22 if minute % 5 == 0 else 14)
            width = 3 if minute % 5 == 0 else 1

            x_outer = center + outer * math.cos(angle)
            y_outer = center + outer * math.sin(angle)
            x_inner = center + inner * math.cos(angle)
            y_inner = center + inner * math.sin(angle)
            self.canvas.create_line(x_inner, y_inner, x_outer, y_outer, width=width, fill="#333")

        # Números de horas
        for hour in range(1, 13):
            angle = math.radians(hour * 30 - 90)
            x = center + (radius - 48) * math.cos(angle)
            y = center + (radius - 48) * math.sin(angle)
            self.canvas.create_text(x, y, text=str(hour), font=("Helvetica", 18, "bold"), fill="#111")

    # ------------------------------------------------------------------
    def _create_hands(self) -> None:
        center = self.CLOCK_SIZE // 2

        self.hour_hand = self.canvas.create_line(center, center, center, center - self.HOUR_HAND, width=6, fill="#222")
        self.minute_hand = self.canvas.create_line(center, center, center, center - self.MINUTE_HAND, width=4, fill="#444")
        self.second_hand = self.canvas.create_line(center, center, center, center - self.SECOND_HAND, width=2, fill="#c0392b")

        # Centro decorativo
        self.canvas.create_oval(
            center - 8,
            center - 8,
            center + 8,
            center + 8,
            fill="#444",
            outline="",
        )

    # ------------------------------------------------------------------
    def _setup_phrases(self) -> None:
        g4 = 392.0
        c5 = 523.25
        d5 = 587.33
        e5 = 659.25

        duration = 550

        self.phrases: Dict[str, Phrase] = {
            "A": Phrase("A", ((g4, duration), (c5, duration), (d5, duration), (e5, duration + 150))),
            "B": Phrase("B", ((e5, duration), (d5, duration), (c5, duration), (g4, duration + 150))),
            "C": Phrase("C", ((g4, duration), (d5, duration), (e5, duration), (c5, duration + 150))),
            "D": Phrase("D", ((c5, duration), (e5, duration), (d5, duration), (g4, duration + 150))),
        }

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._schedule_update()
        self.root.mainloop()

    # ------------------------------------------------------------------
    def _schedule_update(self) -> None:
        self._update_clock()
        self.root.after(120, self._schedule_update)

    # ------------------------------------------------------------------
    def _update_clock(self) -> None:
        now = datetime.now()
        center = self.CLOCK_SIZE // 2

        second_fraction = now.second + now.microsecond / 1_000_000
        minute_fraction = now.minute + second_fraction / 60
        hour_fraction = (now.hour % 12) + minute_fraction / 60

        self._set_hand_position(self.second_hand, self.SECOND_HAND, second_fraction * 6, center)
        self._set_hand_position(self.minute_hand, self.MINUTE_HAND, minute_fraction * 6, center)
        self._set_hand_position(self.hour_hand, self.HOUR_HAND, hour_fraction * 30, center)

        self.time_label.config(text=now.strftime("%H:%M:%S"))
        progress_value = now.minute * 60 + now.second + now.microsecond / 1_000_000
        self.progress.configure(value=progress_value)

        self._handle_tick(now)
        self._handle_chime(now)

    # ------------------------------------------------------------------
    def _set_hand_position(self, hand_id: int, length: float, angle_deg: float, center: int) -> None:
        angle = math.radians(angle_deg - 90)
        x_end = center + length * math.cos(angle)
        y_end = center + length * math.sin(angle)
        self.canvas.coords(hand_id, center, center, x_end, y_end)

    # ------------------------------------------------------------------
    def _handle_tick(self, now: datetime) -> None:
        if self._last_second is None or now.second != self._last_second:
            self.sound_player.play_tick(self._tick_state)
            self._tick_state = not self._tick_state
            self._last_second = now.second

    # ------------------------------------------------------------------
    def _handle_chime(self, now: datetime) -> None:
        if now.second != 0:
            return

        if now.minute % 15 != 0:
            return

        if self._last_chime and now - self._last_chime < timedelta(seconds=50):
            return

        quarter = 4 if now.minute == 0 else now.minute // 15
        self._play_westminster_chime(quarter, now.hour)
        self._last_chime = now

    # ------------------------------------------------------------------
    def _play_westminster_chime(self, quarter: int, hour: int) -> None:
        phrases_order = {
            1: ["A"],
            2: ["B", "A"],
            3: ["C", "A", "B"],
            4: ["D", "B", "C", "A"],
        }

        selected = phrases_order.get(quarter, [])
        sequence: List[Note] = []
        for key in selected:
            phrase = self.phrases[key]
            sequence.extend(phrase.notes)

        pause_between = 80

        if quarter == 4:
            strikes = hour % 12 or 12
            strike_note: Note = (392.0, 700)  # Aproximación del tono de la gran campana
            for _ in range(strikes):
                sequence.append(strike_note)
            pause_between = 140

        filtered_sequence = [(freq, dur) for freq, dur in sequence if dur > 0 and freq > 0]
        self.sound_player.play_sequence(filtered_sequence, pause_ms=pause_between)

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        self.root.destroy()


def main() -> None:
    clock = WestminsterClock()
    clock.start()


if __name__ == "__main__":
    try:
        main()
    except tk.TclError as exc:
        print("No se pudo iniciar la interfaz gráfica:", exc, file=sys.stderr)
