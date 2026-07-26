#!/usr/bin/env python3
"""
fsk_raw_rx.py - Recepcion cruda FSK/GFSK, sin SatNOGS Network.

Cadena de demodulacion extraida de satnogs-flowgraphs
(generic/fsk_ax25.grc + hierarchical/fsk_downlink_hier.grc, proyecto oficial
Libre Space Foundation): misma matematica de correccion de frecuencia,
filtro de canal, demodulador FSK/GFSK y recuperacion de reloj que usa la
estacion real. Se quito todo lo que no es recepcion: rigctl/doppler,
ZMQ, waterfall, y el deframer AX.25 (no aplica a un protocolo custom).

Salida: bits crudos empacados en bytes, sin intentar separar paquetes.
Revisa el archivo de salida con `hexdump -C salida.bin | less` buscando
patrones repetidos (preambulo/sync word) de tu protocolo.

Uso:
    python3 fsk_raw_rx.py --freq 435000000 --baudrate 9600 --out salida.bin

Requisitos (WSL2 Ubuntu): gnuradio, gr-osmosdr
"""
import argparse
import math
import os
import sys
import threading
import time

from gnuradio import analog
from gnuradio import blocks
from gnuradio import digital
from gnuradio import filter as gr_filter
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.filter import pfb
from gnuradio.fft import window

try:
    import osmosdr
except ImportError:
    sys.exit("Falta gr-osmosdr. Instala con: sudo apt install gr-osmosdr")

# Muestras por simbolo que entran al recuperador de reloj. El chain
# original de SatNOGS siempre apunta a 2 sps en este punto (omega=2),
# sin importar el baudrate, asi que lo dejamos fijo.
CLOCK_RECOVERY_SPS = 2


