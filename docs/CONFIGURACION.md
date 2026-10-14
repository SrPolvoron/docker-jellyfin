# Configuración de las aplicaciones

Completa todos los pasos por el túnel SSH antes de publicar. Los nombres de los
servicios funcionan por DNS interno de Docker; `localhost` dentro de un contenedor
se refiere a ese contenedor, no a las demás aplicaciones.

## Jellyfin

1. Crea `media-admin` con una contraseña robusta para administración.
2. Termina el asistente y crea una cuenta normal para tu uso diario. Oculta la
   cuenta administradora en la pantalla de login y mantén contraseñas en todas.
3. Añade biblioteca **Películas** → `/media/movies` y **Series** → `/media/tv`.
4. En cada usuario autoriza las bibliotecas necesarias; quita «acceso a todas»
   para los usuarios restringidos. Desactiva borrado de contenido y administración
   en cuentas normales. El bind multimedia de este proyecto también es de solo lectura.
5. Permite conexiones remotas a los usuarios que usarán el subdominio. Conserva
   el bloqueo por intentos de login fallidos. No configures acceso sin contraseña.
6. En red, deja Base URL vacío y añade `OVH_WG_IP` a **Known Proxies** para confiar
   únicamente en tu proxy. Verifica la IP que realmente ve el contenedor en tu
   montaje: no autorices toda Internet ni todas las redes Docker.
7. Tras publicación verifica «continuar viendo», progreso y acceso desde dos cuentas.

Para biblioteca privada: crea una carpeta dentro de `DATA_ROOT/media`, con el mismo
UID/GID y permisos, añade una biblioteca específica y da acceso solo a su propietario.
No incluyas esa carpeta en otra biblioteca compartida. Los administradores del servidor
siguen teniendo acceso. La cuenta no crea carpetas ni catálogos automáticamente.

## qBittorrent independiente

qBittorrent pertenece al repositorio separado `docker-qbittorrent`. En su `.env`
debe compartir estos valores con este despliegue:

```dotenv
PUID=1000                     # El mismo valor real en ambos proyectos
PGID=1000                     # El mismo valor real en ambos proyectos
DATA_ROOT=/srv/media          # El mismo DATA_ROOT de este proyecto
SHARED_NETWORK=media-downloads
WEBUI_PORT=8081
```

Desde ese repositorio ejecuta `./stack prepare`, `./stack network-create` y
`./stack up --media` (añade `--vpn` si quieres su interfaz en WireGuard). Después
de cambiar la contraseña temporal, ejecuta allí `./stack categories`. Esto crea:

| Categoría | Ruta común dentro de los contenedores |
|---|---|
| `movies` | `/data/torrents/standalone/movies` |
| `tv` | `/data/torrents/standalone/tv` |
| Incompletas | `/data/torrents/standalone/incomplete` |

Mantén protección CSRF, validación de Host y autenticación. Si limitas los dominios
admitidos de la interfaz, permite `qbittorrent-standalone`, `localhost` y
`127.0.0.1`; no desactives globalmente esas protecciones. La administración y los
límites de siembra se gestionan exclusivamente en el proyecto qBittorrent.

## Radarr y Sonarr

En ambos, configura autenticación **Forms** o la opción equivalente de la versión
instalada, contraseña y autenticación requerida también en direcciones locales.
Las API keys se encuentran en Settings → General. Deja URL Base vacío.

| Campo | Radarr | Sonarr |
|---|---|---|
| Carpeta raíz | `/data/media/movies` | `/data/media/tv` |
| Download Client | qBittorrent | qBittorrent |
| Host del cliente | `qbittorrent-standalone` | `qbittorrent-standalone` |
| Puerto del cliente | `8081` | `8081` |
| SSL interno | Desactivado | Desactivado |
| Usuario/contraseña | Los que configuraste en qBittorrent | Los mismos |
| Categoría | `movies` | `tv` |

Prueba el cliente con **Test**, activa Completed Download Handling y selecciona un
perfil de calidad/idioma que se ajuste al espacio disponible y a tus dispositivos.
No configures Remote Path Mappings: los tres contenedores ven el mismo `DATA_ROOT`
del host como `/data`, aunque pertenezcan a proyectos Compose diferentes.

