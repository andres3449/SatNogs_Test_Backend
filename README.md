# SatNOGS Test Backend — INTISAT

Setup de una estación receptora de [SatNOGS Network](https://network.satnogs.org)
en Windows via Docker Desktop + WSL2, y una herramienta de banco para probar
recepción cruda FSK/GFSK pensando en el futuro satélite propio del proyecto
INTISAT (protocolo custom sobre Si4463/CC1101, aún no lanzado).

Esto es una estación RX de la red pública SatNOGS, no un satélite propio en órbita.

## Contenido

- **`station-intisat/`** — Config de la estación SatNOGS Network:
  - `docker-compose.yml`, tomado de la guía LSF de
    [satnogs-client-docker](https://github.com/kng/satnogs-client-docker)
  - `station.env.example` — plantilla de variables de entorno (ubicación,
    dispositivo RX, etc). Copiar a `station.env` y completar
    `SATNOGS_API_TOKEN` / `SATNOGS_STATION_ID` con los datos de tu Ground
    Station en network.satnogs.org (no se versiona, contiene credenciales)
  - `10-satnogs.rules` / `satnogs-blacklist.conf` — reglas udev y blacklist
    de módulos para que el RTL-SDR/LimeSDR tengan los permisos correctos
    dentro de WSL2

- **`rx-bench/fsk_raw_rx.py`** — Receptor FSK/GFSK standalone, sin
  SatNOGS Network. Extrae la cadena real de demodulación de
  [satnogs-flowgraphs](https://gitlab.com/librespacefoundation/satnogs/satnogs-flowgraphs)
  (corrección de frecuencia, filtro de canal, demod FSK/GFSK, recuperación
  de reloj) quitando todo lo de red/rigctl/AX.25, para volcar bits crudos a
  un archivo y poder buscar a mano el patrón (preámbulo/sync word) de un
  protocolo custom.

## Requisitos

- Docker Desktop for Windows con backend WSL2
- [usbipd-win](https://github.com/dorssel/usbipd-win) para pasar el SDR por
  USB a WSL2
- WSL2 con Ubuntu, más `gnuradio` + `gr-osmosdr` (solo para `rx-bench/`)

## Estado

Estación configurada, pendiente de: cuenta en network.satnogs.org (Station
ID + API Token) y prueba con hardware SDR real conectado.
