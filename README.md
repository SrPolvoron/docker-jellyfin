# Jellyfin Home Stack · SrPolvoron

Tu biblioteca de películas y series en **Debian con Docker Compose**: reproducción
con Jellyfin, descubrimiento/solicitudes con Seerr, subtítulos con Bazarr y descargas
con Radarr, Sonarr, Prowlarr y qBittorrent. Acceso con cuentas propias por HTTPS desde un Traefik en
OVH, conectado a casa mediante WireGuard. Kubernetes queda para tus otros proyectos.

## Arquitectura fijada

| Ubicación | Servicios | Acceso |
|---|---|---|
| Debian de casa | Jellyfin, Seerr | Primero localhost; después también IP WireGuard |
| Debian de casa | Radarr, Sonarr, Prowlarr, Bazarr, qBittorrent | Localhost y túnel SSH |
| OVH | Traefik existente o Compose opcional incluido | 80/443 públicos |
| Ambos hosts | WireGuard del sistema | Un túnel privado con rutas /32 |

El DNS público apunta a OVH. HTTPS termina allí y el tráfico HTTP hasta casa viaja
cifrado dentro de WireGuard. El contenido y las configuraciones permanecen en casa.
Todo el vídeo remoto pasa por OVH: cuenta la subida doméstica y el tráfico del VPS.

Decisiones: dos subdominios; autenticación nativa; catálogo compartido con progreso
individual y bibliotecas privadas opcionales; configuración inicial manual de las
aplicaciones; imágenes fijadas por digest; administración por SSH. No se crea un
reproductor propio, ni se modifica Debian, ni se instala Kubernetes. Supuestos:
disco local para appdata, conexión saliente UDP a OVH y acceso administrativo SSH.
Una avería de casa interrumpe la reproducción; OVH no guarda una réplica de vídeos.

## Requisitos