Activa «Use Hardlinks instead of Copy» si descargas y biblioteca están en el mismo
filesystem; `/data` es un único bind en Radarr/Sonarr. Dos discos, submontajes o
datasets distintos pueden impedir hardlinks: en ese caso habrá copia y doble ocupación.
No borres torrents o descargas que quieras seguir sembrando; establece tu política
de ratio/tiempo en el cliente y comprueba su efecto sobre la importación.

## Prowlarr

Configura contraseña y autenticación requerida. Añade las fuentes que vas a usar
y prueba cada conexión. En Settings → Apps crea:

| Campo | Aplicación Radarr | Aplicación Sonarr |
|---|---|---|
| Prowlarr Server | `http://prowlarr:9696` | `http://prowlarr:9696` |
| Application Server | `http://radarr:7878` | `http://sonarr:8989` |
| API key | La de Radarr | La de Sonarr |
| Sync Level | Full Sync | Full Sync |

Pulsa **Test** y comprueba que aparecen los indexadores en Radarr/Sonarr. Si usas
solo torrents, no configures indexadores Usenet sin un cliente compatible.

## Bazarr

Accede a `http://localhost:6767` por el túnel SSH y configura autenticación. Bazarr
comparte exactamente `/data/media` con Radarr y Sonarr; **no añadas Path Mappings**.

En Settings → Sonarr:

| Campo | Valor |
|---|---|
| Enabled | Activado |
| Address | `sonarr` |
| Port | `8989` |
| Base URL | Vacío |
| API Key | La de Sonarr |
| SSL | Desactivado |

En Settings → Radarr:

| Campo | Valor |
|---|---|
| Enabled | Activado |
| Address | `radarr` |
| Port | `7878` |
| Base URL | Vacío |
| API Key | La de Radarr |
| SSL | Desactivado |

Pulsa **Test** y guarda cada integración. En Settings → Languages habilita Spanish
y crea un perfil, por ejemplo **Castellano**, con español como idioma requerido.
En Settings → Providers añade proveedores de subtítulos compatibles con tus cuentas
y prueba cada uno. En Settings → Subtitles conserva los subtítulos junto al archivo
multimedia. Aplica el perfil como predeterminado para nuevas películas y series; para
contenido ya existente usa Mass Edit en Movies y Series. Bazarr escribe los `.srt`
junto a los vídeos para que Jellyfin los detecte durante su actualización de biblioteca.

## Seerr

1. Selecciona **Jellyfin** y entra con la cuenta administradora dedicada. Ese usuario
   será propietario de Seerr y su token se utilizará para la integración.
2. URL interna: `http://jellyfin:8096`. URL externa: `https://TU_JELLYFIN_DOMAIN`.
3. Sincroniza las bibliotecas. En Settings → Services añade Radarr/Sonarr:

| Campo | Radarr | Sonarr |
|---|---|---|
| Hostname | `radarr` | `sonarr` |
| Puerto | `7878` | `8989` |
| Use SSL | Desactivado | Desactivado |
| API key | La de Radarr | La de Sonarr |
| Root folder | `/data/media/movies` | `/data/media/tv` |
| Quality Profile | El elegido en Radarr | El elegido en Sonarr |
| Default server | Activado | Activado |

4. Prueba ambas integraciones y configura la URL externa de Seerr con HTTPS.
5. Importa las cuentas de Jellyfin autorizadas. Permite login de cuentas enlazadas,
   pero desactiva el alta automática de nuevas cuentas desde el servidor multimedia
   si quieres admitir únicamente las que hayas importado expresamente.
6. Para cuentas normales permite **Request**, sin Admin ni Manage Users. Mantén
   aprobación manual al principio; después puedes habilitarla automáticamente en
   usuarios concretos. Configura límites de solicitudes para controlar el disco.

Flujo de uso: usuario solicita → aprobación → Radarr/Sonarr consultan fuentes
sincronizadas por Prowlarr → qBittorrent independiente descarga → importación → Jellyfin detecta
el archivo → Bazarr busca subtítulos → Seerr sincroniza disponibilidad. Son servicios separados, con dos
interfaces públicas y sesiones independientes. El contenido solicitado va a las
bibliotecas configuradas, compartidas por defecto.
