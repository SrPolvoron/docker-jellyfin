# Jellyfin Home Stack · SrPolvoron

Stack multimedia privado para Debian mediante Docker Compose: reproducción con
Jellyfin, solicitudes con Seerr, automatización con Radarr/Sonarr, gestión de
indexadores con Prowlarr y subtítulos con Bazarr. Las descargas las proporciona el
proyecto separado `docker-qbittorrent` a través de una red Docker externa privada.
El tráfico público de Jellyfin y Seerr termina en Traefik en OVH y llega al servidor
doméstico mediante WireGuard.

[Read in English](../README.md)

## Arquitectura

| Ubicación/proyecto | Servicios | Exposición |
| --- | --- | --- |
| Este stack doméstico | Jellyfin, Seerr | Loopback; opcionalmente IP WireGuard de casa y Traefik en OVH |
| Este stack doméstico | Radarr, Sonarr, Prowlarr, Bazarr | Loopback; opcionalmente la IP WireGuard de casa |
| `docker-qbittorrent` | qBittorrent | Su propia política loopback/WireGuard en el puerto 8081 |
| OVH | Traefik existente o Compose opcional incluido | Solo 80/443 públicos |

Solo Radarr y Sonarr entran en la red externa `media-downloads`. Acceden al cliente
como `qbittorrent-standalone:8081`. Ambos proyectos montan el mismo `DATA_ROOT` del
host como `/data`, por lo que las rutas coinciden y las importaciones pueden usar
hardlinks sin Remote Path Mappings:

```text
/srv/media                     -> /data
├── torrents/standalone/movies -> descargas de Radarr
├── torrents/standalone/tv     -> descargas de Sonarr
└── media
    ├── movies                 -> biblioteca de películas de Jellyfin
    └── tv                     -> biblioteca de series de Jellyfin
```

Este repositorio no define, inicia, detiene, actualiza, publica ni respalda
qBittorrent. Su appdata pertenece de forma independiente a `docker-qbittorrent`.

## Contrato de persistencia

Estos directorios del host contienen el estado que debe conservarse:

```text
/srv/jellyfin-home/appdata/jellyfin
/srv/jellyfin-home/appdata/seerr
/srv/jellyfin-home/appdata/radarr
/srv/jellyfin-home/appdata/sonarr
/srv/jellyfin-home/appdata/prowlarr
/srv/jellyfin-home/appdata/bazarr
```

Actualizar el repositorio no renombra, vacía ni recrea esos directorios. `prepare`
solo crea rutas ausentes y se niega a apropiarse de un directorio existente con otro
propietario. Los backups incluyen esos seis appdata, `.env` e `images.lock.env`;
excluyen multimedia, descargas y caché.

## Requisitos

- Debian u otro host Linux, Python 3.10+, Docker Engine 28+ y Compose 2.24+.
- Un PUID/PGID no root idéntico en ambos proyectos.
- Appdata local y una raíz de datos compartida, normalmente `/srv/media`.
- El qBittorrent independiente desplegado primero con su overlay `--media`.
- SSH; opcionalmente WireGuard en el host y dos dominios para Jellyfin/Seerr.

## Instalación limpia

Configura primero el proyecto qBittorrent independiente. Su `.env` debe usar el
mismo PUID, PGID, directorio de datos y nombre de red externa que este proyecto:

```dotenv
PUID=1000
PGID=1000
DATA_ROOT=/srv/media
SHARED_NETWORK=media-downloads
WEBUI_PORT=8081
```

Desde el repositorio qBittorrent:

```bash
./stack check
sudo ./stack prepare
./stack lock
./stack network-create
./stack up --media
# Usa --media --vpn si su interfaz también debe escuchar en WireGuard.
```

Cambia su contraseña temporal y ejecuta allí `./stack categories`. Después inicia
este repositorio:

```bash
chmod +x stack
./stack init
nano .env
./stack check
sudo ./stack prepare
./stack lock
./stack config
./stack up
./stack status
```

Configura los mismos valores en el `.env` de este proyecto:

```dotenv
PUID=1000
PGID=1000
DATA_ROOT=/srv/media
SHARED_NETWORK=media-downloads
```

Antes de `up`, la herramienta comprueba que la red externa sea un bridge Docker,
que existan las carpetas independientes de películas/series con el propietario
esperado y que no quede un contenedor qBittorrent antiguo en este proyecto Compose.

## Migración segura desde el antiguo qBittorrent integrado

Es una separación intencionada del servicio. Jellyfin, Seerr, Radarr, Sonarr,
Prowlarr y Bazarr conservan su appdata actual. La migración no necesita conservar
multimedia ni payloads torrent, pero no los borres hasta probar el nuevo flujo.

Ejecuta estos comandos desde el **repositorio antiguo actualmente desplegado**,
antes de copiar los archivos actualizados:

```bash
cd /ruta/al/jellyfin-home-stack-actual
sudo mkdir -p /srv/backups/jellyfin
sudo ./stack backup --output /srv/backups/jellyfin/before-qbittorrent-split.tar.gz
./stack down
sudo tar -tzf /srv/backups/jellyfin/before-qbittorrent-split.tar.gz
```