class FskRawReceiver(gr.top_block):

    def __init__(self, args):
        super().__init__("fsk_raw_rx")

        baudrate = args.baudrate
        work_rate = baudrate * args.sps  # tasa de trabajo tras el resampler
        narrow_decim = max(1, args.sps // CLOCK_RECOVERY_SPS)

        # --- Fuente SDR ---
        self.src = osmosdr.source(args=args.device_args)
        self.src.set_sample_rate(args.samp_rate)
        self.src.set_center_freq(args.freq - args.lo_offset, 0)
        self.src.set_freq_correction(args.ppm, 0)
        if args.gain is None:
            self.src.set_gain_mode(True, 0)
        else:
            self.src.set_gain_mode(False, 0)
            self.src.set_gain(args.gain, 0)

        # --- Resampler a la tasa de trabajo (baudrate * sps) ---
        self.resampler = pfb.arb_resampler_ccf(work_rate / args.samp_rate)

        # --- Correccion automatica de frecuencia (2 etapas) ---
        # Rama ancha: estima el offset de frecuencia residual (PPM del
        # RTL-SDR, deriva del oscilador, etc.) y genera un tono de
        # correccion con un VCO que se mezcla con la señal retrasada.
        relaxed_taps = firdes.low_pass(1, work_rate, baudrate * 1.25,
                                        baudrate / 2.0, window.WIN_HAMMING)
        self.relaxed_lpf = gr_filter.fir_filter_ccf(1, relaxed_taps)
        self.coarse_demod = analog.quadrature_demod_cf(1.0)
        self.freq_est = blocks.moving_average_ff(1024, 1.0 / 1024, 4096)
        self.vco = blocks.vco_c(work_rate, -work_rate, 1.0)
        self.delay = blocks.delay(gr.sizeof_gr_complex, 1024 // 2)
        self.mixer = blocks.multiply_cc(1)

        # --- Filtro de canal (ancho de banda ajustado al baudrate) ---
        narrow_taps = firdes.low_pass(1, work_rate, 0.625 * baudrate,
                                       baudrate / 8.0, window.WIN_HAMMING)
        self.channel_lpf = gr_filter.fir_filter_ccf(narrow_decim, narrow_taps)

        # --- Demodulacion FSK/GFSK + recuperacion de reloj ---
        self.fine_demod = analog.quadrature_demod_cf(1.2)
        self.dc_blocker = gr_filter.dc_blocker_ff(1024, True)
        self.clock_recovery = digital.clock_recovery_mm_ff(
            omega=float(CLOCK_RECOVERY_SPS),
            gain_omega=2 * math.pi / 100,
            mu=0.5,
            gain_mu=0.5 / 8.0,
            omega_relative_limit=0.01)
        self.slicer = digital.binary_slicer_fb()

        # --- Empaquetado a bytes crudos + volcado a archivo ---
        self.pack = blocks.pack_k_bits_bb(8)
        self.sink = blocks.file_sink(gr.sizeof_char, args.out, False)
        self.sink.set_unbuffered(True)

        # --- Conexiones ---
        self.connect(self.src, self.resampler)

        self.connect(self.resampler, self.relaxed_lpf)
        self.connect(self.relaxed_lpf, self.coarse_demod, self.freq_est,
                     self.vco)
        self.connect(self.relaxed_lpf, self.delay)
        self.connect(self.delay, (self.mixer, 0))
        self.connect(self.vco, (self.mixer, 1))

        self.connect(self.mixer, self.channel_lpf, self.fine_demod,
                     self.dc_blocker, self.clock_recovery, self.slicer,
                     self.pack, self.sink)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--freq", type=float, required=True,
                    help="Frecuencia central del satelite en Hz (ej. 435000000)")
    p.add_argument("--baudrate", type=float, required=True,
                    help="Baudrate del protocolo (ej. 9600 para Si4463/CC1101 tipico)")
    p.add_argument("--samp-rate", type=float, default=2.4e6,
                    help="Sample rate del SDR (default 2.4e6, tipico RTL-SDR)")
    p.add_argument("--sps", type=int, default=8,
                    help="Sobremuestreo interno antes del filtro de canal (default 8, debe ser par)")
    p.add_argument("--gain", type=float, default=None,
                    help="Ganancia RF en dB. Si se omite, usa AGC automatico")
    p.add_argument("--ppm", type=float, default=0.0,
                    help="Correccion de frecuencia del SDR en PPM")
    p.add_argument("--lo-offset", type=float, default=100e3,
                    help="Desplazamiento del LO para evitar el pico DC (default 100kHz)")
    p.add_argument("--device-args", default="rtl=0",
                    help="Argumentos de dispositivo osmosdr (default 'rtl=0'; "
                         "para LimeSDR probar 'driver=lime' o 'soapy=driver=lime,soapy=0')")
    p.add_argument("--out", default="raw_bits.bin",
                    help="Archivo de salida con los bytes crudos empacados")
    p.add_argument("--duration", type=float, default=None,
                    help="Segundos a correr. Si se omite, corre hasta Ctrl+C")
    return p.parse_args()


def _print_progress(out_path, stop_event):
    last = 0
    while not stop_event.is_set():
        time.sleep(1.0)
        try:
            size = os.path.getsize(out_path)
        except OSError:
            size = 0
        print(f"[{time.strftime('%H:%M:%S')}] bytes recibidos: {size} "
              f"(+{size - last}/s)")
        last = size


def main():
    args = parse_args()
    if args.sps % CLOCK_RECOVERY_SPS != 0:
        sys.exit(f"--sps debe ser multiplo de {CLOCK_RECOVERY_SPS}")

    tb = FskRawReceiver(args)

    stop_event = threading.Event()
    progress = threading.Thread(target=_print_progress,
                                 args=(args.out, stop_event), daemon=True)

    print(f"Sintonizando {args.freq/1e6:.4f} MHz, baudrate={args.baudrate}, "
          f"device={args.device_args!r} -> {args.out}")
    tb.start()
    progress.start()
    try:
        if args.duration:
            time.sleep(args.duration)
        else:
            input("Recibiendo... Enter o Ctrl+C para detener.\n")
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        tb.stop()
        tb.wait()
        print(f"Listo. Bytes crudos en: {args.out}")


if __name__ == "__main__":
    main()