- Debian, arquitectura amd64 o arm64, Python **3.10+**, `tzdata`, `iproute2` y SSH.
- Docker Engine **28+** y Docker Compose **2.24+**, instalados siguiendo la
  [guía de Docker para Debian](https://docs.docker.com/engine/install/debian/).
  Se recomienda Engine 28+ por las correcciones de aislamiento de puertos localhost.
- Usuario con acceso al daemon Docker. Ese permiso equivale a administración del host.
- Espacio para contenido y caché. Los límites de RAM incluidos son máximos, no
  reservas; ajústalos a tu equipo. La transcodificación depende de CPU/GPU y formatos.
- Dos subdominios propios y OVH con 80/443 disponibles o un Traefik ya funcionando.
- WireGuard entre los hosts; configuración de ejemplo en `examples/wireguard/`.

## 1. Arranque privado en casa

Descomprime el proyecto en una carpeta propia, por ejemplo
`~/github_srpolvoron/jellyfin-home-stack`. Ejecuta desde ella:

```bash
chmod +x stack
./stack init
id -u
id -g
nano .env
./stack check
sudo ./stack prepare
./stack lock
./stack config
./stack up
./stack status
```

Pon tus UID/GID reales en `.env`; no uses 0. Ajusta rutas, IP del túnel, interfaz y
dominios. Los valores son literales: sin comillas, espacios o variables de shell.
`prepare` crea los directorios y asigna propietarios solo a los nuevos: **no hace
chown recursivo ni modifica datos ya existentes**. Si encuentra otro propietario,
se detiene para que revises esa ruta. Si el contenido está en otro disco, móntalo
antes y comprueba `findmnt -T /srv/media`; appdata debe estar en almacenamiento local.

`lock` descarga los canales estables indicados en `.env` y guarda sus digests en
`images.lock.env`. `up` usa exclusivamente esos digests. Ejecutar `lock` otra vez
conserva los existentes; `--refresh` es una actualización deliberada.

Desde tu ordenador abre un túnel SSH al servidor de casa (usa tu alias SSH):

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 8096:127.0.0.1:8096 -L 5055:127.0.0.1:5055 \
  -L 7878:127.0.0.1:7878 -L 8989:127.0.0.1:8989 \
  -L 9696:127.0.0.1:9696 -L 6767:127.0.0.1:6767 \
  -L 8080:127.0.0.1:8080 casa
```

| Aplicación | Dirección en tu ordenador |
|---|---|
| Jellyfin | http://localhost:8096 |
| Seerr | http://localhost:5055 |
| Radarr | http://localhost:7878 |
| Sonarr | http://localhost:8989 |
| Prowlarr | http://localhost:9696 |
| Bazarr | http://localhost:6767 |
| qBittorrent | http://localhost:8080 |

## 2. Cuentas, bibliotecas y descargas

Sigue [docs/CONFIGURACION.md](docs/CONFIGURACION.md): incluye los campos exactos
para conectar las siete aplicaciones. Primero termina los asistentes, configura
contraseñas y prueba las conexiones. Las API keys se copian entre las interfaces;
no se añaden a Git ni a este proyecto.

Jellyfin administra usuarios y permisos. Seerr puede reutilizar sus credenciales,
con sesión propia. Una solicitud descarga al catálogo compartido: **no genera una
biblioteca privada del solicitante**. Para privacidad, crea carpetas/bibliotecas
separadas y asigna el acceso explícitamente en Jellyfin.

## 3. WireGuard y publicación

Sigue [docs/ACCESO_OVH.md](docs/ACCESO_OVH.md) para levantar el túnel y configurar
el Traefik existente o el opcional incluido. No abras los puertos de aplicaciones
en el router doméstico. El túnel conecta casa con OVH; las descargas usan la conexión
normal de casa, sin proveedor VPN de salida. qBittorrent funciona como nodo pasivo;
no se publican puertos P2P por defecto.

Una vez creadas las cuentas y verificado el túnel, en casa:

```bash
./stack config --public
./stack up --public --accounts-configured
./stack edge-config --accounts-configured
```

La opción `--accounts-configured` es tu declaración de que has terminado el
bootstrap; **no inspecciona las contraseñas ni sustituye la prueba de login**.
El arranque comprueba que `HOME_WG_IP` está en `WG_INTERFACE` y rechaza dominios
de ejemplo. El overlay conserva localhost y añade solo Jellyfin/Seerr en la IP
privada del túnel. Copia `edge/dynamic/media.yml` al proveedor file de OVH.

Desde entonces:

- `https://cine.tudominio.es`: ver tu contenido con tu cuenta de Jellyfin.
- `https://peticiones.tudominio.es`: buscar y solicitar, con las cuentas autorizadas.
- Administración de descargas: el mismo túnel SSH, sin nuevos subdominios públicos.

Mantén `--public` en las siguientes ejecuciones de `up`; omitirlo retira el acceso
por WireGuard y conserva el privado. Para administrar desde casa también puedes
usar los subdominios de OVH; el acceso LAN directo queda cerrado por defecto.

## Operación, copias y actualización

```bash
./stack status
./stack logs --service jellyfin
./stack down
# Recuperar tras down conservando datos y acceso público:
./stack up --public --accounts-configured
```

Una copia consistente de **configuraciones, cuentas y metadatos** detiene brevemente
los servicios que estaban activos y vuelve a arrancarlos, sin recrearlos:

```bash
sudo ./stack backup --output /srv/backups/media-2026-10-13.tar.gz
```

La copia tiene permisos 0600 y contiene API keys/configuraciones: guárdala cifrada
fuera del servidor. **No incluye vídeos, descargas, caché ni certificados de OVH**;
copia estos por separado si quieres recuperarlos. No se sobrescribe un backup existente.
Si el proceso recibe SIGKILL o se apaga el host, revisa `./stack status` y reinicia
los servicios. Guarda también tus configuraciones WireGuard de forma privada.

Para actualizar: haz backup, revisa cambios de los proyectos originales y, si quieres
versiones concretas, cambia `*_SOURCE_IMAGE` a sus tags antes de resolver:

```bash
./stack lock --refresh
./stack config --public
./stack up --public --accounts-configured
```

El lock anterior queda en `images.lock.env.previous`. Para rollback copia ese lock
y recrea los servicios **solo si sus bases de datos siguen siendo compatibles**.
Si hubo migración, restaura también appdata del backup previo. Extrae la copia a un
directorio temporal privado, comprueba su contenido, detén el stack y restaura las
carpetas de `appdata/`, `.env` y el lock en sus rutas originales; conserva UID/GID.
No extraigas archivos no fiables directamente sobre el sistema. No hay actualizaciones
automáticas ni un comando que borre contenido.

### Incorporar Bazarr a una instalación existente

Después de actualizar el repositorio, añade a tu `.env` si aún no existe:

```text
BAZARR_SOURCE_IMAGE=lscr.io/linuxserver/bazarr:latest
```

Conservando el acceso público actual, crea el directorio, resuelve únicamente la
imagen nueva y aplica el Compose:

```bash
sudo ./stack prepare
./stack lock
./stack config --public
./stack up --public --accounts-configured
./stack status
```

Bazarr queda en `127.0.0.1:6767`; no se publica mediante Traefik ni WireGuard.

## GPU opcional y Kubernetes

La base funciona sin dispositivos GPU. Para un render node Intel/AMD compatible,
comprueba `ls -l /dev/dri/renderD128` y `stat -c %g /dev/dri/renderD128`; añade el GID
real como `RENDER_GID` en `.env`. Usa `./stack up --intel` (añade también `--public
--accounts-configured` si publicas). Activa VA-API/QSV según tu GPU en Jellyfin y
prueba una reproducción que transcodifique. NVIDIA requiere otra configuración
según hardware; no se habilita a ciegas.

Puedes añadir K3s en una VM KVM/libvirt sobre este mismo Debian cuando quieras.
La instalación y las redes de ese laboratorio son independientes del stack.

## Comprobación y estado de entrega

```bash
python3 -m unittest discover -s tests -v
# Opcional para la comprobación estática de YAML: sudo apt install python3-yaml
python3 tests/check_compose.py
./stack config
./stack config --public
```

[docs/VALIDACION.md](docs/VALIDACION.md) distingue la validación local ejecutada de
las pruebas obligatorias de arranque, login, HTTPS y descargas en tus servidores.
Deuda aceptada: integración inicial manual, elección del hardware pendiente y sin
HA. Si añades más usuarios, controla espacio, permisos de solicitudes y consumo de
transcodificación; si crece el servicio, revisa límites y estrategia de recuperación.

Este repositorio contiene configuración y herramientas MIT. Cada aplicación mantiene
su licencia propia. No contiene contenido multimedia ni credenciales de fuentes.