El `down` antiguo elimina contenedores y redes Compose, pero conserva appdata,
descargas y multimedia montados desde el host. El archivo previo también contiene
la configuración del qBittorrent antiguo porque se generó con la versión anterior.

Después:

1. Despliega `docker-qbittorrent` con `DATA_ROOT=/srv/media`, su propio
   `CONFIG_ROOT=/srv/qbittorrent/config` y `SHARED_NETWORK=media-downloads`.
2. Ejecuta allí `prepare`, `lock`, `network-create`, `up --media` y `categories`.
3. Sustituye únicamente los archivos versionados de este repositorio. Conserva el
   `.env` y `images.lock.env` existentes.
4. Añade `SHARED_NETWORK=media-downloads` al `.env`. Las líneas antiguas
   `QBITTORRENT_SOURCE_IMAGE` y `QBITTORRENT_IMAGE` pueden permanecer temporalmente:
   se aceptan por compatibilidad, pero no se usan.
5. Ejecuta `check`, `prepare`, `lock`, `config` y `up` como en la instalación.
6. En Radarr y Sonarr, edita el cliente qBittorrent existente:

   | Campo | Valor |
   | --- | --- |
   | Host | `qbittorrent-standalone` |
   | Puerto | `8081` |
   | SSL | Desactivado |
   | Categoría | `movies` en Radarr; `tv` en Sonarr |
   | Credenciales | Las del nuevo qBittorrent independiente |

   Mantén Remote Path Mappings vacío y pulsa **Test**.

No copies el `/config` del qBittorrent antiguo al nuevo mientras alguna instancia
esté activa. Conserva la carpeta antigua y el backup hasta que una solicitud de
prueba se descargue, importe, aparezca en Jellyfin y obtenga subtítulos correctamente.

## Acceso privado

Abre todos los paneles locales con una conexión SSH:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 8096:127.0.0.1:8096 -L 5055:127.0.0.1:5055 \
  -L 7878:127.0.0.1:7878 -L 8989:127.0.0.1:8989 \
  -L 9696:127.0.0.1:9696 -L 6767:127.0.0.1:6767 \
  -L 8081:127.0.0.1:8081 casa
```

| Aplicación | URL en el portátil |
| --- | --- |
| Jellyfin | `http://127.0.0.1:8096` |
| Seerr | `http://127.0.0.1:5055` |
| Radarr | `http://127.0.0.1:7878` |
| Sonarr | `http://127.0.0.1:8989` |
| Prowlarr | `http://127.0.0.1:9696` |
| Bazarr | `http://127.0.0.1:6767` |
| qBittorrent (proyecto separado) | `http://127.0.0.1:8081` |

Completa las cuentas e integraciones con [CONFIGURACION.md](CONFIGURACION.md).

## WireGuard y acceso público

Sigue [ACCESO_OVH.md](ACCESO_OVH.md). Cuando hayas comprobado las cuentas y el túnel:

```bash
./stack config --public
./stack up --public --accounts-configured
./stack edge-config --accounts-configured
```

El overlay público expone Jellyfin y Seerr en la IP WireGuard doméstica para el proxy
de OVH. El override administrativo añade Radarr, Sonarr, Prowlarr y Bazarr en esa IP
privada. No publica qBittorrent: su proyecto controla su propio listener `--vpn`.
Ningún panel administrativo recibe router Traefik ni subdominio público.

Conserva `--public` en siguientes ejecuciones de `up` para mantener los listeners.

## Backups, actualizaciones y recuperación

Crea un backup consistente de la configuración antes de realizar cambios:

```bash
sudo ./stack backup --output /srv/backups/jellyfin/media-2026-10-14.tar.gz
```

El comando detiene solo los servicios activos de este repositorio, crea un archivo
0600 y reinicia únicamente esos servicios. Respalda qBittorrent desde su propio
repositorio. Guarda ambos archivos cifrados fuera del host: contienen API keys,
sesiones y credenciales de aplicaciones.

Actualiza de forma deliberada:

```bash
./stack lock --refresh
./stack config --public
./stack up --public --accounts-configured
```

Se conserva el lock de imágenes anterior. Volver a una imagen no revierte migraciones
de las bases de datos; restaura el appdata correspondiente cuando sea necesario. No
uses `docker compose down -v`, `--remove-orphans` ni borrados recursivos en esta migración.

## Validación

```bash
python3 -m unittest discover -s tests -v
python3 tests/check_compose.py       # Requiere PyYAML
python3 -m py_compile scripts/stack.py tests/*.py
./stack config
./stack config --public
```

Las pruebas locales validan el parseo de configuración, locks inmutables, límites de
persistencia/backup, redes Compose, binds privados y contrato con el cliente externo.
La confianza de producción requiere arrancar Docker en Debian, probar el cliente de
descargas en Radarr/Sonarr y completar una descarga/importación legal de extremo a extremo.

Consulta [VALIDACION.md](VALIDACION.md) para la lista de aceptación. Este repositorio
usa licencia MIT; cada aplicación conserva su propia licencia.
